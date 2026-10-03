# 视频下载项目完成总结

整理日期：2026-10-03。项目名称：**save any**。本文以当前源码、本次回归检查及已有验收报告为依据，作为当前版本的交接入口；早期方案和界面演进记录继续保留在各专题文档中。

## 1. 完成情况

已完成个人本地使用的单视频下载闭环：**粘贴链接 → 解析信息 → 选择格式与保存方式 → 准备文件 → 保存到设备**。

前端提供响应式页面、结果弹窗、格式选择、任务进度和失败重试；后端负责地址检查、平台解析、音视频合并、下载任务与文件交付。可以在本机用一个 FastAPI 进程同时提供构建后的页面和 API，也可以在开发时分别启动 Vite 与 API。

当前版本定位为单实例、本地运行的应用。没有数据库、站内账号、支付、批量下载、字幕处理或 AI 总结功能。

## 2. 已实现功能与平台范围

| 功能 | 当前行为 |
| --- | --- |
| 链接解析 | 接受单视频公开 HTTP(S) 链接，返回标题、来源、封面、时长和可选格式 |
| 格式选择 | yt-dlp 来源提供最佳画质及最多 12 个选项（含最佳画质）；抖音提供原始 MP4 格式 |
| 音视频合并 | 分离视频轨使用 `video:<format_id>` 标识，下载时自动选择音频并由 FFmpeg 合并 |
| 下载方式 | 支持 `auto`、`server`、`redirect`；默认自动选择，平台可限制可用方式 |
| 状态与进度 | 后台下载、状态查询、已知大小时显示百分比、完成后显示“保存到设备” |
| 文件交付 | 服务端文件以附件响应返回；可用直链任务返回 302；文件响应支持 Range 请求 |
| 封面 | 使用登记 token 的同源封面接口，兼容来源站 Referer 要求 |
| 交互 | 剪贴板粘贴、解析等待、错误分类提示、重新解析/下载重试、结果弹窗关闭与再次打开 |
| 本地启动 | `start-local.ps1` 构建前端并启动仅监听 `127.0.0.1` 的 API |

| 平台 | 实现方式 | 支持范围与已记录的验证 |
| --- | --- | --- |
| 哔哩哔哩 | yt-dlp | 已记录真实解析、封面和分离轨清晰度选择；现有记录未提供完整媒体下载与解码验收结论 |
| YouTube | yt-dlp + EJS / Node，必要时使用显式选择的本机浏览器会话 | 已记录 Firefox 登录态下的服务层解析、下载、合并及完整音视频解码成功；该次没有完整网页 HTTP 端到端验收；同一测试环境匿名模式未通过登录验证 |
| 抖音 | 独立匿名分享页适配器 | 支持 `/video/<id>`、含 `modal_id` 的链接、短链接和移动分享页；已记录真实网页解析、下载、`ready` 状态、保存入口及 Range 响应 |
| 其他来源 | yt-dlp 提取器 | 已有 Generic 公开视频浏览器下载记录；具体站点是否可用取决于提取器、网络和来源限制 |

抖音只支持公开普通视频、自动/服务端交付，单文件上限 **1 GiB**；图集、直播、私密及已删除作品不在支持范围内。平台可用性会随上游页面和接口变化，既有样例成功不代表全部视频均可下载。

## 3. 架构与代码入口

前端：Vue 3、TypeScript、Vite、Tailwind CSS、Lucide 图标。

后端：FastAPI、Pydantic、yt-dlp、httpx、FFmpeg（系统安装或 `imageio-ffmpeg` 回退）。任务由 `BackgroundTasks` 执行，状态存储在带锁的进程内字典中。

```text
videoDownloader/
├─ frontend/
│  ├─ src/App.vue                 页面状态、解析请求和任务轮询
│  ├─ src/components/             输入、格式、下载、帮助及弹窗组件
│  ├─ src/types/video.ts          前端视频/任务类型
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
│  ├─ app/douyin.py               抖音分享页解析和 MP4 下载校验
│  ├─ tests/                     API、YouTube 与抖音测试及匿名探针
│  ├─ requirements.txt           必需依赖
│  └─ requirements-youtube.txt   可选 PO Token 插件依赖
├─ start-local.ps1               Windows 个人本地启动入口
├─ README.md                     安装、运行与文档导航
└─ PROJECT_SUMMARY.md            当前版本总结与交接入口
```

`frontend/dist/` 是可重新构建的产物，`backend/downloads/` 是运行时下载目录，均不进入版本控制。

## 4. 核心流程与接口

1. 前端发送解析请求；服务端校验协议、凭据和目标公网 IP。
2. 抖音链接进入专用模块，其他来源进入 yt-dlp；解析结果不包含上游媒体 URL 或 Cookie。
3. 用户选定格式和方式，服务端创建随机任务 ID，返回状态入口和文件入口。
4. 后台任务重新解析并下载，按来源执行直链选择、音频合并或 MP4 校验。
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

## 5. 关键实现决策与经验

