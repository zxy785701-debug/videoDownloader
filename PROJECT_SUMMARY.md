# 视频下载项目完成总结

更新日期：2026-10-05。产品：**万能视频下载器**，当前界面名称 **save any**。本文以当前源码、最近完成的回归检查及真实验收报告为依据，汇总下载与 AI 学习功能；早期方案和界面演进记录继续保留在专题文档中。

**2026-10-05 下载扩展：**接入 B 站 Firefox 优先与匿名回退、同格式备用 CDN、分 P 和试看检查；新增芒果官网 pcweb 播放参数适配、完整清单检查及清晰度选择。186 项后端测试全部通过；B 站充电视频、芒果电影及电视剧均通过真实 HTTP 下载、附件保存、Range 响应与完整音视频解码。详见 [适配接入报告](DOWNLOAD_ADAPTER_INTEGRATION.md)。

**2026-10-04 AI 学习扩展：**完成摘要、时间戳字幕、导图、视频问答及 SQLite 本机历史。当时通过 142 项后端回归、前端构建及 13 项模拟浏览器流程；两条 B 站/YouTube 短视频的真实 DeepSeek 生成成功，8 个真实问答已核对。上述后端用例已包含在当前 186 项回归中。抖音字幕访问受阻，真实 60～120 分钟摘要质量与用户内容验收仍待完成。详见 [AI 功能方案](AI_VIDEO_SUMMARY_PLAN.md) 与 [测试报告](AI_VIDEO_SUMMARY_TEST_REPORT.md)。

## 1. 完成情况

已完成个人本地使用的两条流程：

- 下载：**粘贴链接 → 解析信息 → 选择格式与保存方式 → 准备文件 → 保存到设备**。
- AI 学习：**创建学习记录 → 提取平台字幕 → 查看原文 → 生成摘要与导图 → 针对视频问答 → 本机保存或导出**。

前端提供响应式页面、结果弹窗、格式选择、任务进度和失败重试；后端负责地址检查、平台解析、音视频合并、下载任务与文件交付。可以在本机用一个 FastAPI 进程同时提供构建后的页面和 API，也可以在开发时分别启动 Vite 与 API。

项目继续按个人本机、单实例设计。学习记录保存到 SQLite，下载任务仍保存在进程内；没有站内账号、支付、批量下载、语音转录或视频画面分析。

## 2. 已实现功能与平台范围

| 功能 | 当前行为 |
| --- | --- |
| 链接解析 | 接受单视频公开 HTTP(S) 链接，返回标题、来源、封面、时长和可选格式 |
| 格式选择 | yt-dlp 来源提供最佳画质及最多 12 个选项（含最佳画质）；抖音提供原始 MP4 格式 |
| 音视频合并 | 分离视频轨使用 `video:<format_id>` 标识，下载时自动选择音频并由 FFmpeg 合并 |
| 浏览器会话 | B 站和芒果默认优先 Firefox，可独立禁用；YouTube 继续使用原显式配置 |
| 完整性与备用地址 | B 站保留分 P、检查试看并尝试同格式备用 CDN；芒果检查完整 HLS；两者交付前检查音视频轨道和时长 |
| 下载方式 | 支持 `auto`、`server`、`redirect`；默认自动选择，平台可限制可用方式 |
| 状态与进度 | 后台下载、状态查询、已知大小时显示百分比、完成后显示“保存到设备” |
| 文件交付 | 服务端文件以附件响应返回；可用直链任务返回 302；文件响应支持 Range 请求 |
| 封面 | 使用登记 token 的同源封面接口，兼容来源站 Referer 要求 |
| 交互 | 剪贴板粘贴、解析等待、错误分类提示、重新解析/下载重试、结果弹窗关闭与再次打开 |
| 本地启动 | `start-local.ps1` 构建前端并启动仅监听 `127.0.0.1` 的 API |
| AI 摘要 | 根据完整可用字幕生成中文总览、章节及核心知识点，引用定位到原文 |
| 字幕原文 | 时间戳、搜索、分页、语言版本、人工/自动轨标签和 SRT 导出 |
| 思维导图 | 使用同一摘要生成可展开、缩放、拖动的 SVG 树，窄屏显示树形列表 |
| 视频问答 | 根据字幕和最近 5 轮成功对话回答，校验引用；没有依据时明确提示 |
| 学习历史与导出 | SQLite 保存字幕、摘要、问答及中间结果；刷新/重启恢复，手动删除，导出摘要 Markdown |

