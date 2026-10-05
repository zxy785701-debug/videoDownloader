# save any

面向个人学习与获授权公开视频保存的 Web 原型。前端为 Vue 3 + TypeScript + Vite + Tailwind CSS，后端为 FastAPI；哔哩哔哩、YouTube 等使用 yt-dlp，抖音使用独立的公开分享页解析模块。

## B 站与芒果 TV 下载扩展

后端已接入 Firefox 会话与新平台适配。B 站默认优先使用 Firefox，并检查是否登录；未登录或无法读取会话时回退匿名流程。下载保留分 P，主 CDN 网络失败时自动尝试平台返回的同格式备用地址。芒果采用已验证的官网 pcweb 播放请求，列出清晰度并检查完整清单，可尝试保存当前账号有权完整观看的电影、电视剧等视频。

两平台使用自动/服务端方式下载，下载前检查是否仅有试看，文件完成后核对音视频轨道与时长。明确选择的画质不可用时提示重新解析，不静默替换；“最佳画质”仍自动选择当前可用格式。Cookie 和签名地址不发送到前端，也不导出文件。

在 Firefox 登录后，使用原启动命令并重启后端即可。可通过进程环境变量 `BILIBILI_USE_FIREFOX_SESSION=0` / `MGTV_USE_FIREFOX_SESSION=0` 分别禁用会话；`BILIBILI_FIREFOX_PROFILE` / `MGTV_FIREFOX_PROFILE` 可指定配置目录。这些变量不从 `.env` 读取，也不改变 YouTube 或 AI 字幕配置。实现与验收见 [后端适配接入报告](DOWNLOAD_ADAPTER_INTEGRATION.md)。

## AI 视频学习扩展

新增独立的 **AI 学习**工作区，也可从视频解析结果进入“获取字幕与 AI 总结”。学习功能与下载流程独立，下载适配扩展见上文。

- 视频摘要：中文总览、章节和核心知识点，引用可定位原字幕。
- 字幕原文：保留原语言与时间戳，支持搜索、分页、切换语言和导出 SRT。
- 思维导图：与摘要使用同一份内容，支持折叠、缩放、拖动与原文定位；窄屏使用树形列表。
- 视频问答：使用完整字幕回答，带原文引用；支持追问、历史保存及清空对话。
- 本机学习记录：SQLite 保存字幕、摘要、问答与中间结果，刷新/重启可恢复，支持手动删除及摘要 Markdown 导出。

支持尝试获取 B 站、抖音、YouTube 的平台字幕；**字幕可用才生成 AI 内容**。获取受阻或没有字幕时说明原因，仍可进入原下载流程。当前真实样例中 B 站与 YouTube 字幕成功，抖音字幕接口受访问限制；不能据此保证三平台所有视频均能总结。首版不含语音转录、画面分析或字幕导入。

DeepSeek 密钥只在本机后端使用。在项目根目录的 `.env` 填写 `DEEPSEEK_API_KEY` 后，运行：

```powershell
# 默认 8000；如果原下载服务正在运行，可用另一个空闲端口。
.\start-local.ps1 -Port 8181 -UseFirefoxSubtitleSession
```

打开 `http://127.0.0.1:8181` → **AI 学习**。也可不填 `.env`，而用 `-AskDeepSeekKey` 在终端隐藏输入。不要把密钥发到聊天、写入前端或填入 `.env.example`。没有密钥时仍可查看字幕；真实生成可能产生 DeepSeek 账户用量。仅运行一个学习服务实例；启动前先停止占用该端口的旧实例。

`-UseFirefoxSubtitleSession` 是用户批准的新增可选开关：仅 B 站/抖音字幕复用本机 Firefox 已登录会话，默认关闭；YouTube 继续使用 `-Browser` / `-Profile` 的原有设置。可用 `-SubtitleFirefoxProfile` 指定字幕用 Firefox 配置目录。平台可能在登录后仍拒绝字幕；不改变抖音独立下载通道，也不将 Cookie 发送给模型。

后端启动时读取项目根目录 `.env` 中的 **AI/学习配置**，进程环境变量优先；修改后重启后端。[.env.example](.env.example) 仅为无密钥参考，不自动读取，不要放真实密钥。下载配置仍只使用原有进程环境，不从 `.env` 读取 `YTDLP_*`；前端不读取本机密钥。默认模型 `deepseek-flash`、非思考模式，也可设置 `DEEPSEEK_MODEL=deepseek-v4-pro`。默认最长 2 小时、有效字幕 120,000 字符、字幕资源 5 MiB、模型请求 700 KiB；超限会拒绝，不静默截掉后半段。模型输出的结构和引用均经服务端校验，内容准确性仍须结合原文验收。

