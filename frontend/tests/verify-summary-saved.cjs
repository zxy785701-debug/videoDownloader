// Read-only verification after deploying the backend and restoring a real result.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const [base, sourceReport, output] = process.argv.slice(2)
if (!base || !sourceReport || !output) throw new Error('Provide base URL, successful live report and output directory.')
;(async () => {
  const expected = JSON.parse(await fs.readFile(sourceReport, 'utf8'))
  assert.ok(expected.ok && expected.simulation === false)
  const recordId = expected.job.analysis_id
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
  const report = { ok: false, pageErrors: [], generationRequests: 0 }
  page.on('pageerror', error => report.pageErrors.push(error.message))
  page.on('request', request => { if (request.method() === 'POST') report.generationRequests++ })
  const api = async suffix => (await page.request.get(base + '/api/v1/analyses/' + recordId + suffix)).json()
  try {
    await fs.mkdir(output, { recursive: true })
    const config = await (await page.request.get(base + '/api/v1/ai/config')).json()
    assert.equal(config.summary_stream_version, 2)
    const before = await api('')
    assert.equal(before.summary_status, 'ready')
    const result = await api('/summary')
    assert.deepEqual(result.summary, expected.summary)
    await page.goto(base + '/#learn/' + recordId)
    await page.locator('.summary-overview h3').waitFor()
    assert.equal(await page.locator('.summary-chapters > li').count(), expected.chapters)
    assert.match(await page.locator('.summary-chapters > li').last().textContent(), /学习路径/)
    assert.equal(await page.locator('.summary-stream-preview').count(), 0)
    assert.equal(await page.getByText('模型输出不完整或被中断，未保存为成功结果。', { exact: true }).count(), 0)
    // The app scrolls inside .learning-layout. Check actual scrolling, then
    // enlarge only the test viewport for a complete, unclipped artifact.
    for (const chapter of await page.locator('.summary-chapters > li > article > h3').all()) {
      await chapter.evaluate(node => node.scrollIntoView({ block: 'center', behavior: 'instant' }))
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      const bounds = await chapter.boundingBox()
      const scrollArea = await page.locator('.learning-layout').boundingBox()
      assert.ok(bounds.y >= scrollArea.y && bounds.y + bounds.height <= scrollArea.y + scrollArea.height,
        JSON.stringify({ title: await chapter.textContent(), bounds, scrollArea }))
    }
    await page.locator('.summary-chapters > li').last().locator('ul > li').last().scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(output, 'last-chapter.png') })
    const panelHeight = Math.ceil((await page.locator('.learning-panel').boundingBox()).height)
    await page.setViewportSize({ width: 1366, height: panelHeight + 800 })
    await page.locator('.learning-panel').screenshot({ path: path.join(output, 'complete-summary.png') })
    await page.setViewportSize({ width: 1366, height: 900 })
    const lastPoint = result.summary.content.chapters.at(-1).points.at(-1)
    await page.locator('.summary-chapters > li').last().locator('ul > li').last().locator('.learning-reference').last().click()
    const cue = page.locator('#cue-' + lastPoint.references.at(-1).cue_id)
    await cue.waitFor(); assert.match(await cue.getAttribute('class'), /cue-highlighted/)
    await page.getByRole('button', { name: '思维导图', exact: true }).click()
    await page.locator('svg.map-canvas').waitFor()
    await page.locator('.learning-panel').screenshot({ path: path.join(output, 'mindmap.png') })
    await page.getByRole('button', { name: '摘要', exact: true }).click()
    await page.reload(); await page.locator('.summary-overview h3').waitFor()
    assert.equal(await page.locator('.summary-chapters > li').count(), expected.chapters)
    const markdown = await page.request.get(base + '/api/v1/analyses/' + recordId + '/export?format=markdown')
    assert.equal(markdown.status(), 200)
    assert.match(await markdown.text(), /学习路径/)
    await page.setViewportSize({ width: 375, height: 812 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
    await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true })
    assert.deepEqual((await api('')).usage, before.usage)
    assert.equal(report.generationRequests, 0)
    assert.deepEqual(report.pageErrors, [])
    report.ok = true
    report.chapters = expected.chapters
    report.summaryId = result.summary.id
    report.runtimeVersion = config.summary_stream_version
    report.usageUnchanged = true
  } catch (error) {
    report.error = error.stack
    process.exitCode = 1
  } finally {
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report))
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
