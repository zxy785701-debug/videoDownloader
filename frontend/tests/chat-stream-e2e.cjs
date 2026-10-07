// Run against tests.chat_stream_preview on port 8184. No paid model or platform calls.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const ts = require('../node_modules/typescript')
const base = process.env.CHAT_STREAM_TEST_URL || 'http://127.0.0.1:8184'
const artifacts = path.resolve(__dirname, '../../.local/chat-stream-browser-test')
const checks = [], errors = []
const TEXT = '通过主动回忆检查学习效果。\n先复述 "概念"，再结合例子练习 😀。'.repeat(3)
let browser, context, page, failed = null

async function check(name, action) {
  try { await action(); checks.push(name) }
  catch (error) { failed = { name, message: error.stack }; throw error }
}
async function api(url, options) {
  const response = await context.request.fetch(base + url, options)
  assert.ok(response.ok(), 'API: ' + url + ': ' + response.status())
  return response.status() === 204 ? null : response.json()
}
async function release(question, attempt = 1) {
  assert.equal((await api('/_test/chat-stream/release', { method: 'POST', data: { question, attempt } })).released, true)
}
async function calls(question) { return (await api('/_test/chat-stream/stats')).calls[question] || 0 }
async function record(suffix) {
  const result = await api('/api/v1/analyses', { method: 'POST', data: { url: 'https://youtu.be/' + suffix, language: 'auto' } })
  await assertEventually(async () => (await api('/api/v1/analyses/' + result.id)).subtitle_status === 'ready')
  return result.id
}
async function assertEventually(condition) {
  for (let i = 0; i < 80; i++) { if (await condition()) return; await new Promise(resolve => setTimeout(resolve, 100)) }
  assert.fail('Condition did not become true')
}
async function open(id) {
  await page.goto(base + '/#learn/' + id)
  await page.getByRole('button', { name: '视频问答', exact: true }).click()
  await page.getByLabel('你的问题').waitFor()
}
async function send(question) {
  await page.getByLabel('你的问题').fill(question)
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await page.locator('.chat-stream-text').last().waitFor({ timeout: 10000 })
  await page.getByText('正在生成，引用尚未校验…', { exact: true }).waitFor()
}
async function finalAnswer(index = 0) {
  const answer = page.locator('.chat-turn').nth(index).locator('.chat-answer')
  await answer.getByRole('button', { name: '49:40 原文', exact: true }).waitFor({ timeout: 12000 })
  assert.equal(await answer.locator('p').nth(1).innerText(), TEXT)
  assert.equal(await answer.locator('.chat-stream-text').count(), 0)
}

