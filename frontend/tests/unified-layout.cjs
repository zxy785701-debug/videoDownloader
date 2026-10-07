const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
;(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext(), page = await context.newPage()
  const base = process.env.UNIFIED_TEST_URL || 'http://127.0.0.1:8186'
  const output = path.resolve(__dirname, '../../.local/unified-workspace-test')
  const list = await (await context.request.get(base + '/api/v1/analyses')).json()
  const record = list.items.find(r => r.summary_status === 'ready')
  assert.ok(record)
  const results = []
  try {
    await page.goto(base + '/#learn/' + record.id)
    await page.locator('.summary-overview h3').waitFor()
    await page.getByRole('button', { name: '下载', exact: true }).waitFor()
    for (const [width, height] of [[1440,900],[1366,768],[1280,720],[1024,600],[390,844],[375,812],[320,700]]) {
      await page.setViewportSize({ width, height })
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
      assert.equal(overflow, false)
      const download = await page.getByRole('button', { name: '下载', exact: true }).boundingBox()
      const summary = await page.locator('.summary-overview h3').boundingBox()
      if (width >= 1024) {
        assert.ok(download.y >= 0 && download.y + download.height <= height, JSON.stringify({ width,height,download }))
        assert.ok(summary.y >= 0 && summary.y + summary.height <= height, JSON.stringify({ width,height,summary }))
      }
      await page.screenshot({ path: path.join(output, 'layout-' + width + 'x' + height + '.png'), fullPage: width < 1024 })
      results.push({ width,height,overflow,download,summary })
    }
    await fs.writeFile(path.join(output, 'layout-results.json'), JSON.stringify(results, null, 2))
    console.log(JSON.stringify({ passed: results.length }))
  } finally { await browser.close() }
})().catch(e => { console.error(e.stack); process.exitCode = 1 })