| 平台 | 实现方式 | 支持范围与已记录的验证 |
| --- | --- | --- |
| 哔哩哔哩 | yt-dlp + 本机 Firefox / 匿名回退 + 备用 CDN | 用户充电视频第 4 P 已通过实际 HTTP 下载与完整解码；提供 360/480/720/1080P，完整下载验收选择 480P |
| 芒果 TV | yt-dlp + 官网 pcweb 参数适配 + Firefox | 用户电影《流浪地球》和电视剧样例均完整下载通过；提供四档清晰度，标清已通过 HTTP 保存、Range 和完整解码 |
| YouTube | yt-dlp + EJS / Node，必要时使用显式选择的本机浏览器会话 | 已记录 Firefox 登录态下的服务层解析、下载、合并及完整音视频解码成功；该次没有完整网页 HTTP 端到端验收；同一测试环境匿名模式未通过登录验证 |
| 抖音 | 独立匿名分享页适配器 | 支持 `/video/<id>`、含 `modal_id` 的链接、短链接和移动分享页；已记录真实网页解析、下载、`ready` 状态、保存入口及 Range 响应 |
| 其他来源 | yt-dlp 提取器 | 已有 Generic 公开视频浏览器下载记录；具体站点是否可用取决于提取器、网络和来源限制 |

抖音只支持公开普通视频、自动/服务端交付，单文件上限 **1 GiB**；图集、直播、私密及已删除作品不在支持范围内。平台可用性会随上游页面和接口变化，既有样例成功不代表全部视频均可下载。

AI 首版仅尝试 B 站、抖音、YouTube 的平台字幕；没有可用字幕或访问受阻时提示暂不能总结，保留下载入口。芒果的下载支持没有扩展为芒果 AI 字幕支持。当前真实 B 站和 YouTube 字幕及生成成功，抖音仍受接口访问限制。

## 3. 架构与代码入口

前端：Vue 3、TypeScript、Vite、Tailwind CSS、Lucide 图标。

后端：FastAPI、Pydantic、yt-dlp、httpx、FFmpeg（系统安装或 `imageio-ffmpeg` 回退）。下载使用 `BackgroundTasks` 和带锁的内存任务表；学习使用独立线程池与 SQLite 持久化，DeepSeek 通过官方 API 接入。

```text
videoDownloader/
├─ frontend/
│  ├─ src/App.vue                 页面状态、解析请求和任务轮询
│  ├─ src/components/             输入、格式、下载、帮助及弹窗组件
│  ├─ src/types/video.ts          前端视频/任务类型
│  ├─ src/learning/              学习工作区、导图、API 客户端与类型
│  ├─ tests/                     模拟/真实学习页面验收脚本
│  ├─ src/ui/motion.ts            动效时长与减少动态效果处理
│  ├─ src/style.css               公共样式与响应式布局
│  ├─ tailwind.config.js          视觉与布局变量
│  ├─ vite.config.ts              Vue/Tailwind 插件与开发 API 代理
│  └─ package-lock.json           前端依赖锁定
├─ backend/
│  ├─ app/main.py                 API 路由及前端静态文件托管
│  ├─ app/schemas.py              请求/响应模型
│  ├─ app/security.py             公网 HTTP(S) 地址校验
│  ├─ app/video_service.py        平台分流、格式、任务、合并与封面
│  ├─ app/platform_adapters.py    B 站/芒果会话、提取器、备用 CDN 与文件校验
│  ├─ app/douyin.py               抖音分享页解析和 MP4 下载校验
│  ├─ app/analysis_*.py          学习路由、任务、SQLite 存储、模型及错误
│  ├─ app/ai_config.py           本机 AI 配置白名单与处理上限
│  ├─ app/subtitle_service.py    平台字幕获取、归一化与时间轴
│  ├─ app/summary_service.py     分段摘要、合并、导图和引用校验
│  ├─ app/chat_service.py        字幕问答及对话上下文
│  ├─ app/deepseek_client.py     模型请求、输出校验、重试与用量
│  ├─ tests/                     186 项回归及平台/模型/HTTP 验收探针
│  ├─ requirements.txt           必需依赖
│  └─ requirements-youtube.txt   可选 PO Token 插件依赖
├─ start-local.ps1               Windows 个人本地启动入口
├─ .env.example                 无密钥 AI 配置模板
├─ README.md                     安装、运行与文档导航
└─ PROJECT_SUMMARY.md            当前版本总结与交接入口
```

