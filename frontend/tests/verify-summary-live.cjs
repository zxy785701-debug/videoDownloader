// Explicit live verification. Uses the paid model via an isolated server/db.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const [base, recordId, output] = process.argv.slice(2)
if (!base || !recordId || !output) throw new Error('Provide base URL, record ID and artifact directory explicitly.')
const report = { simulation: false, ok: false, pageErrors: [], requests: 0 }
let browser, page
;(async () => {
  await fs.mkdir(output, { recursive: true })
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
  page.on('pageerror', error => report.pageErrors.push(error.message))
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/summary')) report.requests++ })
  const api = async suffix => {
    const response = await page.request.get(base + '/api/v1/analyses/' + recordId + suffix)
    assert.ok(response.ok()); return response.json()
  }
  try {
    const before = await api('')
    assert.equal(before.url, 'https://www.bilibili.com/video/BV1qTYizcEN3/')
    assert.equal(before.subtitle_status, 'ready')
    const config = await (await page.request.get(base + '/api/v1/ai/config')).json()
    assert.equal(config.summary_stream_version, 2); assert.equal(config.configured, true)
    report.model = config.model
    await page.goto(base + '/#learn/' + recordId)
    await page.getByRole('heading', { name: '视频摘要', exact: true }).waitFor()
    await page.evaluate(() => {
      const state = window.__liveRetention = { seen: {}, dropped: [], snapshots: 0, stageIds: [], rewrites: [] }
      new MutationObserver(() => {
        if (document.querySelector('.summary-overview')) return // Formal result atomically replaces drafts.
        const nodes = [...document.querySelectorAll('.summary-draft-part')]
        for (const id of Object.keys(state.seen)) if (!nodes.some(node => node.dataset.partId === id)) state.dropped.push(id)
        for (const node of nodes) {
          const id = node.dataset.partId, text = node.querySelector('.summary-stream-text, .summary-stage-text')?.textContent || ''
          if (state.seen[id] && !text.startsWith(state.seen[id])) state.rewrites.push({ id, before: state.seen[id].length, after: text.length })
          state.seen[id] = text
          if (!state.stageIds.includes(id)) state.stageIds.push(id)
        }
        state.snapshots++
      }).observe(document.querySelector('.learning-panel'), { subtree: true, childList: true, characterData: true })
    })
    const started = Date.now()
    await page.getByRole('button', { name: before.current_summary_id ? '重新生成' : '生成总结', exact: true }).click()
    await page.locator('.summary-stream-preview').waitFor({ timeout: 60000 })
    report.firstTextSeconds = (Date.now() - started) / 1000
    let detail
    while (Date.now() - started < 16 * 60 * 1000) {
      detail = await api('')
      if (detail.summary_status === 'ready' || detail.summary_status === 'failed') break
      await new Promise(resolve => setTimeout(resolve, 3000))
    }
    report.totalSeconds = (Date.now() - started) / 1000
    report.status = detail.summary_status
    report.job = detail.jobs.find(job => job.kind === 'summary')
    report.usageDelta = Object.fromEntries(Object.keys(detail.usage).map(key => [key, detail.usage[key] - before.usage[key]]))
    report.modelCalls = (await (await page.request.get(base + '/_test/summary-live/stats')).json()).calls
    report.retention = await page.evaluate(() => window.__liveRetention)
    assert.equal(detail.summary_status, 'ready', report.job.error)
    await page.locator('.summary-overview h3').waitFor({ timeout: 15000 })
    const result = await api('/summary')
    report.summary = result.summary
    const cues = []
    for (let offset = 0; ; offset += 200) {
      const transcript = await api('/transcript?limit=200&offset=' + offset)
      cues.push(...transcript.items); if (cues.length >= transcript.total) break
    }
    const allowed = new Set(cues.map(cue => cue.id)), refs = result.summary.content.chapters.flatMap(chapter => [...chapter.references, ...chapter.points.flatMap(point => point.references)])
    report.referencesValid = refs.every(ref => allowed.has(ref.cue_id))
    report.lastReferencedSeconds = Math.max(...refs.map(ref => ref.start))
    report.chapters = result.summary.content.chapters.length
    assert.ok(report.referencesValid && report.chapters > 1)
    assert.ok(report.lastReferencedSeconds > before.duration * .85, 'Missing references from the closing part of the video.')
    assert.deepEqual(report.retention.dropped, [])
    assert.deepEqual(report.retention.rewrites, [])
    assert.deepEqual(report.pageErrors, [])
    assert.equal(report.requests, 1)
    const callCount = report.modelCalls.length
    await page.reload(); await page.locator('.summary-overview h3').waitFor()
    assert.equal((await api('/summary')).summary.id, result.summary.id)
    assert.equal((await (await page.request.get(base + '/_test/summary-live/stats')).json()).calls.length, callCount)
    await page.locator('.summary-overview').screenshot({ path: path.join(output, 'formal-summary.png') })
    await page.getByRole('button', { name: '思维导图', exact: true }).click()
    await page.locator('svg.map-canvas').waitFor()
    const markdown = await page.request.get(base + '/api/v1/analyses/' + recordId + '/export?format=markdown')
    assert.equal(markdown.status(), 200)
    await fs.writeFile(path.join(output, 'summary.md'), await markdown.text())
    report.ok = true
  } catch (error) {
    report.error = error.stack
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
    process.exitCode = 1
  } finally {
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify({ ...report, summary: undefined, retention: report.retention && {
      ...report.retention, seen: undefined,
      retainedCharacters: Object.values(report.retention.seen).map(text => text.length),
    } }))
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
