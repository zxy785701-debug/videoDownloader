/* Separate mock billing + real local HTTP proxy + actual Vue interface. No real money/model. */
const { chromium } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const base = process.env.MEMBERSHIP_TEST_APP_URL || 'http://127.0.0.1:8187'
const dir = process.env.MEMBERSHIP_TEST_DIR
const verificationRequired = process.env.MEMBERSHIP_TEST_VERIFY_EMAIL === '1'
if (!dir) throw new Error('MEMBERSHIP_TEST_DIR required')
let checks = 0
const timings = {}
async function check(label, action) { await action(); checks++; process.stdout.write('PASS ' + label + '\n') }
async function account(page, operation, data) {
  return page.evaluate(async ({ operation, data }) => {
    const response = await fetch('/api/v1/account/' + operation, { method: data === undefined ? 'GET' : 'POST', headers: data === undefined ? {} : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) })
    return { status: response.status, data: await response.json() }
  }, { operation, data })
}
function mailCode() {
  const files = fs.readdirSync(path.join(dir, 'mail')).map(name => path.join(dir, 'mail', name)).sort((a,b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)
  const content = fs.readFileSync(files[0], 'utf8')
  const [headers, ...parts] = content.split(/\r?\n\r?\n/)
  let body = parts.join('\n\n')
  if (/Content-Transfer-Encoding: base64/i.test(headers)) body = Buffer.from(body, 'base64').toString('utf8')
  if (/Content-Transfer-Encoding: quoted-printable/i.test(headers)) body = body.replace(/=\r?\n/g, '').replace(/=([0-9A-F]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
  return body.match(/^([A-Za-z0-9_-]{43})\r?$/m)[1]
}
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    if (process.env.MEMBERSHIP_LAYOUT_ONLY === '1') {
      await page.goto(base)
      assert.equal((await account(page, 'login', { email: 'browser@example.com', password: 'browser-password-long' })).status, 200)
      await page.reload()
      for (const width of [1280, 390, 320]) {
        await page.setViewportSize({ width, height: width === 1280 ? 900 : 844 })
        if (!(await page.getByRole('heading', { name: '账号与会员' }).isVisible())) await page.getByRole('button', { name: 'VIP', exact: true }).click()
        await check('member layout ' + width, async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)))
        await page.screenshot({ path: path.join(dir, 'member-' + width + '.png'), fullPage: true })
      }
      return
    }
    const navigationStart = performance.now()
    await page.goto(base)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    timings.accountEntryMs = Math.round(performance.now() - navigationStart)
    await check('guest can open account dialog with correct verification policy', async () => {
      assert(await page.getByRole('heading', { name: '登录账号', exact: true }).isVisible())
      await page.getByText('当前为本机模拟支付，不会真实扣款。').waitFor()
      assert.equal(await page.getByRole('button', { name: '验证邮箱', exact: true }).count(), verificationRequired ? 1 : 0)
      assert(await page.getByText('当前为本机模拟支付，不会真实扣款。').isVisible())
    })
    await page.getByRole('button', { name: '注册', exact: true }).click()
    await page.getByLabel('邮箱', { exact: true }).fill('browser@example.com')
    await page.getByLabel(/^密码/).fill('browser-password-long')
    const registered = page.waitForResponse(response => response.url().endsWith('/api/v1/account/register'))
    const registrationStart = performance.now()
    await page.getByRole('button', { name: '创建账号' }).click()
    const registrationResponse = await registered
    timings.registrationMs = Math.round(performance.now() - registrationStart)
    assert.equal(registrationResponse.status(), 200)
    await check('registration follows the configured email policy', async () => {
      assert.equal((await registrationResponse.json()).verification_required, verificationRequired)
      if (verificationRequired) {
        await page.getByLabel('邮箱验证码').waitFor()
        assert(await page.getByText(/未发送到真实邮箱/).isVisible())
        await page.getByLabel('邮箱验证码').fill(mailCode())
        await page.getByRole('button', { name: '完成验证' }).click()
      } else {
        await page.getByRole('button', { name: '登录账号', exact: true }).waitFor()
        assert.equal(await page.getByLabel('邮箱验证码').count(), 0)
        assert(!fs.existsSync(path.join(dir, 'mail')) || fs.readdirSync(path.join(dir, 'mail')).length === 0)
      }
    })
    await page.getByLabel(/^密码/).fill('browser-password-long')
    const loginStart = performance.now()
    await page.getByRole('button', { name: '登录账号' }).click()
    await check('registration and login reach free account', async () => { await page.getByText('今日已用 0 / 3 次').waitFor(); assert(await page.getByText('browser@example.com · 普通用户').isVisible()) })
    timings.loginAndStatusMs = Math.round(performance.now() - loginStart)
    await check('cookie is HttpOnly and credentials are absent from web storage', async () => {
      const cookies = await context.cookies(); assert(cookies.find(c => c.name === 'saveany_account')?.httpOnly)
      const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }))
      assert(!storage.includes('browser-password') && !storage.includes('saveany_account') && !storage.includes('Bearer'))
    })
    const popupPromise = page.waitForEvent('popup')
    await page.getByRole('button', { name: '购买会员', exact: true }).click()
    const popup = await popupPromise
    await popup.waitForLoadState()
    await check('mock payment page is clearly labelled', async () => assert(await popup.getByRole('heading', { name: '仅限本机模拟，不会扣款' }).isVisible()))
    const url = popup.url()
    await check('checkout and form stay on the authenticated application origin', async () => {
      assert.equal(new URL(url).origin, new URL(base).origin)
      assert.match(new URL(url).pathname, /^\/dev\/checkout\/cs_test_mock_[A-Za-z0-9_-]{32}$/)
      assert.equal(await popup.locator('form').getAttribute('action'), new URL(url).pathname)
      assert(await popup.locator('input[name="csrf"]').getAttribute('value'))
    })
    await popup.getByRole('button', { name: '取消并返回' }).click()
    await check('cancel retains the unpaid order and returns to the same website', async () => {
      assert(!(await account(page, 'refresh', {})).data.quota.member_expires)
      assert.equal((await account(page, 'me')).data.order.status, 'open')
      await popup.getByRole('link', { name: '返回 SaveAny', exact: true }).click()
      await popup.waitForURL(base + '/')
      assert.equal(new URL(popup.url()).origin, new URL(base).origin)
    })
    await popup.goto(url)
    await popup.getByRole('button', { name: '模拟银行卡拒付' }).click()
    await page.getByRole('button', { name: '刷新会员状态' }).click()
    await check('declined payment leaves account free', async () => { await page.getByText('今日已用 0 / 3 次').waitFor(); assert(!(await account(page, 'me')).data.quota.member_expires) })
    await check('repeat purchase reuses same hosted session', async () => { const result = await account(page, 'checkout', {}); assert.equal(new URL(result.data.checkout_url, base).href, url) })
    await popup.goto(url)
    const paidResponse = popup.waitForResponse(response => response.request().method() === 'POST' && response.url() === url)
    await popup.getByRole('button', { name: '模拟付款成功' }).click()
    assert.equal((await paidResponse).status(), 200)
    await page.getByRole('button', { name: '刷新会员状态' }).click()
    await check('paid account shows 30/day and blocks active repurchase', async () => { await page.getByText('今日已用 0 / 30 次').waitFor(); assert(await page.getByRole('button', { name: '会员已开通', exact: true }).isDisabled()); assert.equal((await account(page, 'checkout', {})).data.detail.code, 'ALREADY_MEMBER') })
    await check('paid return and reload preserve server-confirmed order and membership', async () => {
      assert.equal((await account(page, 'refresh', {})).data.order.status, 'paid')
      await popup.getByRole('link', { name: '返回 SaveAny', exact: true }).click()
      await popup.waitForURL(base + '/')
      assert.equal((await account(popup, 'me')).data.quota.limit, 30)
      await popup.reload()
      assert.equal((await account(popup, 'me')).data.order.status, 'paid')
    })
    await page.screenshot({ path: path.join(dir, 'member-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await check('mobile dialog fits viewport', async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)))
    await page.screenshot({ path: path.join(dir, 'member-mobile.png'), fullPage: true })
    await page.getByRole('button', { name: '退出登录', exact: true }).click()
    await check('logout removes account and backend session', async () => { await page.getByRole('button', { name: '登录账号' }).waitFor(); assert.equal((await account(page, 'me')).status, 401) })
    await check('password reset clearly shows local mail and accepts the saved code', async () => {
      await page.getByRole('button', { name: '找回密码', exact: true }).click()
      assert(await page.getByText('当前未接通真实邮件。邮件只保存为本机测试文件，真实邮箱收不到。').isVisible())
      const sent = page.waitForResponse(response => response.url().endsWith('/api/v1/account/forgot-password'))
      await page.getByRole('button', { name: '生成本机测试重置邮件', exact: true }).click()
      assert.equal((await sent).status(), 200)
      await page.getByText(/未发送到真实邮箱/).waitFor()
      await page.getByLabel('邮件重置码').fill(mailCode())
      await page.getByLabel(/^新密码/).fill('browser-password-long')
      await page.getByRole('button', { name: '重置密码', exact: true }).click()
      await page.getByRole('button', { name: '登录账号', exact: true }).waitFor()
      assert(await page.getByText('密码已重置，旧登录已失效，请重新登录。').isVisible())
    })
    await page.getByRole('button', { name: '关闭弹窗' }).click()
    await check('download parse stays available to guest', async () => {
      const result = await page.evaluate(async () => { const r = await fetch('/api/v1/parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: 'https://www.youtube.com/watch?v=abcdefghijk' }) }); return r.status }); assert.equal(result, 200)
    })
    await check('no browser runtime errors', async () => assert.deepEqual(errors, []))
    fs.writeFileSync(path.join(dir, 'browser-report.json'), JSON.stringify({ checks, errors, simulated: true, verificationRequired, timings }, null, 2))
    process.stdout.write(`Membership browser: ${checks} passed\n`)
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
