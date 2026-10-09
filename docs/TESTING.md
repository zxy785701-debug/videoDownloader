# 回归执行说明

更新日期：2026-10-10。工作区完整验证见 [同屏验收报告](UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md)，最新公开页面扩展见 [SEO／GEO 验证](SEO_GEO_TEST_REPORT.md)。以下命令从仓库根目录执行，测试与正式本机服务使用不同端口和数据库。

最新前端参考改版验证见 [改版报告](FRONTEND_REFERENCE_REDESIGN.md)：45 项浏览器流程和 7 组工作区布局通过，生产构建通过；本轮没有修改后端，也没有新增真实付款或模型调用。

之后的 [总结登录与额度弹窗](SUMMARY_MEMBERSHIP_PROMPTS.md) 验证为 13 项专项加 45 项原浏览器回归，共 58 项；后端仍未修改，人工验收待确认。

## 单元回归与构建

2026-10-09 的来源与反向代理修复新增 105 项安全检查，完整后端 **410 项通过**；配置、缺失 Origin 规则和服务器人工验收见 [代理与可信来源配置](ORIGIN_PROXY_DEPLOYMENT.md)。服务器部署未在本轮执行。

同日后续的 [本地／云端 Cookie 双模式修复](LOCAL_CLOUD_COOKIE_MODES.md) 新增 24 项验证，最新完整后端 **434 项通过**（97.89 秒）。测试覆盖真实 yt-dlp 异常包装、匿名解析与文件交付、本机有效会话保留及字幕权限分类；只使用合成 Cookie 和隔离数据库。另固定了既有会员过期测试的时钟，避免夜间执行跨日造成错误断言；会员业务代码未修改。真实服务器平台访问与本机登录态待人工验收。