- **平台适配集中在服务层。** 抖音通过分流接入现有 API 和任务流程，前端不需要新增一套下载协议。
- **格式值区分显示与执行。** “最佳画质”映射为 `bv*+ba/best`，分离视频轨映射为 `<format_id>+ba/best`；合并后的大小未知时不显示误导性估算。
- **交付方式由实际处理要求决定。** YouTube 和抖音使用服务端交付，显式选择直链会得到提示；其他来源仅在已解析目标为公网 HTTP(S)、无需额外请求头且不含多条合并轨时考虑直链。
- **抖音不依赖旧 iteminfo 接口。** 已有测试中该接口返回空内容；适配器使用移动分享页数据、有限重试和独立匿名访客会话，按作品编号精确匹配，不执行页面 JavaScript。
- **临时播放地址重新获取。** 抖音在下载时再次解析，避免沿用解析阶段已过期的媒体链接；下载检查 MIME、长度、大小上限和 MP4 顶层容器结构，失败清理残片并尝试候选地址。
- **本机会话按配置启用。** 普通后端默认不读取浏览器 Cookie；个人启动脚本默认显式选择 Firefox，仅将会话用于 YouTube，不导出 Cookie 文件。脚本退出时恢复相关进程环境设置。
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

个人本地运行（需要会话的 YouTube 视频先在所选浏览器登录）：

```powershell
.\start-local.ps1
# 可选参数：-Browser firefox|edge|chrome -Profile <profile> -Proxy <url> -Port <port>
```

打开 `http://127.0.0.1:8000`。浏览器数据库被占用时完全退出对应浏览器后重试；更改配置后需要重新启动 API。仅使用 `uvicorn` 启动时，未设置会话配置则保持不读取浏览器 Cookie 的行为。

前后端分开开发的命令见 [README](README.md)。YouTube 登录、加密数据库、代理、EJS 和可选 Provider 排障见 [YouTube 配置与排障](YOUTUBE_SETUP.md)。

| 环境变量 | 作用 |
| --- | --- |
| `YTDLP_COOKIES_FROM_BROWSER` | 显式指定本机浏览器，可附 `:<profile>`；仅作用于 YouTube |
| `YTDLP_PROXY` | YouTube 专用 HTTP(S)/SOCKS 代理 |
| `YTDLP_NODE_PATH` | 指定 JavaScript runtime；默认尝试 PATH 中的 Node |
| `YTDLP_FFMPEG_LOCATION` | 指定 FFmpeg；默认优先系统版本，其次随包回退 |
| `YTDLP_POT_BASE_URL` | 可选 bgutil HTTP Provider；需独立运行服务并安装可选依赖，个人脚本会清除该设置 |

PO Token Provider 不是默认运行的必要组件；生成 Token 成功并不保证平台允许解析或下载。

## 7. 验收结果与证据边界

**本次整理时实际执行（2026-10-03）：**

| 检查 | 结果 |
| --- | --- |
| 后端 `pytest tests -q`（临时目录位于 `.local/`） | **80 passed**，退出码 0；有 Starlette/httpx 弃用提示及现有 pytest 缓存目录写权限提示，共 2 条 warning |
| 前端 `npm.cmd run build` | **通过**，包含 `vue-tsc -b` 类型检查和 Vite 生产构建 |

已有真实网络与界面验收来自下列报告，本次没有重新向各平台下载完整视频：

- [抖音验收](DOUYIN_TEST_REPORT.md)：多种链接真实解析；用户样例下载 43,204,005 字节，MP4 容器和 FFmpeg 音视频流读取检查通过；网页下载任务及文件 Range 响应通过。
- [YouTube 测试报告](YOUTUBE_TEST_REPORT.md)：2026-10-02 Firefox 登录态下下载 49,361,328 字节，合并后的整个文件音视频解码退出码为 0；匿名路径未通过登录验证。
- [前端验收](UI_REDESIGN_ACCEPTANCE.md)：记录桌面与窄屏布局、解析/下载/错误状态及后续 PC 弹窗与帮助切换检查。部分状态来自本机 UI 样例，不代表真实平台网络测试。
- [方案与阶段记录](DOWNLOAD_PLAN.md)：保留 Generic 视频下载、Bilibili 解析与早期实现过程。

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
- 创建新任务时会清理内存表中已过期任务；查询状态/文件时检查并清理所查询的过期任务。没有独立定时清扫器；重启后遗留文件及部分失败任务目录需要另行管理。
- 封面 token 有效 **1 小时**，响应允许的图片类型和大小上限为 **8 MiB**，读取时校验重定向目标。尚未实现统一定期淘汰封面登记表。
- 抖音有单文件上限；其他来源尚未统一限制单任务大小、总磁盘占用、并发、速率和执行时长。`BackgroundTasks` 不是持久化队列，没有取消/重启恢复功能。
- 入口地址检查不能独立抵御 yt-dlp 内部请求的所有重定向或 DNS 重绑定；公开部署还需要出站网络隔离、认证、配额和限流。
- 文件扩展名和编码取决于来源格式与合并结果，不保证全部来源输出 MP4。抖音容器结构检查不等于完整解码。
- 仅处理用户拥有版权或已获授权的内容；不提供 DRM、付费墙或访问控制绕过。

## 9. Git 交付范围与维护建议

仓库采用 `main` 分支，纳入前后端源码、测试、依赖清单/前端锁文件、启动脚本及项目文档。

`.gitignore` 排除虚拟环境、Node 依赖、构建产物、视频下载目录、Python/pytest 缓存、`.local/` 本地备份与验证记录、根目录编辑器配置、日志及本地 `.env` 配置。历史报告引用的 `.local/` 原始证据仍留在本机，不随仓库交付。

后续优先处理定时清理和失败目录回收，再补磁盘/并发配额、任务取消与持久化。公开部署前完成出站网络隔离和访问控制；字幕、历史、账号等产品扩展在此之后按实际需求评估。
