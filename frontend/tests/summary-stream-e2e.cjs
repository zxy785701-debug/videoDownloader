// Run with tests.summary_stream_preview on port 8185; no paid model calls.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const base = process.env.SUMMARY_STREAM_TEST_URL || 'http://127.0.0.1:8185'
const artifacts = path.resolve(__dirname, '../../.local/summary-stream-browser-test')
const checks = [], errors = []
let browser, context, page, failed = null
async function check(name, action) {
  if (process.env.SUMMARY_STREAM_CHECK && !name.includes(process.env.SUMMARY_STREAM_CHECK)) return
  try { await action(); checks.push(name) }
  catch (error) { failed = { name, message: error.stack }; throw error }
}
async function api(url, options) {
  const response = await context.request.fetch(base + url, options)
  assert.ok(response.ok(), url + ': ' + response.status())
  return response.status() === 204 ? null : response.json()
}
async function eventually(condition) {
  for (let i = 0; i < 100; i++) { if (await condition()) return; await new Promise(resolve => setTimeout(resolve, 100)) }
  assert.fail('Condition did not become true')
}
async function create(suffix) {
  const result = await api('/api/v1/analyses', { method: 'POST', data: { url: 'https://youtu.be/' + suffix } })
  await eventually(async () => (await api('/api/v1/analyses/' + result.id)).subtitle_status === 'ready')
  return result.id
}
async function open(id) {
  await page.goto(base + '/#learn/' + id)
  await page.getByRole('heading', { name: '视频摘要', exact: true }).waitFor()
}
async function calls(mode) { return (await api('/_test/summary-stream/stats')).calls[mode] || 0 }
async function release(mode, attempt = 1) {
  await eventually(async () => await calls(mode) >= attempt)
  assert.equal((await api('/_test/summary-stream/release', { method: 'POST', data: { mode, attempt } })).released, true)
}
async function generate(name = '生成总结') {
  await page.getByRole('button', { name, exact: true }).click()
  await page.locator('.summary-stream-text').waitFor({ timeout: 10000 })
}
async function complete(id, title) {
  await page.locator('.summary-stream-preview').waitFor({ state: 'detached', timeout: 15000 })
  await page.locator('.summary-overview h3').getByText(title, { exact: true }).waitFor()
  const result = await api('/api/v1/analyses/' + id + '/summary')
  assert.equal(result.status, 'ready'); assert.equal(result.summary.content.headline, title)
  assert.ok(result.summary.content.chapters[0].references.length)
  assert.ok(result.summary.mindmap.children.length)
  return result.summary
}
;(async () => {
  await fs.mkdir(artifacts, { recursive: true })
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
  try {
    const id = await create('sseshort001')
    let jobId, posts = 0
    page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/summary')) posts++ })
    await check('摘要草稿在模型完成前逐步显示，不暴露 JSON 或未校验引用', async () => {
      await open(id); await generate()
      const draft = page.locator('.summary-stream-text'), first = await draft.innerText()
      await eventually(async () => (await draft.innerText()).length > first.length)
      await page.getByText(/正在生成，引用尚未校验；完整摘要/).waitFor()
      assert.doesNotMatch(await draft.innerText(), /cue_ids|chapters|c000150|[{}]/)
      assert.equal(await page.locator('.summary-overview').count(), 0)
      assert.equal(await page.locator('.learning-reference').count(), 0)
      const detail = await api('/api/v1/analyses/' + id)
      jobId = detail.jobs.find(job => job.kind === 'summary').id
      assert.equal((await api('/api/v1/analyses/' + id + '/summary')).summary, null)
      await page.screenshot({ path: path.join(artifacts, 'generating.png'), fullPage: true })
    })
    await check('刷新、切换页签、退出后返回均接回原摘要任务，不重复调用', async () => {
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByRole('button', { name: '摘要', exact: true }).click()
      await page.locator('.summary-stream-text').waitFor()
      await page.getByRole('button', { name: '换个链接', exact: true }).click()
      await open(id); await page.locator('.summary-stream-text').waitFor()
      await page.reload(); await page.locator('.summary-stream-text').waitFor()
      assert.equal((await api('/api/v1/analyses/' + id)).jobs.find(job => job.kind === 'summary').id, jobId)
      assert.equal(await calls('正常'), 1); assert.equal(posts, 1)
    })
    await check('SSE 和状态请求临时断开后自动恢复，完整摘要与导图校验后保存', async () => {
      let dropped = false, statusDropped = false
      await page.route('**/summary/*/stream', async route => {
        if (!dropped) { dropped = true; await route.abort('failed') } else await route.continue()
      })
      await page.route('**/summary', async route => {
        if (route.request().method() === 'GET' && dropped && !statusDropped) { statusDropped = true; await route.abort('failed') }
        else await route.continue()
      })
      await page.reload()
      await page.getByText(/摘要流式连接暂时中断/).waitFor()
      await page.locator('.summary-stream-text').waitFor({ timeout: 15000 })
      assert.equal(statusDropped, true); assert.equal(await calls('正常'), 1)
      await release('正常'); await complete(id, '正常：第 1 次概览 😀')
      assert.equal((await api('/api/v1/analyses/' + id)).usage.calls, 1)
      await page.unroute('**/summary/*/stream'); await page.unroute('**/summary')
      await page.screenshot({ path: path.join(artifacts, 'completed.png'), fullPage: true })
    })
    await check('完成后刷新恢复，引用定位原字幕，读取摘要不新增用量', async () => {
      await page.reload()
      await page.locator('.summary-overview h3').waitFor()
      await page.getByRole('button', { name: '49:40 原文', exact: true }).first().click()
      await page.locator('#cue-c000150').waitFor()
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      await page.locator('svg.map-canvas').waitFor()
      assert.equal(await calls('正常'), 1)
    })
    await check('记录与摘要的并行读取跨过保存时点，不会丢失正式摘要或停止在空页面', async () => {
      let stale = false
      await page.route('**/api/v1/analyses/' + id + '/summary', async route => {
        if (!stale && route.request().method() === 'GET') {
          stale = true
          const response = await route.fetch(), body = await response.json()
          await route.fulfill({ response, json: { ...body, status: 'processing', summary: null } })
        } else await route.continue()
      })
      await page.reload()
      await page.locator('.summary-overview h3').getByText('正常：第 1 次概览 😀', { exact: true }).waitFor()
      assert.equal(stale, true); assert.equal(await calls('正常'), 1); assert.equal(posts, 1)
      await page.unroute('**/api/v1/analyses/' + id + '/summary')
    })
    await check('识别未重启的旧后端并阻止付费生成，字幕阅读仍然可用', async () => {
      await page.route('**/api/v1/ai/config', async route => {
        const response = await route.fetch(), config = await response.json()
        delete config.summary_stream_version
        await route.fulfill({ response, json: config })
      })
      await page.reload()
      await page.getByText('后端仍在运行旧版摘要代码，请重启后端后再生成。', { exact: true }).waitFor()
      assert.equal(await page.getByRole('button', { name: '重新生成', exact: true }).isDisabled(), true)
      assert.equal(posts, 1); assert.equal(await calls('正常'), 1)
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByRole('heading', { name: '字幕原文', exact: true }).waitFor()
      await page.unroute('**/api/v1/ai/config')
      await page.reload()
      await page.locator('.summary-overview h3').waitFor()
    })
    await check('引用校验修复保留第一版草稿，第二版独立生成且仅保存第二版摘要', async () => {
      const repairId = await create('sserepair01')
      await open(repairId); await generate()
      await release('修复')
      await eventually(async () => await calls('修复') === 2)
      await eventually(async () => (await page.locator('.summary-stream-text').innerText().catch(() => '')).includes('第 2 次'))
      assert.doesNotMatch(await page.locator('.summary-stream-text').innerText(), /第 1 次/)
      assert.match(await page.locator('.summary-stage-text').innerText(), /第 1 次/)
      await page.getByText('上一版草稿未通过校验，正在修正；此版本不会作为正式摘要保存。', { exact: true }).waitFor()
      await page.getByText('自动修复原因：摘要结构或字幕引用无效，未保存为成功结果。', { exact: true }).waitFor()
      assert.equal(await page.locator('.learning-reference').count(), 0)
      await release('修复', 2); await complete(repairId, '修复：第 2 次概览 😀')
      assert.equal((await api('/api/v1/analyses/' + repairId)).usage.calls, 2)
    })
    await check('输出额度耗尽后保留已展示草稿，重试增加额度并完成，不会整块撤回', async () => {
      const truncatedId = await create('ssecut00001')
      await open(truncatedId); await generate()
      const previous = await page.locator('.summary-stream-text').innerText()
      await release('截断')
      await eventually(async () => await calls('截断') === 2)
      await page.locator('.summary-draft-part[data-phase="superseded"]').waitFor()
      const retained = await page.locator('.summary-stage-text').innerText()
      assert.ok(retained.startsWith(previous))
      await eventually(async () => (await page.locator('.summary-stream-text').innerText().catch(() => '')).includes('第 2 次'))
      const stats = await api('/_test/summary-stream/stats')
      assert.deepEqual(stats.budgets['截断'], [4096, 8192])
      await page.getByText('自动修复原因：模型达到本次输出长度上限，未保存为完整结果。', { exact: true }).waitFor()
      await page.screenshot({ path: path.join(artifacts, 'retained-repair.png'), fullPage: true })
      await release('截断', 2); await complete(truncatedId, '截断：第 2 次概览 😀')
      assert.equal(await calls('截断'), 2)
    })
    await check('重新生成期间保留旧摘要，模型断流不自动重试或覆盖成功版本', async () => {
      const brokenId = await create('ssebroken01')
      await open(brokenId); await generate(); await release('断流');
      const previous = await complete(brokenId, '断流：第 1 次概览 😀')
      await generate('重新生成')
      await page.getByText('下方为上次保存的摘要；生成完成后更新。', { exact: true }).waitFor()
      assert.equal(await page.locator('.summary-overview h3').innerText(), '断流：第 1 次概览 😀')
      await release('断流', 2)
      await page.getByText('未完成草稿，尚未保存为正式摘要。', { exact: true }).waitFor()
      const result = await api('/api/v1/analyses/' + brokenId + '/summary')
      assert.equal(result.status, 'failed'); assert.equal(result.summary.id, previous.id)
      assert.equal(await calls('断流'), 2)
      await page.screenshot({ path: path.join(artifacts, 'failed-regeneration.png'), fullPage: true })
      await generate('重试总结'); await release('断流', 3)
      await complete(brokenId, '断流：第 3 次概览 😀')
      assert.equal(await calls('断流'), 3)
    })
    await check('两次引用均无效时不保存摘要，不产生新导图', async () => {
      const invalidId = await create('ssebadref01')
      await open(invalidId); await generate(); await release('无效引用')
      await eventually(async () => await calls('无效引用') === 2)
      await release('无效引用', 2)
      await page.getByText('摘要结构或字幕引用无效，未保存为成功结果。', { exact: true }).waitFor()
      const result = await api('/api/v1/analyses/' + invalidId + '/summary')
      assert.equal(result.status, 'failed'); assert.equal(result.summary, null)
      await page.getByRole('button', { name: '思维导图', exact: true }).click()
      assert.equal(await page.locator('svg.map-canvas').count(), 0)
    })
    await check('长字幕的五段与两层汇总均采用流式输出，最终覆盖最后一段', async () => {
      const longId = await create('sselong0001')
      await open(longId); await generate()
      for (let attempt = 1; attempt <= 7; attempt++) {
        await eventually(async () => await calls('长视频') === attempt)
        await eventually(async () => (await page.locator('.summary-stream-text').innerText().catch(() => '')).includes('第 ' + attempt + ' 次'))
        if (attempt <= 5) await page.locator('.learning-progress').getByText('总结第 ' + attempt + '/5 段', { exact: true }).waitFor()
        else await page.locator('.learning-progress').getByText(attempt === 6 ? '汇总第 1 层（1/2）' : '汇总第 2 层（1/1）', { exact: true }).waitFor()
        if (attempt > 1) {
          assert.equal(await page.locator('.summary-stage-text').count(), attempt - 1)
          assert.match(await page.locator('.summary-stage-text').first().innerText(), /第 1 次/)
        }
        await release('长视频', attempt)
      }
      const saved = await complete(longId, '长视频：第 7 次概览 😀')
      assert.ok(saved.content.chapters[0].cue_ids.includes('c000005'))
      assert.equal((await api('/api/v1/analyses/' + longId)).usage.calls, 7)
      assert.equal((await api('/api/v1/analyses/' + longId + '/summary', { method: 'POST', data: { stream: true } })).cached, true)
      assert.equal(await calls('长视频'), 7)
    })
    await check('旧后端无阶段列表时，连续三次修复、断线重连及分段汇总不清空已显示文字', async () => {
      const legacyId = await create('sslegacy001')
      const postsBefore = posts
      await open(legacyId); await generate()
      await page.evaluate(() => {
        const state = window.__draftRetention = { texts: {}, violations: [], stopped: false }
        const sample = () => {
          if (state.stopped) return
          const nodes = Array.from(document.querySelectorAll('.summary-draft-part'))
          for (const [id, text] of Object.entries(state.texts)) {
            const node = nodes.find(item => item.dataset.partId === id)
            const next = node?.querySelector('.summary-stream-text, .summary-stage-text')?.textContent || ''
            if (!next.startsWith(text)) state.violations.push({ id, before: text.length, after: next.length })
          }
          for (const node of nodes) {
            const text = node.querySelector('.summary-stream-text, .summary-stage-text')?.textContent || ''
            if (text) state.texts[node.dataset.partId] = text
          }
        }
        const observer = new MutationObserver(sample)
        observer.observe(document.querySelector('.learning-panel'), { childList: true, subtree: true, characterData: true })
        state.stop = () => { sample(); state.stopped = true; observer.disconnect(); return state.violations }
        sample()
      })
      for (let attempt = 1; attempt <= 10; attempt++) {
        await eventually(async () => await calls('旧协议') === attempt)
        await eventually(async () => (await page.locator('.summary-stream-text').innerText().catch(() => '')).includes('第 ' + attempt + ' 次'))
        assert.equal(await page.locator('.summary-draft-part').count(), attempt)
        assert.doesNotMatch(await page.locator('.summary-draft-part > .learning-eyebrow').allTextContents().then(text => text.join('\n')), /修正第/)
        assert.deepEqual(await page.evaluate(() => window.__draftRetention.violations), [])
        if (attempt === 10) {
          assert.deepEqual(await page.evaluate(() => window.__draftRetention.stop()), [])
          await page.locator('.summary-draft-part').first().screenshot({ path: path.join(artifacts, 'legacy-retained-draft.png') })
        }
        if (attempt === 3) await api('/_test/summary-stream/disconnect', { method: 'POST', data: { record_id: legacyId } })
        await release('旧协议', attempt)
        if (attempt === 3) await page.getByText(/摘要流式连接暂时中断/).waitFor()
      }
      const saved = await complete(legacyId, '旧协议：第 10 次概览 😀')
      assert.ok(saved.content.chapters[0].cue_ids.includes('c000005'))
      assert.equal((await api('/api/v1/analyses/' + legacyId)).usage.calls, 10)
      assert.equal(posts, postsBefore + 1)
    })
    await check('删除生成中的记录后迟到的模型输出不能恢复记录或摘要', async () => {
      const deletedId = await create('ssedelete01')
      await open(deletedId); await generate()
      await page.getByRole('button', { name: /^本机学习记录/ }).click()
      await page.getByRole('button', { name: '删除记录：SSE摘要模拟：删除', exact: true }).click()
      await page.getByRole('button', { name: '确认删除', exact: true }).click()
      await eventually(async () => (await context.request.get(base + '/api/v1/analyses/' + deletedId)).status() === 404)
      await release('删除')
      assert.equal((await context.request.get(base + '/api/v1/analyses/' + deletedId + '/summary')).status(), 404)
    })
    await check('切换记录取消旧订阅，返回可接回任务；窄屏草稿与正式摘要不溢出', async () => {
      const switchId = await create('sseswitch01')
      await open(switchId); await generate()
      await open(id)
      assert.equal(await page.locator('.summary-stream-text').count(), 0)
      await page.setViewportSize({ width: 375, height: 812 })
      await open(switchId); await page.locator('.summary-stream-text').waitFor()
      assert.equal(await calls('切换'), 1)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      await page.screenshot({ path: path.join(artifacts, 'mobile-generating.png'), fullPage: true })
      await release('切换'); await complete(switchId, '切换：第 1 次概览 😀')
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      assert.deepEqual(errors, [])
    })
  } finally {
    await fs.writeFile(path.join(artifacts, 'report.json'), JSON.stringify({ simulation: true, checks, errors, failed }, null, 2))
    console.log(JSON.stringify({ passed: checks.length, checks, errors, failed }))
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
