// Acceptance of persisted, real DeepSeek outputs. No new paid generation calls.
const { chromium } = require('playwright')
const fs = require('node:fs/promises')
const path = require('node:path')
const assert = require('node:assert/strict')

;(async () => {
  const folder = path.resolve(__dirname, '../../.local/learning-real-probes')
  const report = JSON.parse(await fs.readFile(path.join(folder, 'ai-results.json'), 'utf8'))
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const errors = []
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    page.on('pageerror', error => errors.push(error.message))
    for (const result of report.summaries) {
      assert.equal(result.status, 'ready')
      await page.goto('http://127.0.0.1:8181/#learn/' + result.id)
      await page.getByRole('heading', { name: result.result.summary.content.headline, exact: true }).waitFor({ state: 'visible' })
      assert.equal(await page.locator('.summary-chapters > li').count(), result.result.summary.content.chapters.length)
      await page.screenshot({ path: path.join(folder, 'real-' + result.platform.toLowerCase() + '-summary.png'), fullPage: true })
      await page.locator('.learning-reference').first().click()
      await page.locator('.cue-highlighted').waitFor({ state: 'visible' })
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.locator('.map-canvas').waitFor({ state: 'visible' })
      const nodes = page.locator('g.map-node[aria-expanded="false"]')
      if (await nodes.count()) await nodes.first().click()
      await page.getByRole('button', { name: '放大导图' }).click()
      await page.getByRole('button', { name: '适配视图' }).click()
      await page.locator('.map-visual').screenshot({ path: path.join(folder, 'real-' + result.platform.toLowerCase() + '-mindmap.png') })
      if (result.platform === 'YouTube') {
        await page.getByRole('button', { name: '视频问答', exact: true }).click()
        assert.equal(await page.locator('.chat-turn').count(), report.questions.length)
        assert.equal(await page.getByText('字幕依据不足', { exact: true }).count(), 2)
        await page.locator('.chat-messages').screenshot({ path: path.join(folder, 'real-youtube-chat.png') })
        await page.reload()
        await page.getByRole('heading', { name: result.result.summary.content.headline, exact: true }).waitFor({ state: 'visible' })
        await page.getByRole('button', { name: '视频问答', exact: true }).click()
        assert.equal(await page.locator('.chat-turn').count(), report.questions.length)
        await page.goBack()
        await page.getByRole('heading', { name: report.summaries[0].result.summary.content.headline, exact: true }).waitFor({ state: 'visible' })
        await page.goForward()
        await page.getByRole('heading', { name: result.result.summary.content.headline, exact: true }).waitFor({ state: 'visible' })
        await page.setViewportSize({ width: 375, height: 812 })
        await page.getByRole('button', { name: '思维导图', exact: true }).click()
        await page.locator('.map-mobile-list').waitFor({ state: 'visible' })
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
        await page.screenshot({ path: path.join(folder, 'real-mobile-mindmap.png'), fullPage: true })
      }
    }
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ simulation: false, realSummaryPages: report.summaries.length, hashRecordSwitch: true, browserBackForward: true, references: true, mindmap: true, realChatTurns: report.questions.length, reloadRestores: true, mobile: true, pageErrors: errors }))
  } finally { await browser.close() }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
