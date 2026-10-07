// Run against tests.unified_preview on 8186. Isolated SQLite and mock model only.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const base = process.env.UNIFIED_TEST_URL || 'http://127.0.0.1:8186'
const output = path.resolve(__dirname, '../../.local/unified-workspace-test')
const checks = [], errors = []
let browser, context, page, failed
const url = id => 'https://www.youtube.com/watch?v=' + id
async function check(name, action) { try { await action(); checks.push(name); console.log('PASS ' + name) } catch (error) { failed = { name, message: error.stack }; throw error } }
async function api(endpoint, data) { const result = await context.request.fetch(base + endpoint, data ? { method: 'POST', data } : {}); assert.ok(result.ok(), endpoint + ': ' + result.status()); return result.json() }
async function stats() { return api('/_test/unified/stats') }
async function eventually(action) { for (let n = 0; n < 150; n++) { if (await action()) return; await page.waitForTimeout(100) } assert.fail('Condition never reached') }
async function parse(source) { await page.getByLabel('视频页面链接', { exact: true }).fill(source); await page.getByRole('button', { name: '解析视频', exact: true }).click() }
async function summary() { await page.locator('.summary-overview h3').waitFor({ timeout: 20000 }) }
async function visibleInViewport(locator) { const box = await locator.boundingBox(), viewport = page.viewportSize(); assert.ok(box && box.y >= 0 && box.y + box.height <= viewport.height && box.x >= 0 && box.x + box.width <= viewport.width, JSON.stringify(box)) }
function listen(p) { p.on('pageerror', error => errors.push(error.message)) }
;(async () => {
  await fs.mkdir(output, { recursive: true })
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true })
  for (let attempt = 0; attempt < 60; attempt++) {
    if (await context.request.get(base + '/api/v1/ai/config').then(r => r.ok()).catch(() => false)) break
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  page = await context.newPage(); listen(page)
  try {
    let firstHash, initialCalls
    await check('默认自动总结，字幕未完成时先显示可下载的信息', async () => {
      await page.goto(base)
      assert.equal(await page.getByRole('checkbox', { name: '解析后自动总结' }).isChecked(), true)
      await parse(url('slowcaption'))
      await page.getByRole('heading', { name: '【模拟验收】视频信息 slowcaption', exact: true }).waitFor()
      await visibleInViewport(page.getByRole('button', { name: '下载', exact: true }))
      await eventually(async () => new URL(page.url()).hash.startsWith('#learn/'))
      firstHash = new URL(page.url()).hash
      const record = await api('/api/v1/analyses/' + firstHash.slice(7))
      assert.ok(['pending', 'fetching'].includes(record.subtitle_status))
      assert.equal(record.jobs.find(job => job.kind === 'auto_summary').status, 'queued')
      await page.getByRole('checkbox', { name: '解析后自动总结' }).uncheck()
      initialCalls = (await stats()).summary
      assert.equal(initialCalls, 0)
    })
    await check('关闭页面后字幕继续接续总结，恢复旧地址不重复调用', async () => {
      await page.close()
      page = await context.newPage(); listen(page)
      await api('/_test/unified/release', { kind: 'caption' })
      await page.goto(base + '/' + firstHash)
      await summary()
      assert.equal((await stats()).summary, initialCalls + 1)
      await visibleInViewport(page.getByRole('button', { name: '下载', exact: true }))
      await visibleInViewport(page.locator('.summary-overview h3'))
      await page.screenshot({ path: path.join(output, 'desktop-summary.png') })
    })
    await check('重复解析、刷新和页签切换复用保存结果，无摘要 POST 或新模型请求', async () => {
      let posts = 0
      page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/summary')) posts++ })
      await parse(url('slowcaption')); await summary()
      await page.reload(); await summary()
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByRole('button', { name: '摘要', exact: true }).click()
      assert.equal((await stats()).summary, initialCalls + 1); assert.equal(posts, 0)
    })
    await check('下载使用已解析链接及真实格式 ID，处理中锁定切换但保留学习功能', async () => {
      await page.getByLabel('视频清晰度与格式').selectOption('video:137')
      await page.getByLabel('视频页面链接').fill(url('different01'))
      await page.getByRole('button', { name: '下载', exact: true }).click()
      await eventually(async () => (await stats()).downloads.length === 1)
      assert.deepEqual((await stats()).downloads[0], { url: url('slowcaption'), format_id: 'video:137', delivery_mode: 'auto' })
      assert.equal(await page.getByLabel('视频页面链接').isDisabled(), true)
      assert.equal(await page.getByRole('button', { name: '换个链接', exact: true }).isDisabled(), true)
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByRole('button', { name: '下载字幕', exact: true }).waitFor()
      await page.getByRole('button', { name: /^本机学习记录/ }).click()
      assert.equal(await page.getByRole('button', { name: /^删除记录/ }).isDisabled(), true)
      await page.keyboard.press('Escape')
      await api('/_test/unified/release', { kind: 'download' })
      await page.getByRole('link', { name: '保存到设备', exact: true }).waitFor()
      const pending = page.waitForEvent('download')
      await page.getByRole('link', { name: '保存到设备', exact: true }).click()
      const file = await pending
      assert.equal(file.suggestedFilename(), 'simulated-download.mp4')
    })
    await check('关闭自动总结后获取字幕、导出原文，刷新保留偏好，手动生成可用', async () => {
      await page.getByRole('button', { name: '换个链接', exact: true }).click()
      await page.getByRole('checkbox', { name: '解析后自动总结' }).uncheck()
      await parse(url('manualtest1'))
      const generate = page.getByRole('button', { name: '生成总结', exact: true })
      await eventually(async () => await generate.isEnabled())
      assert.equal((await stats()).summary, initialCalls + 1)
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      const pending = page.waitForEvent('download')
      await page.getByRole('button', { name: '下载字幕', exact: true }).click()
      assert.match((await pending).suggestedFilename(), /\.srt$/)
      await page.reload()
      assert.equal(await page.getByRole('checkbox', { name: '解析后自动总结' }).isChecked(), false)
      await generate.click(); await summary()
      assert.equal((await stats()).summary, initialCalls + 2)
    })
    await check('下载状态暂时断线自动恢复，任务过期解除切换锁定', async () => {
      let polls = 0, posts = 0, expired = false
      await page.route('**/api/v1/downloads', route => {
        posts++
        return route.fulfill({ status: 202, json: { task_id: 'mock-task', status: 'pending', status_url: '/api/v1/downloads/mock-task', download_url: '/api/v1/downloads/mock-task/file' } })
      })
      await page.route('**/api/v1/downloads/mock-task', route => {
        if (expired) return route.fulfill({ status: 404, json: { detail: '下载任务不存在或已过期' } })
        if (++polls === 1) return route.abort('failed')
        return route.fulfill({ json: { task_id: 'mock-task', status: 'ready', delivery_mode: 'server', progress: 100, filename: 'mock.mp4', error: null, expires_at: '' } })
      })
      await page.getByRole('button', { name: '下载', exact: true }).click()
      await page.getByText('状态更新已中断', { exact: true }).waitFor()
      assert.equal(await page.getByLabel('视频页面链接').isDisabled(), true)
      await page.getByRole('link', { name: '保存到设备', exact: true }).waitFor({ timeout: 10000 })
      assert.equal(posts, 1)
      expired = true
      await page.getByRole('button', { name: '重新准备文件', exact: true }).click()
      await page.getByRole('button', { name: '重试下载', exact: true }).waitFor()
      assert.equal(await page.getByLabel('视频页面链接').isDisabled(), false)
      assert.equal(posts, 2)
      await page.unroute('**/api/v1/downloads'); await page.unroute('**/api/v1/downloads/mock-task')
    })
    await check('切换字幕语言和历史记录不自动生成新摘要', async () => {
      await page.getByLabel('切换字幕语言').selectOption('en')
      await eventually(async () => await page.getByRole('button', { name: '生成总结', exact: true }).isEnabled())
      assert.equal(await page.locator('.summary-overview').count(), 0)
      assert.equal((await stats()).summary, initialCalls + 2)
      await page.getByRole('button', { name: /^本机学习记录/ }).click()
      await page.locator('.history-select').filter({ hasText: 'slowcaption' }).click()
      await summary()
      assert.equal((await stats()).summary, initialCalls + 2)
    })
    await check('桌面同屏和 320–1024px 响应式布局无横向溢出', async () => {
      for (const width of [1440, 1280, 1024, 900, 768, 600, 390, 375, 320]) {
        await page.setViewportSize({ width, height: width >= 1024 ? 768 : 812 })
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'width ' + width)
        if (width >= 1024) {
          await visibleInViewport(page.getByRole('button', { name: '下载', exact: true }))
          await visibleInViewport(page.locator('.summary-overview h3'))
        }
        if (width === 375) await page.screenshot({ path: path.join(output, 'mobile-summary.png'), fullPage: true })
      }
      await page.setViewportSize({ width: 1280, height: 900 })
    })
    await check('无字幕不调用模型，重复解析不自动重试，视频下载仍可用', async () => {
      await page.getByRole('checkbox', { name: '解析后自动总结' }).check()
      await parse(url('nocaptions1'))
      await page.getByText('【模拟验收】没有可提取字幕，暂不能总结，仍可下载视频。', { exact: true }).waitFor()
      const before = await stats()
      assert.equal(before.summary, initialCalls + 2)
      assert.equal(await page.getByRole('button', { name: '生成总结', exact: true }).isDisabled(), true)
      assert.equal(await page.getByRole('button', { name: '下载', exact: true }).isEnabled(), true)
      await parse(url('nocaptions1'))
      await page.getByText('【模拟验收】没有可提取字幕，暂不能总结，仍可下载视频。', { exact: true }).waitFor()
      assert.equal((await stats()).captions.length, before.captions.length)
    })
    await check('下载支持而 AI 未支持的平台显示明确说明，不建立字幕任务', async () => {
      const before = await stats()
      await parse('https://www.mgtv.com/b/123/456.html')
      await page.getByRole('heading', { name: '暂不能总结这个视频', exact: true }).waitFor()
      assert.equal(await page.getByRole('button', { name: '下载', exact: true }).isEnabled(), true)
      assert.equal((await stats()).captions.length, before.captions.length)
      assert.equal((await stats()).summary, before.summary)
    })
    await check('解析失败不提交自动总结，迟到的解析响应不能覆盖历史选择', async () => {
      const before = await stats()
      await parse(url('parsefails1'))
      await page.locator('#input-error').waitFor()
      assert.equal((await stats()).summary, before.summary)
      assert.equal((await stats()).captions.length, before.captions.length)
      await parse(url('lateparse01'))
      await page.getByRole('button', { name: /^本机学习记录/ }).click()
      await page.locator('.history-select').filter({ hasText: 'slowcaption' }).click()
      await summary()
      await page.waitForTimeout(3500)
      await page.getByRole('heading', { name: '【模拟验收】视频信息 slowcaption', exact: true }).waitFor()
      assert.equal((await stats()).captions.length, before.captions.length)
    })
    await check('模型未配置仍自动获取字幕并可下载，不产生模型调用', async () => {
      await page.route('**/api/v1/ai/config', async route => { const response = await route.fetch(); await route.fulfill({ response, json: { ...await response.json(), configured: false } }) })
      await page.goto(base + '/#learn')
      await page.reload()
      await parse(url('nokeytest01'))
      await page.getByText('DeepSeek 尚未配置，字幕和视频下载已可使用。', { exact: true }).waitFor()
      assert.equal((await stats()).summary, initialCalls + 2)
      assert.equal(await page.getByRole('button', { name: '下载', exact: true }).isEnabled(), true)
      await page.unroute('**/api/v1/ai/config')
    })
    await check('自动总结失败后重复解析不重试付费任务，手动重试入口保留', async () => {
      await page.goto(base + '/#learn')
      await page.reload()
      await parse(url('badsummary1'))
      await page.getByRole('button', { name: '重试总结', exact: true }).waitFor({ timeout: 15000 })
      const before = (await stats()).summary
      await parse(url('badsummary1'))
      await page.getByRole('button', { name: '重试总结', exact: true }).waitFor()
      assert.equal((await stats()).summary, before)
      assert.equal(await page.getByRole('button', { name: '下载', exact: true }).isEnabled(), true)
    })
    assert.deepEqual(errors, [])
  } finally {
    if (failed) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {})
    await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ simulation: true, checks, failed, pageErrors: errors }, null, 2))
    console.log(JSON.stringify({ passed: checks.length, failed, pageErrors: errors }))
    await browser.close()
  }
})().catch(error => { console.error(error.stack); process.exitCode = 1 })