`frontend/dist/` 是可重新构建的产物；`backend/downloads/`、`backend/data/`、`.local/` 与真实 `.env` 是本机运行数据，均不进入版本控制。

## 4. 核心流程与接口

1. 前端发送解析请求；服务端校验协议、凭据和目标公网 IP。
2. 抖音链接进入专用模块，B 站/芒果进入新适配层，其余来源进入原 yt-dlp 流程；解析结果不包含上游媒体 URL 或 Cookie。
3. 用户选定格式和方式，服务端创建随机任务 ID，返回状态入口和文件入口。
4. 后台任务重新解析并下载，按来源处理会话、备用地址、清晰度、音频合并和文件校验；B 站/芒果/YouTube/抖音使用自动或服务端交付。
5. 前端约每 900 ms 查询任务状态，完成后提供文件入口；失败时显示可操作的提示。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/v1/health` | 健康检查 |
| `POST /api/v1/parse` | 解析视频，请求字段为 `url` |
| `POST /api/v1/downloads` | 创建任务，请求字段为 `url`、`format_id`、`delivery_mode`；返回 HTTP 202 |
| `GET /api/v1/downloads/{task_id}` | 查询任务状态、方式、进度、文件名、错误和到期时间 |
| `GET /api/v1/downloads/{task_id}/file` | 获取附件文件或 302 跳转；未就绪返回 409，失败返回 422，不存在/过期返回 404 |
| `GET /api/v1/thumbnails/{token}` | 获取服务端登记的封面 |
| `GET /docs` | 自动生成的 API 文档 |

任务状态为 `pending → processing → ready / failed`。下载地址在任务完成后可用；直链方式会让浏览器访问来源地址。接口详细模型以 `schemas.py` 和 `/docs` 为准。

学习 API 使用同一 `/api/v1` 前缀：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /ai/config` | 可公开的模型配置与是否已配置密钥，不返回密钥 |
| `POST /analyses`、`GET /analyses` | 创建字幕任务、查询本机学习历史 |
| `GET /analyses/{record_id}` | 记录详情、字幕元信息、最近作业及用量 |
| `GET /analyses/{record_id}/transcript` | 字幕分页、搜索与引用定位 |
| `POST /analyses/{record_id}/summary`、`GET /analyses/{record_id}/summary` | 生成和查看摘要、章节、导图与引用 |
| `POST /analyses/{record_id}/chat`、`GET /analyses/{record_id}/messages` | 提问及查看对话历史 |
| `GET /analyses/{record_id}/export` | 导出 Markdown 摘要或 SRT 字幕 |
| `DELETE /analyses/{record_id}`、`DELETE /analyses/{record_id}/messages` | 删除学习记录或清空对话 |

学习先取得字幕再调用模型，成功分段可复用；重启中断的作业需要人工重试，不自动重新计费。引用 ID 与结构校验通过不等于结论语义一定准确，仍需结合原文验收。

## 5. 关键实现决策与经验

