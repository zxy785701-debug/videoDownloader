# 视频问答 SSE 测试与验收报告

日期：2026-10-06。实现方案及用户确认见 [SSE 方案](AI_QA_SSE_PLAN.md)。

## 1. 当前验证结果

| 检查 | 结果 |
| --- | --- |
| 后端全量回归 | 215 项通过：原有 194 项＋21 项 SSE 测试；保留 1 条既有 Starlette/httpx 弃用提示 |
| 前端类型与生产构建 | `npm.cmd run build` 通过（vue-tsc＋Vite） |
| 原功能浏览器回归 | 13 项通过：下载、摘要、字幕、导图、问答、历史、语言和删除 |
| 展示与导出回归 | 20 项通过：全屏、滚轮、首次展开、自适应样式、完整 PNG/SVG/SRT/TXT 等 |
| 流式专项自动检查 | 11 项通过，包含前端流解析与实际 HTTP 页面流程；浏览器脚本错误为 0 |
| DeepSeek 官方真实 SSE | 尚未执行，待用户确认此次样例字幕发送与账户用量 |

模拟验证使用独立 SQLite、假字幕和 httpx MockTransport。它覆盖真实后端任务/HTTP SSE/页面状态/数据库校验保存，但不代表已调用真实平台或付费模型。已有功能和本次流式专项共 44 项前端自动检查通过。

## 2. 专项覆盖

后端验证模型 `stream:true` 与用量选项、当前和旧版 usage 帧、跨包中文、JSON 转义及 emoji、缺失结束帧、截断/空内容/无效 JSON、超时、请求标识去重、订阅重连、最终引用映射、一次有界修复、活动订阅删除、15 秒心跳、本机来源限制、记录/消息匹配、重启中断且不重新提交模型，以及后台草稿回收。

页面专项检查：

1. UTF-8 逐字节传输、CRLF、多行 data、终止帧和未完成连接的解析。
2. 完成前草稿持续增长，数据库尚无正式回答，页面无正式引用。
3. 页签切换、离开学习工作区和刷新均接回原消息，模型调用次数保持一次。
4. SSE 与状态查询分别临时断开后自动恢复，完整快照替换不重复拼接，最终文本与字幕引用正确保存。
5. 已完成回答刷新恢复，引用跳到第 150 段原文；重新读取不增加模型用量。
6. 首版引用错误后进行一次修复，先清空旧草稿，不合并两版文本，只保存第二版成功回答。
7. 模型断流保留当前页的未校验草稿，不保存成功回答、不自动再调用；手动重新提问才创建新请求。
8. 两次引用均无效时显示失败，无正式引用，数据库回答为 null。
9. 清空进行中对话后消息不被迟到任务写回，刷新仍为空。
10. 切换视频记录不显示旧草稿，返回仍可继续原任务。
11. 375 px 窄屏正常换行，无横向页面溢出或脚本异常。

已人工查看生成中和完成后的桌面截图，以及窄屏检查结果。生成中明确标注未校验状态；完成后移除草稿标签，并显示正式字幕引用。

## 3. 真实验证状态

准备使用用户之前提供的 [B 站样例 BV1Y5aq6gEV3](https://www.bilibili.com/video/BV1Y5aq6gEV3/)，从本机学习数据库通过 SQLite 只读备份创建测试副本。拟提交一个问题：“请依据视频字幕，用三个要点概括核心内容，并引用支持这些要点的原文。”密钥只由后端读取 `.env`，不进入报告。

自动审批拒绝执行此次请求，原因是尚未明确授权向 `api.deepseek.com` 发送这一条视频的完整字幕及问题。**请求未执行，未新增这次模型调用。** 已向用户请求确认；模拟开发与验证不受影响。用户授权后可执行一次真实调用，记录首段文本耗时、不同草稿帧、正式引用及用量，并确认重新读取最终事件不会增加调用。

## 4. 复现与证据

项目根目录运行：

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Push-Location frontend
npm.cmd run build
Pop-Location

# 普通回归：启动后先运行 learning-e2e，再运行 learning-export-e2e。
backend\.venv\Scripts\python.exe -m uvicorn tests.learning_preview:app --app-dir backend --host 127.0.0.1 --port 8180
node frontend/tests/learning-e2e.cjs
node frontend/tests/learning-export-e2e.cjs

# SSE 专项：使用另一个新启动的独立测试实例。
backend\.venv\Scripts\python.exe -m uvicorn tests.chat_stream_preview:app --app-dir backend --host 127.0.0.1 --port 8184
node frontend/tests/chat-stream-e2e.cjs
```

浏览器测试需要 Playwright 及 Edge，默认 `msedge`；本次使用 Codex 本机已安装的运行时，无新增依赖。服务命令和 node 脚本需在不同终端运行；SSE 专项完整重跑前重新启动测试服务，确保隔离数据库和计数器为初始状态。

本机原始证据位于忽略的 `.local/learning-browser-test/results.json`、`.local/learning-export-test/report.json`、`.local/chat-stream-browser-test/report.json` 及生成/完成/窄屏截图。真实验证脚本为 `backend/tests/verify_chat_stream_live.py`，必须显式指定地址、测试副本记录 ID 和报告路径；不会自动重提问题。

## 5. 用户验收

1. 停止旧后端，项目根目录运行 `.\start-local.ps1 -Port 8181 -UseFirefoxSubtitleSession`，打开 `http://127.0.0.1:8181` 并 Ctrl＋F5 刷新。
2. AI 学习中打开已有字幕记录，进入“视频问答”，输入一个视频内容问题，观察回答逐步出现及“引用尚未校验”提示。
3. 完成后确认正式引用出现且能够定位到原文。生成中刷新或离开后返回，应继续同一问题，不新增问答。
4. 已完成记录刷新应恢复；清空对话后刷新仍为空。服务重启期间未完成问题应提示中断，需手动重新提问。

当前仍按个人本机单实例使用。页面断线后后台可以继续，服务进程停止则不能继续生成；草稿不作为正式历史保存。引用校验不代替用户对回答语义准确性的验收。
