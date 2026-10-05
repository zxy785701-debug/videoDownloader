// Run against the isolated backend/tests/learning_preview.py server.
// Requires Playwright (or the Codex bundled package via NODE_PATH).
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')

const base = process.env.LEARNING_TEST_URL || 'http://127.0.0.1:8180'
const artifacts = path.resolve(__dirname, '../../.local/learning-browser-test')
const checks = []
const failures = []
const errors = []

async function check(name, action) {
  try { await action(); checks.push(name) }
  catch (error) { failures.push({ name, message: error.message }); throw error }
}
async function visible(page, text) {
  await page.getByText(text, { exact: true }).first().waitFor({ state: 'visible', timeout: 10000 })
}
async function noOverflow(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
}

;(async () => {
  await fs.mkdir(artifacts, { recursive: true })
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true, reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  try {
    await check('下载首页与原有解析流程', async () => {
      await page.goto(base)
      await page.getByLabel('视频页面链接').fill('https://www.youtube.com/watch?v=abcdefghijk')
      await page.getByRole('button', { name: '解析视频', exact: true }).click()
      await visible(page, '【模拟验收】原有下载流程')
      await page.getByRole('button', { name: '下载', exact: true }).click()
      await page.getByRole('link', { name: '保存到设备', exact: true }).waitFor({ state: 'visible' })
      await page.getByRole('button', { name: '获取字幕与 AI 总结', exact: true }).click()
    })
    await check('真实后端接口创建字幕记录（模拟平台数据）', async () => {
      await page.getByRole('button', { name: '获取字幕', exact: true }).click()
      await visible(page, '【模拟验收】长视频学习方法')
      await page.getByRole('button', { name: '生成总结', exact: true }).waitFor({ state: 'visible' })
      await noOverflow(page)
    })
    await check('摘要、用量与 Markdown 导出', async () => {
      await page.getByRole('button', { name: '生成总结', exact: true }).click()
      await visible(page, '理解、练习与主动回忆形成学习闭环')
      await visible(page, '先回想概念，再用例子检验，发现理解漏洞。')
      const downloadEvent = page.waitForEvent('download')
      await page.getByRole('link', { name: '导出 Markdown', exact: true }).click()
      const download = await downloadEvent
      assert.equal(download.suggestedFilename(), 'video-summary.md')
      await download.saveAs(path.join(artifacts, 'summary.md'))
      assert.match(await fs.readFile(path.join(artifacts, 'summary.md'), 'utf8'), /主动回忆/)
      await page.screenshot({ path: path.join(artifacts, 'desktop-summary.png'), fullPage: true })
    })
    await check('摘要引用跳转到第 150 段原文，并正确分页', async () => {
      await page.getByRole('button', { name: '49:40 原文', exact: true }).first().click()
      const cue = page.locator('#cue-c000150')
      await cue.waitFor({ state: 'visible' })
      assert.match(await cue.innerText(), /主动回忆/)
      assert.match(await cue.getAttribute('class'), /cue-highlighted/)
      await page.getByLabel('搜索字幕').fill('主动回忆')
      await page.getByRole('button', { name: '搜索', exact: true }).click()
      await visible(page, '1–1 / 1 段')
      const downloadEvent = page.waitForEvent('download')
      await page.getByRole('link', { name: '导出 SRT', exact: true }).click()
      const download = await downloadEvent
      assert.equal(download.suggestedFilename(), 'video-subtitles.srt')
      await download.saveAs(path.join(artifacts, 'subtitles.srt'))
      assert.match(await fs.readFile(path.join(artifacts, 'subtitles.srt'), 'utf8'), /00:49:40,000/)
    })
    await check('思维导图缩放、折叠与原文定位', async () => {
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      const node = page.locator('g.map-node').filter({ has: page.locator('title').filter({ hasText: /^主动回忆$/ }) })
      await node.waitFor({ state: 'visible' })
      assert.equal(await node.getAttribute('aria-expanded'), 'false')
      await node.click()
      assert.equal(await node.getAttribute('aria-expanded'), 'true')
      await page.getByRole('button', { name: '放大导图' }).click()
      await page.getByRole('button', { name: '缩小导图' }).click()
      await page.getByRole('button', { name: '适配视图' }).click()
      await page.screenshot({ path: path.join(artifacts, 'desktop-mindmap.png'), fullPage: true })
      await page.getByRole('button', { name: '查看对应字幕', exact: true }).click()
      await page.locator('#cue-c000150').waitFor({ state: 'visible' })
    })
    await check('视频问答、连续追问和依据不足提示', async () => {
      await page.getByRole('button', { name: '视频问答', exact: true }).click()
      await page.getByLabel('你的问题').fill('如何检查学习效果？')
      await page.getByRole('button', { name: '发送问题', exact: true }).click()
      await visible(page, '可以通过主动回忆检查：先回想概念，再用例子检验。')
      await page.getByLabel('你的问题').fill('这个方法有哪些步骤？')
      await page.getByRole('button', { name: '发送问题', exact: true }).click()
      await page.locator('.chat-turn').nth(1).locator('.chat-answer').getByText('可以通过主动回忆检查：先回想概念，再用例子检验。', { exact: true }).waitFor({ state: 'visible' })
      await page.getByLabel('你的问题').fill('画面中的图表用了什么颜色？')
      await page.getByRole('button', { name: '发送问题', exact: true }).click()
      await visible(page, '字幕依据不足')
      await page.screenshot({ path: path.join(artifacts, 'desktop-chat.png'), fullPage: true })
    })
    await check('退出学习工作区后保留原下载任务', async () => {
      const learnHash = new URL(page.url()).hash
      await page.getByRole('button', { name: '返回视频下载', exact: true }).click()
      await page.getByRole('button', { name: '查看解析结果', exact: true }).click()
      await page.getByRole('link', { name: '保存到设备', exact: true }).waitFor({ state: 'visible' })
      await page.getByRole('button', { name: '获取字幕与 AI 总结', exact: true }).click()
      await page.evaluate(hash => { window.location.hash = hash }, learnHash)
      await page.reload()
    })
    await check('刷新恢复摘要和完整对话', async () => {
      const hash = new URL(page.url()).hash
      await page.reload()
      await visible(page, '理解、练习与主动回忆形成学习闭环')
      assert.equal(new URL(page.url()).hash, hash)
      await page.getByRole('button', { name: '视频问答', exact: true }).click()
      assert.equal(await page.locator('.chat-turn').count(), 3)
    })
    await check('375px 窄屏摘要、导图列表与无横向溢出', async () => {
      await page.setViewportSize({ width: 375, height: 812 })
      await page.getByRole('button', { name: '摘要', exact: true }).click()
      await noOverflow(page)
      await page.screenshot({ path: path.join(artifacts, 'mobile-summary.png'), fullPage: true })
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.locator('.map-mobile-list').waitFor({ state: 'visible' })
      await noOverflow(page)
      await page.screenshot({ path: path.join(artifacts, 'mobile-mindmap.png'), fullPage: true })
    })
    await check('清空对话的确认与持久化删除', async () => {
      await page.setViewportSize({ width: 1280, height: 900 })
      await page.getByRole('button', { name: '视频问答', exact: true }).click()
      await page.getByRole('button', { name: '清空对话', exact: true }).click()
      await page.getByRole('button', { name: '确认清空', exact: true }).click()
      await page.getByRole('button', { name: '概括核心知识', exact: true }).waitFor({ state: 'visible' })
      assert.equal(await page.locator('.chat-turn').count(), 0)
    })
    await check('字幕语言切换建立独立记录', async () => {
      await page.getByLabel('切换字幕语言').selectOption('en')
      await page.locator('p.learning-muted').filter({ hasText: /^en · 人工字幕$/ }).waitFor({ state: 'visible' })
      assert.equal(await page.locator('.history-item').count(), 2)
      assert.equal(await page.locator('.summary-overview').count(), 0)
    })
    await check('无字幕时阻止总结、导图和问答，保留下载入口', async () => {
      await page.getByLabel('视频链接', { exact: true }).fill('https://www.youtube.com/watch?v=nocaptions')
      await page.getByRole('button', { name: '获取字幕', exact: true }).click()
      await page.getByText('【模拟验收】没有可提取字幕，暂不能总结，仍可下载视频。', { exact: true }).waitFor({ state: 'visible' })
      assert.equal(await page.getByRole('button', { name: '生成总结', exact: true }).isDisabled(), true)
      assert.equal(await page.getByRole('button', { name: '下载视频', exact: true }).isEnabled(), true)
    })
    await check('删除学习记录，不影响原下载任务', async () => {
      await page.locator('.history-item.history-selected').getByRole('button', { name: /^删除记录/ }).click()
      await page.getByRole('button', { name: '确认删除', exact: true }).click()
      await page.waitForFunction(() => document.querySelectorAll('.history-item').length === 2)
      await page.getByRole('button', { name: '返回视频下载', exact: true }).click()
      // Original downloads use page-memory state: reload has always reset their UI.
      // Check a fresh download after deletion rather than claiming reload persistence.
      await page.setViewportSize({ width: 375, height: 812 })
      await noOverflow(page)
      await page.setViewportSize({ width: 1280, height: 900 })
      await page.getByLabel('视频页面链接').fill('https://www.youtube.com/watch?v=abcdefghijk')
      await page.getByRole('button', { name: '解析视频', exact: true }).click()
      await visible(page, '【模拟验收】原有下载流程')
      await page.getByRole('button', { name: '下载', exact: true }).click()
      await page.getByRole('link', { name: '保存到设备', exact: true }).waitFor({ state: 'visible' })
      const downloadEvent = page.waitForEvent('download')
      await page.getByRole('link', { name: '保存到设备', exact: true }).click()
      const download = await downloadEvent
      assert.equal(download.suggestedFilename(), 'simulated-download.mp4')
      await download.saveAs(path.join(artifacts, 'simulated-download.mp4'))
    })
    assert.deepEqual(errors, [])
  } catch (error) {
    await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true }).catch(() => {})
    console.error(error.message)
    process.exitCode = 1
  } finally {
    await fs.writeFile(path.join(artifacts, 'results.json'), JSON.stringify({ simulation: true, checks, failures, pageErrors: errors }, null, 2))
    console.log(JSON.stringify({ passed: checks.length, failed: failures.length, checks, failures, pageErrors: errors }))
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
