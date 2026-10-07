// Run against backend/tests/learning_preview.py. All platform/model data is
// simulated; downloads, Vue rendering, fullscreen and browser files are real.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')

const base = process.env.LEARNING_TEST_URL || 'http://127.0.0.1:8180'
const artifacts = path.resolve(__dirname, '../../.local/learning-export-test')
const checks = [], errors = [], images = []
let currentCheck = ''

async function check(name, action) { currentCheck = name; await action(); checks.push(name); console.log('PASS ' + name) }
async function waitRecord(request, id, field, expected) {
  for (let i = 0; i < 80; i++) {
    const response = await request.get(base + '/api/v1/analyses/' + id)
    const record = await response.json()
    if (record[field] === expected) return record
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Record did not reach ' + field + '=' + expected)
}
async function saveDownload(page, button, output) {
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: button, exact: true }).click()])
  await download.saveAs(path.join(artifacts, output))
  return { filename: download.suggestedFilename(), data: await fs.readFile(path.join(artifacts, output)) }
}
async function mapView(page) {
  return page.locator('.map-canvas > g').evaluate(element => {
    const matrix = element.transform.baseVal.consolidate().matrix
    return { x: matrix.e, y: matrix.f, zoom: matrix.a }
  })
}
async function rendered(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}
function close(actual, expected) { assert.ok(Math.abs(actual - expected) < 0.01, `${actual} != ${expected}`) }
async function wheelAtMap(page, dx, dy, modifier) {
  const bounds = await page.locator('.map-canvas').boundingBox()
  const before = await mapView(page)
  const x = Math.round(bounds.x + bounds.width * 0.4), y = Math.round(bounds.y + bounds.height * 0.4)
  await page.mouse.move(x, y)
  if (modifier) await page.keyboard.down(modifier)
  try { await page.mouse.wheel(dx, dy) } finally { if (modifier) await page.keyboard.up(modifier) }
  await page.waitForFunction(before => {
    const matrix = document.querySelector('.map-canvas > g').transform.baseVal.consolidate().matrix
    return matrix.e !== before.x || matrix.f !== before.y || matrix.a !== before.zoom
  }, before)
  await rendered(page)
  return { before, after: await mapView(page), anchor: { x: x - bounds.x, y: y - bounds.y } }
}
function flatten(tree) { return [tree, ...tree.children.flatMap(flatten)] }
function fixture(chapters, points, long = false) {
  return { id: 'root', text: '学习效率 & <完整导图> "引号" 😀', cue_ids: [], children: Array.from({ length: chapters }, (_, i) => ({
    id: 'chapter-' + i, text: '第 ' + (i + 1) + ' 章：理解与复习', cue_ids: ['c000001'],
    children: Array.from({ length: points }, (_, j) => ({ id: 'point-' + i + '-' + j,
      text: long ? '中文知识点与 English 公式 <a+b> & 提示 😀。'.repeat(4) + '末尾-' + i + '-' + j : '知识要点-' + i + '-' + j,
      cue_ids: ['c000150'], children: [] }))
  })) }
}
async function verifySvg(page, data, tree) {
  const result = await page.evaluate(svg => {
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
    const root = doc.documentElement
    const invalid = !!doc.querySelector('parsererror,script,foreignObject,image')
    const container = document.createElement('div')
    container.style.cssText = 'position:fixed;left:-100000px;top:0;visibility:hidden'
    container.append(document.importNode(root, true)); document.body.append(container)
    const groups = [...container.querySelectorAll('g[data-node-id]')]
    const result = { invalid, width: Number(root.getAttribute('width')), height: Number(root.getAttribute('height')),
      nodes: groups.map(g => ({ id: g.getAttribute('data-node-id'), depth: Number(g.getAttribute('data-node-depth')), title: g.querySelector('title').textContent,
        visible: [...g.querySelectorAll('tspan')].map(t => t.textContent).join(''),
        label: (() => { const box = g.querySelector('text').getBBox(); return { x: box.x, y: box.y, width: box.width, height: box.height } })(),
        x: Number(g.querySelector('rect').getAttribute('x')), y: Number(g.querySelector('rect').getAttribute('y')),
        width: Number(g.querySelector('rect').getAttribute('width')), height: Number(g.querySelector('rect').getAttribute('height')) })) }
    container.remove()
    return result
  }, data.toString('utf8'))
  assert.equal(result.invalid, false)
  const source = flatten(tree)
  assert.equal(result.nodes.length, source.length)
  for (const node of result.nodes) {
    const original = source.find(item => item.id === node.id)
    assert.equal(node.title, original.text)
    assert.equal(node.visible, original.text.replace(/\r\n?/g, '\n').replace(/\n/g, ''))
    assert.ok(node.x >= 0 && node.y >= 0 && node.x + node.width <= result.width && node.y + node.height <= result.height)
    assert.ok(node.label.x >= node.x && node.label.y >= node.y && node.label.x + node.label.width <= node.x + node.width + 1 && node.label.y + node.label.height <= node.y + node.height + 1, 'Node text outside its card: ' + node.id)
  }
  for (const column of [...new Set(result.nodes.map(node => node.x))]) {
    const nodes = result.nodes.filter(node => node.x === column).sort((a, b) => a.y - b.y)
    for (let i = 1; i < nodes.length; i++) assert.ok(nodes[i].y >= nodes[i - 1].y + nodes[i - 1].height)
  }
  for (let i = 0; i < result.nodes.length; i++) for (let j = i + 1; j < result.nodes.length; j++) {
    const a = result.nodes[i], b = result.nodes[j]
    assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y, 'Cards overlap: ' + a.id + ', ' + b.id)
  }
  for (const parent of source) for (const child of parent.children) {
    const from = result.nodes.find(node => node.id === parent.id), to = result.nodes.find(node => node.id === child.id)
    assert.ok(to.x > from.x + from.width, 'Branch must open to the right: ' + child.id)
  }
  return result
}