- **平台适配集中在服务层。** B 站、芒果和抖音复用现有 API 和任务协议。B 站/芒果的解析与下载使用同一会话规则；提取器覆盖当前实例，不修改已安装的 yt-dlp 源码。
- **格式值区分显示与执行。** “最佳画质”仍映射为 `bv*+ba/best`。B 站/芒果明确选择分离视频轨时使用 `<format_id>+ba`，不可用即失败，不静默降低画质；其他来源保留原 `<format_id>+ba/best` 规则。未知合并大小不显示误导性估算。
- **交付方式由实际处理要求决定。** B 站、芒果、YouTube、抖音使用服务端交付，显式选择直链会得到提示；其他来源仅在已解析目标为公网 HTTP(S)、无需额外请求头且不含多条合并轨时考虑直链。
- **抖音不依赖旧 iteminfo 接口。** 已有测试中该接口返回空内容；适配器使用移动分享页数据、有限重试和独立匿名访客会话，按作品编号精确匹配，不执行页面 JavaScript。
- **临时播放地址重新获取。** 抖音在下载时再次解析，避免沿用解析阶段已过期的媒体链接；下载检查 MIME、长度、大小上限和 MP4 顶层容器结构，失败清理残片并尝试候选地址。
- **本机会话按平台隔离。** B 站/芒果默认优先 Firefox，可独立禁用和指定配置目录；B 站确认未登录或会话不可读时回退匿名，登录状态网络错误和视频权限失败不降级。YouTube 仍由原配置控制，B 站/抖音字幕另有默认关闭的显式开关。不导出 Cookie 文件。
- **完整性检查区分日常与验收。** 芒果检查完整 HLS 时长、结束标记及缺片，B 站核对分 P 和试看；两者交付前检查媒体轨道和容器时长。整段音视频解码用于验收脚本，不在每次日常下载中重复执行。
- **学习与下载隔离。** AI 只根据取得的字幕生成内容，密钥仅在后端使用。SQLite 保存学习记录，删除和清空对话防止迟到作业恢复已删除数据；学习存储初始化失败不阻塞原下载。
- **日志只记录可控信息。** yt-dlp 日志按错误类别输出，httpx 常规 URL 日志关闭，避免直接记录上游签名地址、Token 或凭据。
- **界面保持输入位置稳定。** 当前 PC 首页保留流程区和解析状态区域；成功后打开结果弹窗，关闭后可再次查看，帮助区采用普通布局替换。

## 6. 安装、运行与配置

项目现有运行说明要求 Python 3.10+、Node.js 22.12+。在项目根目录首次安装：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Push-Location frontend
npm.cmd ci
Pop-Location
```

个人本地运行（B 站/芒果会员或充电视频先在 Firefox 确认能完整播放；YouTube 使用所选浏览器）：

```powershell
.\start-local.ps1
# 可选参数：-Browser firefox|edge|chrome -Profile <profile> -Proxy <url> -Port <port>

# AI 学习：先在项目根目录 .env 配置 DEEPSEEK_API_KEY。
# 若要复用 Firefox 的 B 站/抖音字幕会话，显式启用：
.\start-local.ps1 -Port 8181 -UseFirefoxSubtitleSession
```

默认打开 `http://127.0.0.1:8000`；使用 8181 时打开对应端口。使用 `.env.example` 作为无密钥模板，真实密钥仅填本机 `.env`，不要写入示例或前端。也可通过 `-AskDeepSeekKey` 在终端隐藏输入；脚本退出时恢复其修改的进程环境。

已有服务先停止并重启以加载新代码；同一学习数据库仅运行一个服务实例。浏览器数据库被占用时检查对应浏览器及访问权限。直接用 `uvicorn` 启动同样会默认尝试 B 站/芒果 Firefox；YouTube 在未配置时不读取浏览器会话。

前后端分开开发的命令见 [README](README.md)。YouTube 登录、加密数据库、代理、EJS 和可选 Provider 排障见 [YouTube 配置与排障](YOUTUBE_SETUP.md)。

