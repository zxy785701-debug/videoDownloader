// Read-only acceptance against a local service with a COPY of existing learning
// data. No platform extraction or model request is triggered by this script.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')

const base = process.env.LEARNING_EXISTING_TEST_URL || 'http://127.0.0.1:8182'
const directory = path.resolve(__dirname, '../../.local/learning-export-real')
function flatten(tree) { return [tree, ...tree.children.flatMap(flatten)] }
async function save(page, name, filename) {
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name, exact: true }).click()])
  await download.saveAs(path.join(directory, filename))
  return fs.readFile(path.join(directory, filename))
}

;(async () => {
  await fs.mkdir(directory, { recursive: true })
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true, reducedMotion: 'reduce' })
  await context.route('**/api/v1/**', route => route.request().method() === 'GET' ? route.continue() : route.abort())
  const page = await context.newPage()
  const errors = [], results = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    const records = (await (await context.request.get(base + '/api/v1/analyses?limit=100')).json()).items
      .filter(record => record.subtitle_status === 'ready' && record.summary_status === 'ready')
    assert.ok(records.length > 0, 'No existing summarized records found in the test copy')
    for (let index = 0; index < records.length; index++) {
      const record = records[index], prefix = record.platform + '-' + (index + 1)
      const summary = await (await context.request.get(base + '/api/v1/analyses/' + record.id + '/summary')).json()
      const nodes = flatten(summary.summary.mindmap)
      const transcript = await (await context.request.get(base + '/api/v1/analyses/' + record.id + '/transcript')).json()
      await page.goto(base + '/#learn/' + record.id)
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      const svg = await save(page, '下载 SVG', prefix + '.svg')
      const dimensions = await page.evaluate(source => {
        const doc = new DOMParser().parseFromString(source, 'image/svg+xml')
        return { width: Number(doc.documentElement.getAttribute('width')), height: Number(doc.documentElement.getAttribute('height')),
          nodes: [...doc.querySelectorAll('g[data-node-id]')].map(node => ({ id: node.getAttribute('data-node-id'),
            text: node.querySelector('title').textContent, visible: [...node.querySelectorAll('tspan')].map(line => line.textContent).join('') })) }
      }, svg.toString('utf8'))
      assert.equal(dimensions.nodes.length, nodes.length)
      for (const node of nodes) {
        const rendered = dimensions.nodes.find(item => item.id === node.id)
        assert.equal(rendered.text, node.text)
        assert.equal(rendered.visible, node.text.replace(/\r\n?/g, '\n').replace(/\n/g, ''))
      }
      const scale = [3, 2].find(scale => dimensions.width * scale <= 16384 && dimensions.height * scale <= 16384 && dimensions.width * dimensions.height * scale * scale <= 32000000)
      let png = null
      if (scale) {
        const file = await save(page, '下载高清 PNG', prefix + '.png')
        png = { width: file.readUInt32BE(16), height: file.readUInt32BE(20), scale }
        assert.equal(png.width, dimensions.width * scale); assert.equal(png.height, dimensions.height * scale)
      } else {
        await page.getByRole('button', { name: '下载高清 PNG', exact: true }).click()
        await page.getByRole('alert').filter({ hasText: '超出高清 PNG' }).waitFor()
      }
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.waitForFunction(() => document.fullscreenElement?.classList.contains('map-stage-fullscreen'))
      await page.getByRole('button', { name: '放大导图', exact: true }).click()
      await page.getByRole('button', { name: '放大导图', exact: true }).click()
      const view = await page.locator('.map-canvas > g').getAttribute('transform')
      await page.locator('g.map-node[aria-expanded="false"]').first().press('Enter')
      await page.locator('.map-selection').waitFor()
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await page.locator('.map-canvas > g').getAttribute('transform'), view)
      await page.getByRole('button', { name: '适配视图', exact: true }).click()
      await page.screenshot({ path: path.join(directory, prefix + '-fullscreen.png') })
      await page.getByRole('button', { name: '退出全屏', exact: true }).click()
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByLabel('字幕下载格式').selectOption('srt')
      const srt = await save(page, '下载字幕', prefix + '.srt')
      assert.equal((srt.toString('utf8').match(/^\d+\n\d{2}:\d{2}:\d{2},\d{3} --> /gm) || []).length, transcript.total)
      await page.getByLabel('字幕下载格式').selectOption('txt')
      const txt = await save(page, '下载字幕', prefix + '.txt')
      assert.equal((txt.toString('utf8').match(/^\[\d{2}:\d{2}:\d{2}\.\d{3} --> /gm) || []).length, transcript.total)
      for (const cue of transcript.items) { assert.ok(srt.toString('utf8').includes(cue.text)); assert.ok(txt.toString('utf8').includes(cue.text)) }
      const after = await (await context.request.get(base + '/api/v1/analyses/' + record.id + '/summary')).json()
      assert.deepEqual(after.usage, summary.usage)
      results.push({ id: record.id, platform: record.platform, duration: record.duration, language: record.language,
        cues: transcript.total, nodes: nodes.length, png, svg_dimensions: { width: dimensions.width, height: dimensions.height },
        svg_complete: true, native_fullscreen: true, first_expansion_preserves_view: true,
        srt_complete: true, txt_complete: true, new_model_calls: 0 })
      console.log(JSON.stringify(results.at(-1)))
    }
    assert.deepEqual(errors, [])
  } catch (error) {
    await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {})
    process.exitCode = 1
    console.error(error.stack)
  } finally {
    await fs.writeFile(path.join(directory, 'report.json'), JSON.stringify({ results, errors, failed: !!process.exitCode, source: 'existing real records copied locally' }, null, 2))
    await browser.close()
  }
})()