学习数据默认位于 `backend/data/learning.sqlite3`，可通过 `VIDEO_LEARNING_DB` 改路径；数据目录已忽略 Git。应用删除会删除相关记录，下载任务与文件不受影响。中断任务需人工重试，成功分段可复用；“重新生成”会产生新的模型请求。问答携带最近 5 轮成功对话帮助理解追问，并仍以字幕为依据。

## 抖音视频

支持抖音 `/video/编号`、带 `modal_id` 的精选/搜索页链接、`v.douyin.com` 短链接和 `iesdouyin.com` 移动分享页。直接粘贴视频链接，解析后使用默认的“自动选择”下载，再保存到设备。

无需登录抖音、导出 Cookie 或配置第三方解析服务。后端会自行接收分享页下发的匿名访客 Cookie（如 `ttwid`），只在本次解析会话内使用，不读取浏览器抖音登录态。旧 `iteminfo` 接口可能返回空内容，因此实际使用移动分享页里的作品数据。

目前支持公开的普通视频，输出 MP4；不支持图集、直播、私密或删除的作品。抖音使用自动/服务端下载，单文件上限 1 GiB。遇到分享页无数据或访问限制，会给出重试提示；不能保证平台接口变更后仍始终可用。下载时会重新解析播放地址，避免复用过期链接。

## 本地运行

### 个人本地版（已安装依赖）

在 Firefox 登录 YouTube 后，在项目根目录运行：

```powershell
.\start-local.ps1
```

打开 **http://127.0.0.1:8000** 即可使用。脚本会构建前端，并用一个进程提供页面和 API，默认使用 Firefox 本机会话；无需另开 Vite。关闭服务终端后，下次重新运行同一脚本即可。8000 端口若已被旧 API 占用，先停止旧 API。

下面保留首次安装和前后端分开运行的开发方式。

需要 Node.js 22.12+ 和 Python 3.10+（同时满足前端与 YouTube EJS 的运行要求）。依赖会安装 `imageio-ffmpeg` 作为 FFmpeg 回退；若系统 PATH 中已有 FFmpeg，则优先使用系统版本。也可通过 `YTDLP_FFMPEG_LOCATION` 指定可执行文件路径。

如果 YouTube 要求登录验证，只有在本机浏览器已登录且你明确选择后，才在启动后端的 PowerShell 终端设置 `YTDLP_COOKIES_FROM_BROWSER`，例如 `$env:YTDLP_COOKIES_FROM_BROWSER="edge"`，然后重启 API。读取时须完全退出该浏览器（包括后台进程）。Cookie 不会写入项目文件或上传；不要把浏览器 Cookie 导出后发送给他人。

首次创建 Python 环境并安装依赖：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

终端一，在仓库根目录启动 API：

```powershell
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload --reload-dir backend/app --port 8000
```

终端二，启动前端：

```powershell
cd frontend
npm install
npm run dev
```

打开 Vite 输出的本地地址。API 文档位于 `http://127.0.0.1:8000/docs`。

## 检查

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
cd frontend
npm run build
```

## 文档

- [项目完成总结](PROJECT_SUMMARY.md)：当前功能、实现决策、验收证据与后续维护入口
- [B 站与芒果后端适配接入](DOWNLOAD_ADAPTER_INTEGRATION.md)：Firefox 优先、备用 CDN、清晰度、完整文件校验及真实 HTTP 验收
- [AI 视频总结竞品调研](AI_VIDEO_SUMMARY_COMPETITOR_RESEARCH.md)：BibiGPT、NoteGPT 对比与扩展依据
- [AI 视频学习功能方案](AI_VIDEO_SUMMARY_PLAN.md)：已批准并实施的需求、架构、处理上限与验收标准
- [AI 视频学习测试与验收报告](AI_VIDEO_SUMMARY_TEST_REPORT.md)：自动测试、真实字幕/模型结果和人工验收项
- [需求分析](REQUIREMENTS.md)
- [方案设计与阶段记录](DOWNLOAD_PLAN.md)
- [YouTube 配置与排障](YOUTUBE_SETUP.md)
- [YouTube 测试报告](YOUTUBE_TEST_REPORT.md)
- [抖音解析与下载验收](DOUYIN_TEST_REPORT.md)
- [前端改版验收](UI_REDESIGN_ACCEPTANCE.md)

## 使用边界

只处理公开 HTTP(S) 链接。请确保自己拥有版权或已获得授权，并遵守平台条款。个人本机模式下 B 站与芒果默认尝试 Firefox，会话可独立禁用；受限内容须由当前账号已有观看权限。项目不处理 DRM、播放列表或访问控制绕过，不保证所有站点始终可用。