| 环境变量 | 作用 |
| --- | --- |
| `YTDLP_COOKIES_FROM_BROWSER` | 显式指定本机浏览器，可附 `:<profile>`；仅作用于 YouTube |
| `YTDLP_PROXY` | YouTube 专用 HTTP(S)/SOCKS 代理 |
| `YTDLP_NODE_PATH` | 指定 JavaScript runtime；默认尝试 PATH 中的 Node |
| `YTDLP_FFMPEG_LOCATION` | 指定 FFmpeg；默认优先系统版本，其次随包回退 |
| `YTDLP_POT_BASE_URL` | 可选 bgutil HTTP Provider；需独立运行服务并安装可选依赖，个人脚本会清除该设置 |
| `BILIBILI_USE_FIREFOX_SESSION` / `MGTV_USE_FIREFOX_SESSION` | 分别默认 `1`；设置 `0` 禁止该平台读取 Firefox |
| `BILIBILI_FIREFOX_PROFILE` / `MGTV_FIREFOX_PROFILE` | 分别指定下载用 Firefox 配置名或路径 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | 本机模型密钥与模型；当前代码默认 `deepseek-flash`，可配置 `deepseek-v4-pro` |
| `VIDEO_LEARNING_FIREFOX_SESSION` / `VIDEO_LEARNING_FIREFOX_PROFILE` | B 站/抖音字幕会话显式开关及 Firefox 配置；默认关闭 |
| `VIDEO_LEARNING_DB` | 学习数据库路径；默认 `backend/data/learning.sqlite3` |

`.env` 仅加载 AI/学习配置白名单，进程环境优先；下载变量不从 `.env` 读取。默认学习上限为 2 小时、120,000 字符、单字幕资源 5 MiB、模型请求 700 KiB，超限拒绝，不静默丢弃后半段。完整参数见 [README](README.md) 和 [AI 功能方案](AI_VIDEO_SUMMARY_PLAN.md)。

PO Token Provider 不是默认运行的必要组件；生成 Token 成功并不保证平台允许解析或下载。

## 7. 验收结果与证据边界

**当前交付的最近验证（2026-10-05）：**

| 检查 | 结果 |
| --- | --- |
| 后端 `pytest tests -q` | **186 passed**，退出码 0；原下载 80 项 + 学习 62 项 + 新平台 44 项，保留 1 条 Starlette/httpx 弃用提示 |
| 前端 `npm.cmd run build` | **通过**，包含 `vue-tsc -b` 类型检查和 Vite 生产构建 |
| B 站充电视频第 4 P HTTP 下载 | **通过**：2,502.67 秒、113,409,530 字节、852 × 480、H.264 + AAC；主地址失败后自动使用同格式备用 CDN |
| 芒果电影《流浪地球》HTTP 下载 | **通过**：7,503.12 秒、554,953,559 字节、832 × 348、H.264 + AAC |
| 芒果电视剧样例 HTTP 下载 | **通过**：1,822.05 秒、114,677,547 字节、832 × 348、H.264 + AAC |

三个新平台样例均选取标清，实际 API 完成解析、创建任务、`ready`、Range 206 和附件保存，再对整个音视频解码，退出码均为 0。更高清晰度已列出但未完整下载验收；样例成功不代表同平台全部内容可用。原始证据留在忽略的 `.local/`，可分发报告见 [适配接入验收](DOWNLOAD_ADAPTER_INTEGRATION.md)。

历史与独立阶段证据：

