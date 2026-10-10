// UI acceptance of the real outputs created by run_bilibili_e2e.py.
// Only the exact video's free metadata POST is allowed; model and other writes
// remain blocked. Paid calls happen only in the Python flow.
const { chromium } = require('playwright')
const fs = require('node:fs/promises')
const path = require('node:path')
const assert = require('node:assert/strict')

const [recordId, output] = process.argv.slice(2)
const base = 'http://127.0.0.1:8000'
const report = { status: 'RUNNING', checks: {}, page_errors: 0, blocked_api_writes: 0, metadata_parse_requests: 0 }
const flatten = node => [node, ...(node.children || []).flatMap(flatten)]

;(async () => {
  assert.ok(recordId && output)
  const expectedUrl = JSON.parse(await fs.readFile(path.join(output, 'report.json'), 'utf8')).url
  assert.equal(new URL(expectedUrl).hostname, 'www.bilibili.com')
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true, reducedMotion: 'reduce' })
  await context.route('**/api/v1/**', route => {
    const request = route.request()
    const target = new URL(request.url())
    if (target.origin === base && request.method() === 'GET') return route.continue()
    if (target.origin === base && target.pathname === '/api/v1/parse' && !target.search && request.method() === 'POST') {
      try {
        const body = request.postDataJSON()
        if (Object.keys(body).length === 1 && body.url === expectedUrl) {
          report.metadata_parse_requests++
          return route.continue()
        }
      } catch { /* Do not persist request bodies or raw errors. */ }
    }
    report.blocked_api_writes++
    return route.abort()
  })
  const page = await context.newPage()
  page.setDefaultTimeout(20000)
  page.on('pageerror', () => report.page_errors++) // Never persist raw browser messages.
  const waitMetadata = () => page.waitForResponse(response => response.url() === base + '/api/v1/parse' && response.request().method() === 'POST')
  const checkMetadata = async pending => {
    const response = await pending
    assert.equal(response.status(), 200)
    const data = await response.json()
    assert.ok(data.formats?.length > 0)
    await page.locator('.compact-download button').first().waitFor()
    report.checks.download_metadata_restored = true
    // Keep counts/status only; metadata can contain private media addresses.
    report.download_metadata = { http_status: response.status(), formats: data.formats.length }
  }
  const download = async (name, filename) => {
    const pending = page.waitForEvent('download')
    await page.getByRole('button', { name, exact: true }).click()
    const file = await pending
    await file.saveAs(path.join(output, filename))
    return fs.readFile(path.join(output, filename))
  }
  try {
    const summary = JSON.parse(await fs.readFile(path.join(output, 'summary.json'), 'utf8'))
    const transcript = JSON.parse(await fs.readFile(path.join(output, 'transcript.json'), 'utf8')).cues
    const messages = JSON.parse(await fs.readFile(path.join(output, 'messages.json'), 'utf8')).items
    report.last_stage = 'initial_load'
    const initialMetadata = waitMetadata()
    await page.goto(base + '/#learn/' + recordId)
    await checkMetadata(initialMetadata)
    await page.locator('.summary-overview h3').waitFor()
    assert.equal(await page.locator('.summary-chapters > li').count(), summary.summary.content.chapters.length)
    report.checks.summary_rendered = true
    await page.screenshot({ path: path.join(output, 'summary.png'), fullPage: true })
    await page.locator('.learning-reference').first().click()
    await page.locator('.cue-highlighted').waitFor()
    report.checks.reference_locates_cue = true
    report.last_stage = 'mindmap_exports'
    await page.getByRole('button', { name: '思维导图', exact: true }).click()
    await page.locator('svg.map-canvas').waitFor()
    const closed = page.locator('g.map-node[aria-expanded="false"]')
    if (await closed.count()) await closed.first().click()
    await page.getByRole('button', { name: '放大导图', exact: true }).click()
    await page.getByRole('button', { name: '适配视图', exact: true }).click()
    const svg = await download('下载 SVG', 'mindmap.svg')
    const dimensions = await page.evaluate(source => {
      const doc = new DOMParser().parseFromString(source, 'image/svg+xml')
      return { width: Number(doc.documentElement.getAttribute('width')), height: Number(doc.documentElement.getAttribute('height')),
        ids: [...doc.querySelectorAll('g[data-node-id]')].map(node => node.getAttribute('data-node-id')) }
    }, svg.toString('utf8'))
    assert.deepEqual(dimensions.ids.sort(), flatten(summary.summary.mindmap).map(node => node.id).sort())
    report.checks.mindmap_svg_complete = true
    const png = await download('下载高清 PNG', 'mindmap.png')
    assert.equal(png.subarray(1, 4).toString(), 'PNG')
    assert.ok(png.readUInt32BE(16) >= dimensions.width * 2 && png.readUInt32BE(20) >= dimensions.height * 2)
    report.checks.mindmap_png = true
    await page.screenshot({ path: path.join(output, 'mindmap-view.png'), fullPage: true })
    report.last_stage = 'subtitle_exports'
    await page.getByRole('button', { name: '字幕原文', exact: true }).click()
    await page.locator('.transcript-cue').first().waitFor()
    for (const format of ['srt', 'txt']) {
      await page.getByLabel('字幕下载格式').selectOption(format)
      const text = (await download('下载字幕', 'browser-subtitles.' + format)).toString('utf8')
      const times = format === 'srt' ? /^\d+\r?\n\d{2}:\d{2}:\d{2},\d{3} --> /gm : /^\[\d{2}:\d{2}:\d{2}\.\d{3} --> /gm
      assert.equal((text.match(times) || []).length, transcript.length)
      for (const cue of transcript) assert.ok(text.includes(cue.text))
      report.checks[format + '_complete'] = true
    }
    report.last_stage = 'chat_restore'
    await page.getByRole('button', { name: '视频问答', exact: true }).click()
    assert.equal(await page.locator('.chat-turn').count(), messages.length)
    assert.ok(messages.every(message => message.status === 'ready' && message.answer.references.length))
    await page.screenshot({ path: path.join(output, 'chat.png'), fullPage: true })
    const restoredMetadata = waitMetadata()
    await page.reload()
    await checkMetadata(restoredMetadata)
    await page.locator('.summary-overview h3').waitFor()
    await page.getByRole('button', { name: '视频问答', exact: true }).click()
    assert.equal(await page.locator('.chat-turn').count(), messages.length)
    report.checks.saved_chat_restored = true
    assert.equal(report.blocked_api_writes, 0)
    assert.equal(report.page_errors, 0)
    report.last_stage = 'complete'
    report.status = 'PASSED'
  } catch (error) {
    report.status = 'FAILED'
    report.error_type = error.name === 'TimeoutError' ? 'TIMEOUT' : 'ASSERTION_OR_BROWSER_ERROR'
    await page.screenshot({ path: path.join(output, 'browser-failure.png'), fullPage: true }).catch(() => {})
    process.exitCode = 1
  } finally {
    await fs.writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2))
    await browser.close()
  }
})().catch(async () => {
  if (output) await fs.writeFile(path.join(output, 'browser-report.json'), JSON.stringify({ status: 'FAILED', error_type: 'BROWSER_START_FAILED' }))
  process.exitCode = 1
})
