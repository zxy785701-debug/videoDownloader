const { chromium } = require('playwright')
const fs = require('node:fs/promises')
const assert = require('node:assert/strict')
const path = require('node:path')
const output = path.resolve(__dirname, '../../.local/unified-saved-data')
const base = process.env.UNIFIED_SAVED_URL || 'http://127.0.0.1:8188'
;(async () => {
  const records = JSON.parse(await fs.readFile(path.join(output, 'records.json'), 'utf8'))
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true })
  const page = await context.newPage(), checks = [], errors = []
  page.on('pageerror', e => errors.push(e.message))
  let posts = 0
  page.on('request', r => { if (r.method() === 'POST' && r.url().includes('/analyses')) posts++ })
  for (let i = 0; i < 60; i++) { if (await context.request.get(base + '/api/v1/ai/config').then(r => r.ok()).catch(() => false)) break; await new Promise(r => setTimeout(r, 100)) }
  try {
    for (const [index, record] of records.entries()) {
      const before = await (await context.request.get(base + '/api/v1/analyses/' + record.id)).json()
      await page.goto(base + '/#learn/' + record.id)
      await page.locator('.summary-overview h3').waitFor()
      await page.getByRole('heading', { name: record.title, exact: true }).waitFor()
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      if (index === 0) await page.screenshot({ path: path.join(output, 'real-saved-desktop.png') })
      const pending = page.waitForEvent('download')
      await page.getByRole('link', { name: '导出 Markdown', exact: true }).click()
      const file = await pending; await file.saveAs(path.join(output, record.id + '.md'))
      assert.ok((await fs.readFile(path.join(output, record.id + '.md'), 'utf8')).length > 100)
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.locator('svg.map-canvas').waitFor()
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.locator('.transcript-cue').first().waitFor()
      const after = await (await context.request.get(base + '/api/v1/analyses/' + record.id)).json()
      assert.deepEqual(after.usage, before.usage)
      checks.push({ id: record.id, savedSummary: true, transcript: true, mindmap: true, markdown: true, unchangedUsage: true })
    }
    assert.equal(posts, 0); assert.deepEqual(errors, [])
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify({ checks, posts, errors, databaseCopyOnly: true }, null, 2))
    console.log(JSON.stringify({ passed: checks.length, posts, errors }))
  } finally { await browser.close() }
})().catch(e => { console.error(e.stack); process.exitCode = 1 })