;(async () => {
  await fs.mkdir(artifacts, { recursive: true })
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true, reducedMotion: 'reduce' })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  let recordId, englishRecordId, sourceSummary, selectedTree, svgDimensions
  try {
    await check('无摘要、页面未配置模型时仍能独立下载完整字幕', async () => {
      const videoId = 'export' + Date.now().toString(36).slice(-5)
      const response = await context.request.post(base + '/api/v1/analyses', { data: { url: 'https://www.youtube.com/watch?v=' + videoId } })
      assert.equal(response.status(), 202)
      recordId = (await response.json()).id
      await waitRecord(context.request, recordId, 'subtitle_status', 'ready')
      await page.route('**/api/v1/ai/config', route => route.fulfill({ json: { configured: false, model: 'deepseek-flash', max_duration: 7200 } }))
      await page.goto(base + '/#learn/' + recordId)
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByRole('button', { name: '下载字幕', exact: true }).waitFor()
      const result = await saveDownload(page, '下载字幕', 'all-subtitles.srt')
      assert.match(result.filename, /-zh-Hans\.srt$/)
      const text = result.data.toString('utf8')
      assert.equal(text.split(/\n\n/).filter(Boolean).length, 150)
      assert.match(text, /第 1 段/); assert.match(text, /00:49:40,000/)
      const summary = await (await context.request.get(base + '/api/v1/analyses/' + recordId + '/summary')).json()
      assert.equal(summary.summary, null); assert.equal(summary.usage.calls, 0)
    })
    await check('搜索与第二页不截断 TXT 下载，语言版本文件名正确', async () => {
      await page.getByLabel('搜索字幕').fill('主动回忆')
      await page.getByRole('button', { name: '搜索', exact: true }).click()
      await page.getByText('1–1 / 1 段', { exact: true }).waitFor()
      await page.getByLabel('字幕下载格式').selectOption('txt')
      const result = await saveDownload(page, '下载字幕', 'all-subtitles.txt')
      assert.equal(result.data.toString('utf8').split(/\n\n/).filter(Boolean).length, 150)
      assert.match(result.data.toString('utf8'), /\[00:49:40\.000 --> 00:49:48\.000\]/)
      await page.getByRole('button', { name: '清除', exact: true }).click()
      await page.getByRole('button', { name: '下一页', exact: true }).click()
      await page.getByText('101–150 / 150 段', { exact: true }).waitFor()
      const second = await saveDownload(page, '下载字幕', 'second-page-full.txt')
      assert.deepEqual(second.data, result.data)
      await page.getByLabel('切换字幕语言').selectOption('en')
      await page.locator('p.learning-muted').filter({ hasText: /^en · 人工字幕$/ }).waitFor()
      englishRecordId = page.url().split('#learn/')[1]
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      const english = await saveDownload(page, '下载字幕', 'en-subtitles.txt')
      assert.match(english.filename, /-en\.txt$/)
      await page.goto(base + '/#learn/' + recordId)
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
    })
    await check('字幕下载失败保留页面并允许重试', async () => {
      const endpoint = '**/api/v1/analyses/' + recordId + '/export?*'
      await page.route(endpoint, route => route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND', message: '【模拟验收】记录已删除，请重新获取字幕。' } } }))
      await page.getByRole('button', { name: '下载字幕', exact: true }).click()
      await page.getByText('【模拟验收】记录已删除，请重新获取字幕。', { exact: true }).waitFor()
      assert.match(page.url(), /#learn\//)
      assert.equal(await page.getByRole('button', { name: '下载字幕', exact: true }).isEnabled(), true)
      await page.unroute(endpoint)
    })
    await check('切换学习记录取消旧字幕下载，避免保存错误语言', async () => {
      const endpoint = '**/api/v1/analyses/' + recordId + '/export?*'
      await page.route(endpoint, async route => {
        await new Promise(resolve => setTimeout(resolve, 700))
        await route.fulfill({ status: 200, body: 'STALE-SUBTITLES', headers: { 'Content-Disposition': 'attachment; filename="stale.txt"' } }).catch(() => {})
      })
      let downloads = 0
      const count = () => downloads++
      page.on('download', count)
      await page.getByRole('button', { name: '下载字幕', exact: true }).click()
      await page.evaluate(id => { location.hash = '#learn/' + id }, englishRecordId)
      await page.locator('p.learning-muted').filter({ hasText: /^en · 人工字幕$/ }).waitFor()
      await new Promise(resolve => setTimeout(resolve, 900))
      assert.equal(downloads, 0)
      page.off('download', count)
      await page.unroute(endpoint)
      await page.goto(base + '/#learn/' + recordId)
    })
    await check('准备模拟导图，导出使用完整数据而非可见节点', async () => {
      await page.unroute('**/api/v1/ai/config')
      await context.request.post(base + '/api/v1/analyses/' + recordId + '/summary', { data: {} })
      await waitRecord(context.request, recordId, 'summary_status', 'ready')
      sourceSummary = await (await context.request.get(base + '/api/v1/analyses/' + recordId + '/summary')).json()
      selectedTree = fixture(3, 3, true)
      selectedTree.children[0].children[0].text = '短要点'
      selectedTree.children[2].children[2].text += '\n<脚本> & 完整末尾不能省略'
      await page.route('**/api/v1/analyses/' + recordId + '/summary', route => route.request().method() === 'GET'
        ? route.fulfill({ json: { ...sourceSummary, summary: { ...sourceSummary.summary, mindmap: selectedTree } } }) : route.continue())
      await page.goto(base + '/#learn/' + recordId)
      await page.reload()
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.locator('g.map-node').first().waitFor()
      assert.ok(await page.locator('g.map-node').count() < flatten(selectedTree).length)
      await page.getByRole('button', { name: '放大导图', exact: true }).click()
      const result = await saveDownload(page, '下载 SVG', 'complete-mindmap.svg')
      svgDimensions = await verifySvg(page, result.data, selectedTree)
      assert.match(result.filename, /-思维导图\.svg$/)
    })
    await check('向右单侧展开，节点宽高随内容调整，卡片和文字无重叠裁切', async () => {
      const short = svgDimensions.nodes.find(node => node.id === 'point-0-0')
      const long = svgDimensions.nodes.find(node => node.id === 'point-0-1')
      assert.ok(long.width > short.width && long.height > short.height)
      const dimensions = await page.locator('g.map-node[data-map-depth="2"]').evaluateAll(elements => elements.map(element => ({
        id: element.getAttribute('data-map-node'), width: Number(element.querySelector('rect').getAttribute('width')),
        height: Number(element.querySelector('rect').getAttribute('height')), lines: element.querySelectorAll('tspan').length,
        label: (() => { const box = element.querySelector('text').getBBox(); return { x: box.x, y: box.y, width: box.width, height: box.height } })(),
      })))
      const previewShort = dimensions.find(node => node.id === 'point-0-0'), previewLong = dimensions.find(node => node.id === 'point-0-1')
      assert.ok(previewLong.width > previewShort.width && previewLong.height > previewShort.height)
      assert.ok(previewLong.lines <= 4)
      for (const node of dimensions) assert.ok(node.label.x >= 0 && node.label.y >= 0 && node.label.x + node.label.width <= node.width + 1 && node.label.y + node.label.height <= node.height + 1)
    })
    await check('高清 PNG 尺寸与完整 SVG 对应，中文图片可解码', async () => {
      const result = await saveDownload(page, '下载高清 PNG', 'complete-mindmap.png')
      assert.deepEqual([...result.data.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10])
      assert.equal(result.data.readUInt32BE(16), svgDimensions.width * 3)
      assert.equal(result.data.readUInt32BE(20), svgDimensions.height * 3)
      const decoded = await page.evaluate(async data => {
        const img = new Image(); img.src = 'data:image/png;base64,' + data
        await img.decode()
        return { width: img.naturalWidth, height: img.naturalHeight }
      }, result.data.toString('base64'))
      images.push({ name: 'complete-mindmap.png', ...decoded, nodes: flatten(selectedTree).length, scale: 3 })
      await page.getByText(/已生成完整高清 PNG/).waitFor()
      const after = await (await context.request.get(base + '/api/v1/analyses/' + recordId + '/summary')).json()
      assert.deepEqual(after.usage, sourceSummary.usage)
    })
    await check('桌面全屏进入、适配、焦点与退出', async () => {
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      const panel = page.getByRole('dialog', { name: '视频思维导图全屏阅读', exact: true })
      await panel.waitFor()
      await page.waitForFunction(() => document.fullscreenElement?.classList.contains('map-stage-fullscreen'))
      const bounds = await panel.locator('.map-canvas').boundingBox()
      assert.ok(bounds.width > 1100 && bounds.height > 550)
      await panel.getByRole('button', { name: '适配视图', exact: true }).click()
      await page.keyboard.press('Tab')
      assert.equal(await page.evaluate(() => !!document.activeElement.closest('dialog')), true)
      await page.screenshot({ path: path.join(artifacts, 'desktop-fullscreen.png') })
      await panel.getByRole('button', { name: '退出全屏', exact: true }).click()
      await page.getByRole('button', { name: '全屏阅读', exact: true }).waitFor()
      assert.match(await page.evaluate(() => document.activeElement.textContent), /全屏阅读/)
      assert.equal(await page.locator('dialog:modal').count(), 0)
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.waitForFunction(() => document.fullscreenElement?.classList.contains('map-stage-fullscreen'))
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: '全屏阅读', exact: true }).waitFor()
      await page.waitForFunction(() => document.fullscreenElement === null)
    })
    await check('Escape 退出与浏览器全屏拒绝时的页面回退', async () => {
      await page.evaluate(() => {
        window.__originalFullscreen = Element.prototype.requestFullscreen
        Element.prototype.requestFullscreen = () => Promise.reject(new DOMException('Simulated fullscreen rejection', 'NotAllowedError'))
      })
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.getByRole('dialog', { name: '视频思维导图全屏阅读', exact: true }).waitFor()
      assert.equal(await page.evaluate(() => document.fullscreenElement), null)
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: '全屏阅读', exact: true }).waitFor()
      assert.equal(await page.locator('dialog:modal').count(), 0)
      await page.evaluate(() => { Element.prototype.requestFullscreen = window.__originalFullscreen })
    })
    await check('全屏放大后首次展开分支、查看长节点不重置缩放和位置', async () => {
      await page.reload()
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.waitForFunction(() => document.fullscreenElement?.classList.contains('map-stage-fullscreen'))
      await page.getByRole('button', { name: '放大导图', exact: true }).click()
      await page.getByRole('button', { name: '放大导图', exact: true }).click()
      const transform = page.locator('.map-canvas > g')
      const before = await transform.getAttribute('transform')
      const heightBefore = (await page.locator('.map-canvas').boundingBox()).height
      const branch = page.locator('g.map-node').filter({ has: page.locator('title').filter({ hasText: /^第 2 章：/ }) })
      await branch.click()
      await page.locator('.map-selection').waitFor()
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await branch.getAttribute('aria-expanded'), 'true')
      assert.ok((await page.locator('.map-canvas').boundingBox()).height < heightBefore)
      assert.equal(await transform.getAttribute('transform'), before)
      const point = page.locator('g.map-node').filter({ has: page.locator('title').filter({ hasText: /末尾-1-0$/ }) })
      await point.press('Enter')
      await page.locator('.map-selection').filter({ hasText: '末尾-1-0' }).waitFor()
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await transform.getAttribute('transform'), before)
      await branch.press('Enter')
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await branch.getAttribute('aria-expanded'), 'false')
      assert.equal(await transform.getAttribute('transform'), before)
      await page.getByRole('button', { name: '适配视图', exact: true }).click()
      assert.notEqual(await transform.getAttribute('transform'), before)
      await page.getByRole('button', { name: '退出全屏', exact: true }).click()
    })
    await check('普通与全屏导图支持滚轮上下、Shift 横向和触控板移动', async () => {
      for (const fullscreen of [false, true]) {
        if (fullscreen) {
          await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
          await page.waitForFunction(() => document.fullscreenElement?.classList.contains('map-stage-fullscreen'))
        }
        await page.locator('.map-canvas').scrollIntoViewIfNeeded()
        const scrollBefore = await page.locator('.workspace-learning').evaluate(element => element.scrollTop)
        const vertical = await wheelAtMap(page, 0, 100)
        close(vertical.after.y, vertical.before.y - 100)
        close(vertical.after.x, vertical.before.x)
        close(vertical.after.zoom, vertical.before.zoom)
        const horizontal = await wheelAtMap(page, 0, 80, 'Shift')
        close(horizontal.after.x, horizontal.before.x - 80)
        close(horizontal.after.y, horizontal.before.y)
        close(horizontal.after.zoom, horizontal.before.zoom)
        const trackpad = await wheelAtMap(page, 45, -60)
        close(trackpad.after.x, trackpad.before.x - 45)
        close(trackpad.after.y, trackpad.before.y + 60)
        close(trackpad.after.zoom, trackpad.before.zoom)
        assert.equal(await page.locator('.workspace-learning').evaluate(element => element.scrollTop), scrollBefore)
        if (fullscreen) await page.getByRole('button', { name: '退出全屏', exact: true }).click()
      }
      const before = await mapView(page)
      await page.setViewportSize({ width: 1100, height: 850 })
      await rendered(page)
      assert.deepEqual(await mapView(page), before)
      await page.setViewportSize({ width: 1280, height: 900 })
      await rendered(page)
      assert.deepEqual(await mapView(page), before)
    })
    await check('Ctrl 滚轮以鼠标位置缩放并保留边界，行和页滚轮单位正确', async () => {
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.waitForFunction(() => document.fullscreenElement?.classList.contains('map-stage-fullscreen'))
      for (const delta of [-100, 100]) {
        const result = await wheelAtMap(page, 0, delta, 'Control')
        assert.ok(delta < 0 ? result.after.zoom > result.before.zoom : result.after.zoom < result.before.zoom)
        close((result.anchor.x - result.after.x) / result.after.zoom, (result.anchor.x - result.before.x) / result.before.zoom)
        close((result.anchor.y - result.after.y) / result.after.zoom, (result.anchor.y - result.before.y) / result.before.zoom)
      }
      const canvas = page.locator('.map-canvas')
      const before = await mapView(page)
      assert.equal(await canvas.evaluate(element => !element.dispatchEvent(new WheelEvent('wheel', { deltaY: 3, deltaMode: 1, bubbles: true, cancelable: true }))), true)
      await rendered(page)
      const lines = await mapView(page)
      close(lines.y, before.y - 48)
      close(lines.x, before.x); close(lines.zoom, before.zoom)
      const bounds = await canvas.boundingBox()
      await canvas.evaluate(element => element.dispatchEvent(new WheelEvent('wheel', { deltaY: 1, deltaMode: 2, shiftKey: true, bubbles: true, cancelable: true })))
      await rendered(page)
      const pages = await mapView(page)
      close(pages.x, lines.x - bounds.width); close(pages.y, lines.y)
      await wheelAtMap(page, 0, -10000, 'Control')
      close((await mapView(page)).zoom, 2.5)
      await wheelAtMap(page, 0, 10000, 'Control')
      close((await mapView(page)).zoom, 0.12)
      await page.getByRole('button', { name: '适配视图', exact: true }).click()
      await page.screenshot({ path: path.join(artifacts, 'wheel-controls-fullscreen.png') })
      await page.getByRole('button', { name: '退出全屏', exact: true }).click()
      await canvas.scrollIntoViewIfNeeded()
      const view = await mapView(page)
      await page.locator('.workspace-learning').evaluate(element => { element.scrollTop = 0 })
      await page.getByRole('button', { name: '摘要', exact: true }).hover()
      await page.mouse.wheel(0, 100)
      await page.waitForFunction(() => document.querySelector('.workspace-learning').scrollTop > 0)
      assert.deepEqual(await mapView(page), view)
    })
    await check('后台轮询相同摘要版本不会退出全屏或重置折叠', async () => {
      const endpoint = '**/api/v1/analyses/' + recordId
      let polling = true
      await page.route(endpoint, async route => {
        const response = await route.fetch()
        const record = await response.json()
        await route.fulfill({ json: { ...record, summary_status: polling ? 'processing' : record.summary_status } })
      })
      await page.reload()
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      const node = page.locator('g.map-node').filter({ has: page.locator('title').filter({ hasText: /^第 2 章：/ }) })
      await node.click()
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.waitForResponse(response => response.url().endsWith('/analyses/' + recordId + '/summary'))
      assert.equal(await page.locator('dialog:modal').count(), 1)
      assert.equal(await node.getAttribute('aria-expanded'), 'true')
      polling = false
      await page.getByRole('button', { name: '退出全屏', exact: true }).click()
      await page.unroute(endpoint)
      await page.reload()
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
    })
    await check('全屏字幕定位清理弹窗，列表阅读仍可用', async () => {
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      const node = page.locator('g.map-node').filter({ has: page.locator('title').filter({ hasText: /^第 1 章：/ }) })
      await node.click()
      await page.getByRole('button', { name: '查看对应字幕', exact: true }).click()
      await page.locator('#cue-c000001').waitFor()
      assert.equal(await page.locator('dialog:modal').count(), 0)
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.getByRole('button', { name: '树形列表', exact: true }).click()
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.locator('.map-fullscreen-dialog .map-list').waitFor()
      await page.getByRole('button', { name: '退出全屏', exact: true }).click()
      await page.getByRole('button', { name: '查看导图', exact: true }).click()
    })
    await check('375px 窄屏全屏操作与图片下载，无页面溢出', async () => {
      await page.setViewportSize({ width: 375, height: 812 })
      await page.locator('.map-mobile-list').waitFor()
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      const panel = page.getByRole('dialog', { name: '视频思维导图全屏阅读', exact: true })
      await panel.locator('.map-canvas').waitFor()
      assert.ok((await panel.locator('.map-canvas').boundingBox()).height > 300)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      await saveDownload(page, '下载 SVG', 'mobile-complete.svg')
      await page.screenshot({ path: path.join(artifacts, 'mobile-fullscreen.png') })
      await page.getByRole('button', { name: '退出全屏', exact: true }).click()
      await page.setViewportSize({ width: 1280, height: 900 })
    })
    await check('较大导图保持完整，以 2 倍高清 PNG 保存', async () => {
      selectedTree = fixture(9, 9)
      await page.reload(); await page.getByRole('button', { name: '思维导图', exact: true }).click()
      const svg = await saveDownload(page, '下载 SVG', 'medium-mindmap.svg')
      const layout = await verifySvg(page, svg.data, selectedTree)
      const png = await saveDownload(page, '下载高清 PNG', 'medium-mindmap.png')
      assert.equal(png.data.readUInt32BE(16), layout.width * 2)
      assert.equal(png.data.readUInt32BE(20), layout.height * 2)
      images.push({ name: 'medium-mindmap.png', width: layout.width * 2, height: layout.height * 2, nodes: flatten(selectedTree).length, scale: 2 })
    })
    await check('超大导图 PNG 明确提示，SVG 包含超过 100 个完整节点', async () => {
      selectedTree = fixture(12, 12, true)
      await page.reload(); await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.getByRole('button', { name: '下载高清 PNG', exact: true }).click()
      await page.getByRole('alert').filter({ hasText: '超出高清 PNG' }).waitFor()
      assert.equal(await page.getByRole('button', { name: '下载 SVG', exact: true }).isEnabled(), true)
      const svg = await saveDownload(page, '下载 SVG', 'huge-complete-mindmap.svg')
      const layout = await verifySvg(page, svg.data, selectedTree)
      assert.equal(layout.nodes.length, 157)
    })
    await check('单主题、单章节及 1500 字长节点导出完整，不裁切文字', async () => {
      selectedTree = { id: 'root', text: '独立主题 😀', cue_ids: [], children: [] }
      await page.reload(); await page.getByRole('button', { name: '思维导图', exact: true }).click()
      const single = await saveDownload(page, '下载 SVG', 'single-node.svg')
      assert.equal((await verifySvg(page, single.data, selectedTree)).nodes.length, 1)
      selectedTree = fixture(1, 1)
      selectedTree.children[0].text = '长章节标题'.repeat(12)
      selectedTree.children[0].children[0].text = '长知识点'.repeat(374) + '完整末尾'
      await page.reload(); await page.getByRole('button', { name: '思维导图', exact: true }).click()
      const long = await saveDownload(page, '下载 SVG', 'single-chapter-long.svg')
      const drawing = await verifySvg(page, long.data, selectedTree)
      assert.equal(drawing.nodes.length, 3)
      assert.equal(drawing.nodes.find(node => node.id === 'point-0-0').visible.length, 1500)
    })
    await check('PNG 生成失败可恢复，不残留忙碌状态', async () => {
      selectedTree = fixture(2, 2)
      await page.reload(); await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.evaluate(() => {
        window.__originalToBlob = HTMLCanvasElement.prototype.toBlob
        HTMLCanvasElement.prototype.toBlob = function (callback) { setTimeout(() => callback(null), 10) }
      })
      await page.getByRole('button', { name: '下载高清 PNG', exact: true }).click()
      await page.getByRole('alert').filter({ hasText: 'PNG 保存失败' }).waitFor()
      await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = window.__originalToBlob })
      await saveDownload(page, '下载高清 PNG', 'recovered-mindmap.png')
    })
    await check('离开导图中止迟到的图片下载，关闭学习工作区清理全屏', async () => {
      await page.evaluate(() => {
        window.__originalToBlob = HTMLCanvasElement.prototype.toBlob
        HTMLCanvasElement.prototype.toBlob = function (callback, ...args) {
          window.__originalToBlob.call(this, blob => setTimeout(() => callback(blob), 1000), ...args)
        }
      })
      let lateDownloads = 0
      const countDownload = () => lateDownloads++
      page.on('download', countDownload)
      await page.getByRole('button', { name: '下载高清 PNG', exact: true }).click()
      await page.getByRole('button', { name: '摘要', exact: true }).click()
      await new Promise(resolve => setTimeout(resolve, 1500))
      assert.equal(lateDownloads, 0)
      page.off('download', countDownload)
      await page.evaluate(() => { HTMLCanvasElement.prototype.toBlob = window.__originalToBlob })
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.getByRole('button', { name: '全屏阅读', exact: true }).click()
      await page.evaluate(() => { location.hash = '#top' })
      await page.getByRole('button', { name: '解析视频', exact: true }).waitFor()
      await page.waitForFunction(() => document.querySelectorAll('dialog:modal').length === 0)
      assert.equal(await page.locator('dialog:modal').count(), 0)
      assert.equal(await page.evaluate(() => document.fullscreenElement), null)
    })
    assert.deepEqual(errors, [])
  } catch (error) {
    await page.screenshot({ path: path.join(artifacts, 'failure.png'), fullPage: true }).catch(() => {})
    console.error('FAILED ' + currentCheck + ': ' + error.stack)
    process.exitCode = 1
  } finally {
    await fs.writeFile(path.join(artifacts, 'report.json'), JSON.stringify({ checks, failed: process.exitCode ? currentCheck : null, errors, images, simulated: true }, null, 2))
    await browser.close()
  }
})()