2026-10-10 的 [B 站 API 模式与 412 修复](BILIBILI_CLOUD_412.md) 再新增 34 项（API 模式 28 项、错误／字幕分类 6 项），最新完整后端 **468 项通过**（158.26 秒）。覆盖真实 SDK WBI 签名、原 Cookie 方式、分 P／身份／试看校验、字幕权限和合成音视频的 FFmpeg 校验、完整与 Range 文件响应。另用真实主服务代码匿名解析 `BV1N2pc6gErK`，仅请求 view、nav、playurl API，返回 5 个界面选项和 125.888 秒；服务器同一路径由用户确认返回 15 个原始格式和匹配完整时长，实际新版服务器文件下载仍待部署后验收。本轮没有修改前端，无需为该后端修复重建前端。

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
npm.cmd run build --prefix frontend
```

后端 `tests/conftest.py` 为单元测试设置隔离的学习配置和数据库，不读取真实密钥用于生成。最近结果为 305 项通过（含 43 项会员和 7 项流式性能回归）；保留一条既有 Starlette/httpx 弃用提示。前端构建包含 Vue／TypeScript 类型检查和 Vite 生产构建。最新本机开销基准和本轮 25 项流式浏览器检查见 [摘要性能修复报告](SUMMARY_STREAM_PERFORMANCE.md)。

## 模拟浏览器流程

浏览器脚本依赖可解析的 `playwright` 包和本机 Microsoft Edge。可使用已配置的 Playwright 环境；本次使用 Codex 自带 Node／Playwright 运行时，通过 `NODE_PATH` 指向其模块目录，未将该机器路径写入项目依赖。多数旧脚本也支持 `PLAYWRIGHT_BROWSER_CHANNEL`；新增同屏脚本使用 `msedge`。

先构建前端，然后在独立终端启动所需 fixture。它们仅监听本机，使用 `.local/` 下的隔离 SQLite、模拟平台和模型。

来源策略现在不自动授权自定义端口。启动以下浏览器 fixture 的终端需显式设置测试来源（仅用于本机测试，不复制到生产）：

```powershell
$env:ALLOWED_ORIGINS = 'http://127.0.0.1:8180,http://127.0.0.1:8184,http://127.0.0.1:8185,http://127.0.0.1:8186,http://127.0.0.1:8187'
$env:ALLOWED_HOSTS = '127.0.0.1,localhost'
$env:ACCOUNT_COOKIE_SECURE = 'false'
```

如用 `localhost` 或 `LEARNING_TEST_URL`／`MEMBERSHIP_TEST_APP_URL` 指定其他地址，添加其完整 Origin。独立会员 Mock fixture 的来源规则保持不变；以上仅配置主服务 fixture。

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

## SEO 静态页面检查

`npm.cmd run test:seo --prefix frontend` 使用 Node 内置测试，不依赖浏览器，验证域名、双语索引信息、预览不收录与输出边界。`npm.cmd run build:site --prefix frontend` 生成独立静态公开包；没有正式 `SEO_SITE_URL` 时为预览模式。

`frontend/tests/seo-e2e.cjs` 使用 Playwright 读取实际渲染的元数据和 JSON-LD，并检查移动布局、禁用 JavaScript 的阅读与内部链接。测试包、启动命令与结果见 [SEO 测试报告](SEO_TEST_REPORT.md)；不能把示例测试域名发布到生产。后端及既有浏览器回归继续按上文隔离流程执行。

`npm.cmd run test:geo --prefix frontend` 检查同源阅读导出、公开数据边界、爬虫组规则与已提交的源码依据。公开浏览器脚本另有 Markdown 内容一致性及爬虫策略检查，可通过 `SEO_TEST_OUTPUT` 指定产物目录；最新 38 项结果和 fixture 命令见 [联合报告](SEO_GEO_TEST_REPORT.md)。爬虫规则检查不是九个平台实际抓取或推荐的证明。

## 已有真实记录的离线复核

`tests.saved_unified_preview` 与 `unified-saved-e2e.cjs` 读取 `.local/unified-saved-data/learning-copy.sqlite3` 及 `records.json`。这些文件是本次以 SQLite 只读连接备份原库后生成的本机产物，仓库不包含用户数据库；不能在其他机器没有副本时直接运行该流程。

复核服务只模拟下载元信息，禁止创建模型客户端；浏览器只读取保存的摘要、字幕、导图和导出，并核对用量未变化。本次 4 条记录通过，学习 POST 为 0。正式服务的原库不作为模拟测试库。

## 会员支付与额度

会员扩展需先安装 `backend/requirements-billing.txt`，包含核心依赖及固定 Stripe SDK；完整 pytest 当前包含 43 项会员测试。默认注册不要求邮箱验证，测试也覆盖重新启用验证、邮件投递提示、连接复用及认证隔离。`frontend/tests/membership-initialization-e2e.cjs` 补充 7 项受控延迟与状态竞争检查，使用报告中的独立 fixture 和 `MEMBERSHIP_TEST_APP_URL`。支付、账号与额度测试使用隔离库和模拟支付，不访问 Stripe。两服务浏览器 fixture、最新结果和沙盒人工验收见 [会员报告](MEMBERSHIP_TEST_REPORT.md) 与 [Stripe 教程](STRIPE_TESTING_GUIDE.md)。模拟 fixture 不使用真实会员数据库。

## 参考设计与账号界面

`frontend/tests/reference-design-e2e.cjs` 在浏览器中拦截账号接口，用合成状态检查首页定价、密码显隐、焦点恢复、头像菜单、会员状态及 320／390px 布局。可以复用上文已启动的隔离 `unified_preview`，不需要真实账号或 Stripe 密钥；不要指向正式用户服务运行模拟脚本。

```powershell
$env:MEMBERSHIP_TEST_APP_URL = 'http://127.0.0.1:8186'
node frontend/tests/reference-design-e2e.cjs
```

脚本依赖前述 Playwright 环境，截图与报告写入 `.local/frontend-reference-design/`。本轮 12 项通过、没有账号付款请求或浏览器错误；会员真实 HTTP 代理与模拟账本的 13 项流程、初始化 7 项和原工作区 13 项另行执行，共 45 项浏览器流程。7 组工作区布局继续使用 `unified-layout.cjs` 检查。验收边界与最新截图目录见 [改版报告](FRONTEND_REFERENCE_REDESIGN.md)。

## AI 总结登录与额度弹窗

`frontend/tests/summary-membership-prompts-e2e.cjs` 需要独立的 `tests.billing_preview` 与 `tests.membership_preview` 两服务。与会员流程相同，在两个服务终端设置相同的 `MEMBERSHIP_TEST_DIR`（仓库 `.local/` 下的全新目录）、`MEMBERSHIP_TEST_SERVICE_URL`（模拟会员服务地址）及 `MEMBERSHIP_TEST_VERIFY_EMAIL=0`；浏览器终端设置 `MEMBERSHIP_TEST_APP_URL` 为工作区 fixture 地址。本轮使用 8490／8487，未使用真实 Stripe 密钥或模型。

```powershell
$env:MEMBERSHIP_TEST_APP_URL = 'http://127.0.0.1:8487'
node frontend/tests/summary-membership-prompts-e2e.cjs
```

脚本实际注册隔离账号并用完 3 次免费额度，再检查服务端拒绝与页面弹窗；会员用尽使用合成响应，不创建 30 次模型调用。重复执行须使用新的隔离账本和 fixture；不要指向正式用户服务。13 项结果及截图保存在 `.local/summary-membership-prompts-20261008/`，没有触发购买接口。原业务、初始化与设计回归的 45 项另外执行，证据范围见 [专项报告](SUMMARY_MEMBERSHIP_PROMPTS.md)。

## 真实平台与模型探针

`probe_*`、`verify_*_live`、`learning-live.cjs`、`learning-generated.cjs` 和相关 live preview 属于单独的真实验收工具，部分会读取本机登录会话或调用模型。它们不属于上述默认回归命令。新增真实模型验证按本次已确认的方案，先确定样例字幕与调用范围并取得用户确认；测试报告记录实际用量与证据，不能将模拟通过写成真实平台成功。
