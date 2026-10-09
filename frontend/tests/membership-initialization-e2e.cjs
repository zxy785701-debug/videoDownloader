/* Controlled delays verify navigation and account state without any account/payment writes. */
const { chromium } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const base = process.env.MEMBERSHIP_TEST_APP_URL || 'http://127.0.0.1:8287'
const directory = process.env.MEMBERSHIP_TEST_DIR
if (!directory) throw new Error('MEMBERSHIP_TEST_DIR required')
let checks = 0
async function check(name, action) { await action(); checks++; process.stdout.write('PASS ' + name + '\n') }
const fulfill = (route, json, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(json) })
const guest = { detail: { code: 'LOGIN_REQUIRED', message: '请先登录。' } }
const options = { enabled: true, verification_required: false, mail_delivery: 'local_file', simulated: true }
const account = (email, limit = 3) => ({ email, simulated: true, order: null, quota: { limit, used: 0, reserved: 0, remaining: limit, member_expires: limit === 30 ? Date.now()/1000 + 86400 : null, day: '2026-10-08' } })

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const errors = []
  try {
    const page = await browser.newPage()
    page.on('pageerror', error => errors.push(error.message))
    let releaseSettings, settingsCount = 0, loggedIn = false
    const settingsGate = new Promise(resolve => { releaseSettings = resolve })
    await page.route('**/api/v1/account/config', route => fulfill(route, { enabled: true }))
    await page.route('**/api/v1/account/settings', async route => { settingsCount++; await settingsGate; await fulfill(route, options) })
    await page.route('**/api/v1/account/me', route => fulfill(route, loggedIn ? account('fast@example.com') : guest, loggedIn ? 200 : 401))
    await page.route('**/api/v1/account/login', route => { loggedIn = true; return fulfill(route, { message: '已登录。' }) })
    await page.goto(base)
    await check('account entry opens while remote settings remain pending', async () => {
      await page.getByRole('button', { name: '登录', exact: true }).click({ timeout: 3000 })
      assert(await page.getByRole('button', { name: '注册', exact: true }).isEnabled())
      assert.equal(settingsCount, 1)
    })
    await check('reopening dialog shares the pending settings request', async () => {
      await page.getByRole('button', { name: '关闭弹窗' }).click()
      await page.getByRole('button', { name: '登录', exact: true }).click()
      assert.equal(settingsCount, 1)
    })
    await check('login can complete before settings respond', async () => {
      await page.getByLabel('邮箱', { exact: true }).fill('fast@example.com')
      await page.getByLabel(/^密码/).fill('timing-test-password-long')
      await page.getByRole('button', { name: '登录账号', exact: true }).click()
      await page.getByText('fast@example.com · 普通用户').waitFor({ timeout: 3000 })
    })
    releaseSettings()
    await page.close()

    for (const lateStatus of [200, 401]) {
      const page = await browser.newPage()
      page.on('pageerror', error => errors.push(error.message))
      let releaseOld, reads = 0
      const oldGate = new Promise(resolve => { releaseOld = resolve })
      await page.route('**/api/v1/account/config', route => fulfill(route, { enabled: true }))
      await page.route('**/api/v1/account/settings', route => fulfill(route, options))
      await page.route('**/api/v1/account/login', route => fulfill(route, { message: '已登录。' }))
      await page.route('**/api/v1/account/me', async route => {
        if (++reads === 1) { await oldGate; await fulfill(route, lateStatus === 200 ? account('stale@example.com', 30) : guest, lateStatus) }
        else await fulfill(route, account('current@example.com'))
      })
      await page.goto(base)
      await page.getByRole('button', { name: '登录', exact: true }).click()
      await page.getByLabel('邮箱', { exact: true }).fill('current@example.com')
      await page.getByLabel(/^密码/).fill('timing-test-password-long')
      await page.getByRole('button', { name: '登录账号', exact: true }).click()
      await page.getByText('current@example.com · 普通用户').waitFor()
      const response = page.waitForResponse(r => r.url().endsWith('/api/v1/account/me') && r.status() === lateStatus)
      releaseOld()
      await response
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      await check('late initial status ' + lateStatus + ' cannot replace the newly logged-in account', async () => {
        assert(await page.getByText('current@example.com · 普通用户').isVisible())
        assert.equal(await page.getByText('stale@example.com · 会员').count(), 0)
        assert.equal(await page.getByRole('button', { name: '登录账号', exact: true }).count(), 0)
      })
      await page.close()
    }
    const personal = await browser.newPage()
    let cloudReads = 0
    await personal.route('**/api/v1/account/*', route => {
      if (route.request().url().endsWith('/config')) return fulfill(route, { enabled: false })
      cloudReads++
      return fulfill(route, guest, 401)
    })
    await personal.goto(base, { waitUntil: 'networkidle' })
    await check('personal mode keeps membership hidden and performs no account cloud reads', async () => {
      assert.equal(await personal.locator('.member-entry').count(), 0)
      assert.equal(cloudReads, 0)
    })
    await personal.close()
    await check('initialization scenarios have no browser runtime errors', async () => assert.deepEqual(errors, []))
    fs.writeFileSync(path.join(directory, 'initialization-report.json'), JSON.stringify({ checks, errors }, null, 2))
  } finally { await browser.close() }
})().catch(error => { console.error(error); process.exitCode = 1 })
