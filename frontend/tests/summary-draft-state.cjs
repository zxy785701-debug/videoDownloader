// Run directly with node; no browser, backend or model calls are needed.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('../node_modules/typescript')
const moduleExports = {}
const source = fs.readFileSync(path.resolve(__dirname, '../src/learning/summaryDraft.ts'), 'utf8')
new Function('exports', ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText)(moduleExports)
const { mergeSummaryDraft } = moduleExports
const merge = (previous, snapshot) => mergeSummaryDraft(previous, snapshot, '等待总结')
const checks = []
function check(name, action) { action(); checks.push(name) }

check('旧快照的空白重置与较短前缀不删除已读文本，不修改上一份快照', () => {
  const first = merge(null, { stage: '第 1 段', text: '第一版完整草稿', phase: 'generating' })
  let next = merge(first, { stage: '第 1 段', text: '' })
  next = merge(next, { stage: '第 1 段', text: '' })
  next = merge(next, { stage: '第 1 段', text: '第一版' })
  assert.equal(next.parts[0].text, '第一版完整草稿')
  next = merge(next, { stage: '第 1 段', text: '修正后的草稿' })
  assert.deepEqual(next.parts.map(part => part.text), ['第一版完整草稿', '修正后的草稿'])
  assert.equal(next.parts[0].phase, 'retained')
  assert.equal(next.parts[1].attempt, 1)
  assert.equal(first.parts[0].phase, 'generating')
})
check('旧后端前缀改变时保留过程版本，不凭文字变化冒称 AI 修复', () => {
  const first = merge(null, { stage: '第 1 段', text: '原版本内容' })
  const next = merge(first, { stage: '第 1 段', text: '新的修复内容' })
  assert.equal(next.parts.length, 2)
  assert.deepEqual(next.parts.map(part => part.text), ['原版本内容', '新的修复内容'])
  assert.ok(next.parts.every(part => part.attempt === 1))
})
check('旧后端切换分段与汇总时，所有阶段及一次修正持续保留', () => {
  let state = merge(null, { stage: '等待总结', phase: 'waiting', text: '' })
  for (const snapshot of [
    { stage: '第 1 段', text: '第一段原稿', phase: 'generating' },
    { stage: '第 1 段', text: '第一段修正版', phase: 'validating' },
    { stage: '第 2 段', text: '', phase: 'generating' },
    { stage: '第 2 段', text: '第二段内容', phase: 'validating' },
    { stage: '汇总', text: '', phase: 'generating' },
    { stage: '汇总', text: '最终汇总', phase: 'generating' },
  ]) state = merge(state, snapshot)
  assert.deepEqual(state.parts.map(part => part.text), ['第一段原稿', '第一段修正版', '第二段内容', '最终汇总'])
  assert.deepEqual(state.parts.map(part => part.id), [1, 2, 3, 4])
})
check('新版完整快照重连时，空文本、缩短文本或遗漏历史不使卡片消失', () => {
  const parts = [
    { id: 1, stage: '第 1 段', text: '已校验第一段', phase: 'validated', attempt: 1 },
    { id: 2, stage: '第 2 段', text: '第二段已有内容', phase: 'generating', attempt: 1 },
  ]
  let state = merge(null, { stage: '第 2 段', text: parts[1].text, parts })
  state = merge(state, { stage: '第 2 段', text: '', parts: [{ ...parts[1], text: '' }] })
  state = merge(state, { stage: '第 2 段', text: '第二段', parts: [{ ...parts[1], text: '第二段' }] })
  state = merge(state, { stage: '第 2 段', text: '', parts: [] })
  assert.deepEqual(state.parts.map(part => part.text), parts.map(part => part.text))
  assert.equal(state.text, '第二段已有内容')
})
check('新版追加修正版使用稳定 ID，重放快照不重复卡片', () => {
  const parts = [
    { id: 1, stage: '第 1 段', text: '未校验原稿', phase: 'superseded', attempt: 1 },
    { id: 2, stage: '第 1 段', text: '修正稿', phase: 'generating', attempt: 2 },
  ]
  const snapshot = { stage: '第 1 段', text: '修正稿', parts }
  let state = merge(null, snapshot)
  for (let i = 0; i < 5; i++) state = merge(state, snapshot)
  assert.deepEqual(state.parts, parts)
})
check('无内容的等待占位不会累积为多余卡片，断线等待不清空有效草稿', () => {
  let state = merge(null, { stage: '等待总结', phase: 'waiting', text: '' })
  state = merge(state, { stage: '第 1 段', text: '正文' })
  state = merge(state, { stage: '等待总结', phase: 'waiting', text: '' })
  assert.equal(state.parts.length, 1)
  assert.equal(state.parts[0].text, '正文')
})
console.log(JSON.stringify({ passed: checks.length, checks }))