- [抖音验收](DOUYIN_TEST_REPORT.md)：多种链接真实解析；用户样例下载 43,204,005 字节，MP4 容器和 FFmpeg 音视频流读取检查通过；网页下载任务及文件 Range 响应通过。
- [YouTube 测试报告](YOUTUBE_TEST_REPORT.md)：2026-10-02 Firefox 登录态下下载 49,361,328 字节，合并后的整个文件音视频解码退出码为 0；匿名路径未通过登录验证。
- [前端验收](UI_REDESIGN_ACCEPTANCE.md)：记录桌面与窄屏布局、解析/下载/错误状态及后续 PC 弹窗与帮助切换检查。部分状态来自本机 UI 样例，不代表真实平台网络测试。
- [方案与阶段记录](DOWNLOAD_PLAN.md)：保留 Generic 视频下载、Bilibili 解析与早期实现过程。
- [B 站 Firefox 独立测试](BILIBILI_FIREFOX_TEST_REPORT.md)、[芒果开源调研与独立测试](MGTV_DOWNLOAD_RESEARCH.md)：保留接入前的方案依据与对照实验。
- [AI 学习验收](AI_VIDEO_SUMMARY_TEST_REPORT.md)：2026-10-04 的 13 项模拟浏览器流程、两条真实短视频生成和 8/8 问答核对；真实长视频效果与用户内容质量验收仍未完成。

版本阶段：2026-10-03 基线通过 80 项后端回归；2026-10-04 AI 扩展通过 142 项；2026-10-05 平台扩展通过 186 项。本次更新总结和提交没有重新调用付费模型，也不将历史浏览器检查表述为本次重新执行。

自动测试使用替身与 `MockTransport` 验证接口、会话隔离、格式映射、错误提示、非法跳转阻止、日志脱敏、MP4 结构/长度校验、残片清理和任务交付；不能代替真实平台持续可用性检查。

日常回归命令：

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Push-Location frontend
npm.cmd run build
Pop-Location
```

## 8. 生命周期与已知限制

- 任务默认从创建起 **2 小时**到期，状态仅存在当前进程；进程重启后旧任务不可查询。不适合直接启用多个 API worker 或多实例。
- 学习记录可持久化，与下载任务生命周期独立。学习任务重启中断后须人工重试；不自动重新发送可能计费的模型请求。
- 创建新任务时会清理内存表中已过期任务；查询状态/文件时检查并清理所查询的过期任务。没有独立定时清扫器；重启后遗留文件及部分失败任务目录需要另行管理。
- 封面 token 有效 **1 小时**，响应允许的图片类型和大小上限为 **8 MiB**，读取时校验重定向目标。尚未实现统一定期淘汰封面登记表。
- 抖音有单文件上限；其他来源尚未统一限制单任务大小、总磁盘占用、并发、速率和执行时长。`BackgroundTasks` 不是持久化队列，没有取消/重启恢复功能。
- 入口地址检查不能独立抵御 yt-dlp 内部请求的所有重定向或 DNS 重绑定；公开部署还需要出站网络隔离、认证、配额和限流。
- 文件扩展名和编码取决于来源格式与合并结果，不保证全部来源输出 MP4。抖音容器结构检查不等于完整解码。
- AI 依赖可获取的平台字幕，不包含语音转录或画面分析。抖音字幕访问受阻时按既定规则提示暂不能总结；模型引用校验不能单独证明知识点准确性。
- 会员/充电内容仅使用当前账号已有完整观看权限；不提供 DRM 或访问控制绕过。前端平台提示仍列出原三平台，芒果可直接粘贴链接使用后端适配。

## 9. Git 交付范围与维护建议

仓库采用 `main` 分支，纳入前后端源码、AI 学习与平台适配、测试和独立验收脚本、依赖清单/前端锁文件、启动脚本及项目文档。`.env.example` 只包含空密钥配置模板。

`.gitignore` 排除虚拟环境、Node 依赖、构建产物、视频下载目录、学习数据库、Python/pytest 缓存、`.local/` 本地备份与验证记录、根目录编辑器配置、日志及真实 `.env`。历史报告引用的 `.local/` 原始证据仍留在本机，不随仓库交付。

后续先完成用户人工验收和真实长视频知识覆盖检查，再处理定时清理、失败目录回收、磁盘/并发配额与下载任务持久化。语音转录、画面分析、批量下载或对外部署另行确认；公开部署前还需账号、密钥隔离、出站网络隔离、配额和限流。
