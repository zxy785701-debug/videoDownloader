# 回归执行说明

更新日期：2026-10-07。最近一次验证结果见 [同屏验收报告](UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md)。以下命令从仓库根目录执行，测试与正式本机服务使用不同端口和数据库。

## 单元回归与构建

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
npm.cmd run build --prefix frontend
```

后端 `tests/conftest.py` 为单元测试设置隔离的学习配置和数据库，不读取真实密钥用于生成。最近结果为 255 项通过；保留一条既有 Starlette/httpx 弃用提示。前端构建包含 Vue／TypeScript 类型检查和 Vite 生产构建。

## 模拟浏览器流程

浏览器脚本依赖可解析的 `playwright` 包和本机 Microsoft Edge。可使用已配置的 Playwright 环境；本次使用 Codex 自带 Node／Playwright 运行时，通过 `NODE_PATH` 指向其模块目录，未将该机器路径写入项目依赖。多数旧脚本也支持 `PLAYWRIGHT_BROWSER_CHANNEL`；新增同屏脚本使用 `msedge`。

先构建前端，然后在独立终端启动所需 fixture。它们仅监听本机，使用 `.local/` 下的隔离 SQLite、模拟平台和模型。

| 终端服务 | 对应脚本 |
| --- | --- |
| `backend/.venv/Scripts/python.exe -m uvicorn tests.learning_preview:app --app-dir backend --host 127.0.0.1 --port 8180` | `node frontend/tests/learning-e2e.cjs` 或 `node frontend/tests/learning-export-e2e.cjs` |
| `backend/.venv/Scripts/python.exe -m uvicorn tests.chat_stream_preview:app --app-dir backend --host 127.0.0.1 --port 8184` | `node frontend/tests/chat-stream-e2e.cjs` |
| `backend/.venv/Scripts/python.exe -m uvicorn tests.summary_stream_preview:app --app-dir backend --host 127.0.0.1 --port 8185` | `node frontend/tests/summary-stream-e2e.cjs` |
| `backend/.venv/Scripts/python.exe -m uvicorn tests.unified_preview:app --app-dir backend --host 127.0.0.1 --port 8186` | `node frontend/tests/unified-workspace-e2e.cjs`，成功后可运行 `node frontend/tests/unified-layout.cjs` |

等待服务健康后运行脚本。每轮完整流程使用全新 fixture 进程；服务启动会创建新的隔离库。基础学习测试要求初始空历史，不能和导出测试共享同一数据库并发执行。若需并行，在另一端口启动独立 `learning_preview`，并在执行基础脚本的终端设置 `LEARNING_TEST_URL`。摘要／问答 SSE fixture 的控制状态同样须为新实例。

`unified-layout.cjs` 读取同屏 fixture 中已有成功摘要，只检查布局；需先完成同屏流程。测试完关闭自己启动的 fixture，保留正式服务。

草稿状态检查无需服务器：

```powershell
node frontend/tests/summary-draft-state.cjs
```

生成的 JSON、截图、下载样本和日志位于 `.local/`，已忽略 Git。最近 71 项模拟流程通过，另有 7 组布局和 6 项草稿状态检查；测试中未新增真实模型调用。

## 已有真实记录的离线复核

`tests.saved_unified_preview` 与 `unified-saved-e2e.cjs` 读取 `.local/unified-saved-data/learning-copy.sqlite3` 及 `records.json`。这些文件是本次以 SQLite 只读连接备份原库后生成的本机产物，仓库不包含用户数据库；不能在其他机器没有副本时直接运行该流程。

复核服务只模拟下载元信息，禁止创建模型客户端；浏览器只读取保存的摘要、字幕、导图和导出，并核对用量未变化。本次 4 条记录通过，学习 POST 为 0。正式服务的原库不作为模拟测试库。

## 真实平台与模型探针

`probe_*`、`verify_*_live`、`learning-live.cjs`、`learning-generated.cjs` 和相关 live preview 属于单独的真实验收工具，部分会读取本机登录会话或调用模型。它们不属于上述默认回归命令。新增真实模型验证按本次已确认的方案，先确定样例字幕与调用范围并取得用户确认；测试报告记录实际用量与证据，不能将模拟通过写成真实平台成功。