;(async () => {
  await fs.mkdir(artifacts, { recursive: true })
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  try {
    await check('前端 SSE 解码支持逐字节 UTF-8、CRLF、多行 data 与终止帧', async () => {
      const source = await fs.readFile(path.join(__dirname, '../src/learning/chatStream.ts'), 'utf8')
      const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
      const { readChatStream } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))
      const original = global.fetch, events = []
      const bytes = new TextEncoder().encode(': comment\r\nevent: snapshot\r\ndata: {"message_id":"a",\r\ndata: "text":"中文 😀\\n引号\\\""}\r\n\r\nevent: complete\r\ndata: {"message_id":"a"}\r\n\r\n')
      global.fetch = async () => new Response(new ReadableStream({ start(c) { for (const byte of bytes) c.enqueue(Uint8Array.of(byte)); c.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })
      try {
        await readChatStream('/test', event => events.push(event), new AbortController().signal)
        assert.deepEqual(events.map(item => item.event), ['snapshot', 'complete'])
        assert.equal(events[0].data.text, '中文 😀\n引号"')
        global.fetch = async () => new Response('event: snapshot\ndata: {"text":"partial"}\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
        await assert.rejects(readChatStream('/test', () => {}, new AbortController().signal), /中断/)
      } finally { global.fetch = original }
    })
    const id = await record('ssetest0001')
    const question = 'SSE测试刷新恢复'
    let messageId, posts = 0
    page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/chat')) posts++ })
    await check('真实 HTTP 流中草稿逐步增长，校验前没有正式引用和保存结果', async () => {
      await open(id); await send(question)
      const draft = page.locator('.chat-stream-text'), first = await draft.innerText()
      await assertEventually(async () => (await draft.innerText()).length > first.length)
      assert.ok((await draft.innerText()).length < TEXT.length)
      assert.equal(await page.locator('.chat-answer .learning-reference').count(), 0)
      const messages = (await api('/api/v1/analyses/' + id + '/messages')).items
      messageId = messages[0].id
      assert.equal(messages[0].answer, null)
      assert.equal(messages[0].status, 'processing')
      await page.screenshot({ path: path.join(artifacts, 'generating.png'), fullPage: true })
    })
    await check('切换页签、离开工作区、刷新后接回同一任务，不增加模型调用', async () => {
      await page.getByRole('button', { name: '字幕原文', exact: true }).click()
      await page.getByRole('button', { name: '视频问答', exact: true }).click()
      await page.locator('.chat-stream-text').waitFor()
      await page.getByRole('button', { name: '换个链接', exact: true }).click()
      await open(id)
      await page.locator('.chat-stream-text').waitFor()
      await page.reload()
      await page.getByRole('button', { name: '视频问答', exact: true }).click()
      await page.locator('.chat-stream-text').waitFor()
      assert.equal((await api('/api/v1/analyses/' + id + '/messages')).items[0].id, messageId)
      assert.equal(await calls(question), 1); assert.equal(posts, 1)
    })
    await check('临时断开 SSE 自动重连，快照替换避免重复，正式回答与引用保存', async () => {
      let interrupted = false, statusInterrupted = false
      await page.route('**/messages/*/stream', async route => {
        if (!interrupted) { interrupted = true; await route.abort('failed') }
        else await route.continue()
      })
      await page.route('**/messages', async route => {
        if (interrupted && !statusInterrupted) { statusInterrupted = true; await route.abort('failed') }
        else await route.continue()
      })
      await page.reload()
      await page.getByRole('button', { name: '视频问答', exact: true }).click()
      await page.getByText(/流式连接暂时中断/).waitFor()
      await page.locator('.chat-stream-text').waitFor({ timeout: 12000 })
      assert.equal(statusInterrupted, true)
      assert.equal(await calls(question), 1)
      assert.ok(TEXT.startsWith(await page.locator('.chat-stream-text').innerText()))
      await release(question); await finalAnswer()
      assert.equal(await calls(question), 1)
      const messages = (await api('/api/v1/analyses/' + id + '/messages')).items
      assert.equal(messages[0].status, 'ready'); assert.equal(messages[0].answer.answer, TEXT)
      assert.equal(messages[0].answer.references[0].cue_id, 'c000150')
      assert.equal((await api('/api/v1/analyses/' + id)).usage.calls, 1)
      await page.unroute('**/messages/*/stream')
      await page.unroute('**/messages')
      await page.screenshot({ path: path.join(artifacts, 'completed.png'), fullPage: true })
    })
    await check('已保存回答刷新恢复，引用跳转到原文且不会重新计费', async () => {
      await open(id); await finalAnswer()
      await page.getByRole('button', { name: '49:40 原文', exact: true }).click()
      await page.locator('#cue-c000150').waitFor()
      assert.equal(await calls(question), 1)
    })
    await check('校验失败修复时清空第一版草稿，仅保存第二版正式回答', async () => {
      const repair = 'SSE测试引用修复'
      await open(id); await send(repair)
      await page.getByText(/第一版待校验草稿：/).waitFor()
      await release(repair)
      await assertEventually(async () => await calls(repair) === 2)
      await assertEventually(async () => {
        const text = await page.locator('.chat-stream-text').last().innerText().catch(() => '')
        return !!text && !text.includes('第一版')
      })
      assert.equal(await page.locator('.chat-turn').last().locator('.learning-reference').count(), 0)
      await release(repair, 2); await finalAnswer(1)
      assert.equal(await calls(repair), 2)
    })
    await check('模型断流保留未校验草稿、无成功保存，手动重新提问才产生新请求', async () => {
      const lost = 'SSE测试模型断流'
      await send(lost); await release(lost)
      await page.getByText('上方内容为未完成草稿，尚未校验或保存为正式回答。', { exact: true }).waitFor()
      let items = (await api('/api/v1/analyses/' + id + '/messages')).items
      assert.equal(items.at(-1).status, 'failed'); assert.equal(items.at(-1).answer, null)
      assert.equal(await calls(lost), 1)
      await page.getByRole('button', { name: '重新提问', exact: true }).click()
      await page.getByRole('button', { name: '发送问题', exact: true }).click()
      await assertEventually(async () => await calls(lost) === 2)
      await page.locator('.chat-stream-text').last().waitFor()
      await release(lost, 2); await finalAnswer(3)
      assert.equal(await calls(lost), 2)
    })
    await check('两次引用校验都失败时不展示正式引用、不保存为成功', async () => {
      const invalid = 'SSE测试无效引用'
      await send(invalid); await release(invalid)
      await assertEventually(async () => await calls(invalid) === 2)
      await release(invalid, 2)
      await page.getByText('回答结构或字幕引用无效，未保存为成功结果。', { exact: true }).waitFor()
      const last = (await api('/api/v1/analyses/' + id + '/messages')).items.at(-1)
      assert.equal(last.status, 'failed'); assert.equal(last.answer, null)
      assert.equal(await page.locator('.chat-turn').last().locator('.learning-reference').count(), 0)
    })
    await check('清空进行中的对话后后台不可写回已删除消息', async () => {
      const clear = 'SSE测试清空对话'
      await send(clear)
      await page.getByRole('button', { name: '清空对话', exact: true }).click()
      await page.getByRole('button', { name: '确认清空', exact: true }).click()
      await assertEventually(async () => await page.locator('.chat-turn').count() === 0)
      await release(clear)
      await assertEventually(async () => !(await api('/api/v1/analyses/' + id)).jobs.some(job => job.kind === 'chat' && ['processing', 'queued'].includes(job.status)))
      assert.equal((await api('/api/v1/analyses/' + id + '/messages')).items.length, 0)
      await page.reload(); await page.getByRole('button', { name: '视频问答', exact: true }).click()
      assert.equal(await page.locator('.chat-turn').count(), 0)
    })
    await check('切换到其他记录时不显示旧草稿，返回后任务仍可继续', async () => {
      const switchQuestion = 'SSE测试切换记录', otherId = await record('ssetest0002')
      await open(id); await send(switchQuestion)
      await open(otherId)
      assert.equal(await page.locator('.chat-stream-text').count(), 0)
      assert.equal(await page.locator('.chat-turn').count(), 0)
      await open(id); await page.locator('.chat-stream-text').waitFor()
      assert.equal(await calls(switchQuestion), 1)
      await release(switchQuestion); await finalAnswer()
    })
    await check('窄屏流式回答换行正常，无页面横向溢出或脚本异常', async () => {
      await page.setViewportSize({ width: 375, height: 812 })
      await open(id)
      const mobile = 'SSE测试窄屏显示'
      await send(mobile)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      await release(mobile); await finalAnswer(1)
      await page.screenshot({ path: path.join(artifacts, 'mobile.png'), fullPage: true })
      assert.deepEqual(errors, [])
    })
  } finally {
    await fs.writeFile(path.join(artifacts, 'report.json'), JSON.stringify({ simulation: true, checks, errors, failed }, null, 2))
    console.log(JSON.stringify({ passed: checks.length, checks, errors, failed }))
    await browser.close()
  }
})().catch(error => { console.error(error.message); process.exitCode = 1 })
