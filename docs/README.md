# save any

面向个人学习与获授权公开视频保存的 Web 原型。前端为 Vue 3 + TypeScript + Vite + Tailwind CSS，后端为 FastAPI；哔哩哔哩、YouTube 等使用 yt-dlp，抖音使用独立的公开分享页解析模块。

## 中英文公开站点与 SEO

本机启动方式和工作区保持原样，新增 `/zh/`、`/en/` 公开介绍及视频下载、AI 总结、字幕下载教程。正文为静态 HTML，不读取本机学习记录；无正式域名时默认不收录。独立公开构建命令为 `npm.cmd run build:site --prefix frontend`，输出 `frontend/site-dist/`，部署无需开放本机 API。

正式域名、语言关联、站点地图和站长验证配置见 [SEO 配置与发布](SEO_SETUP.md)，现状分析见 [SEO 审计](SEO_PLAN_AND_AUDIT.md)，自动检查和人工验收入口见 [SEO 测试报告](SEO_TEST_REPORT.md)。网站尚未上线，尚未验证真实搜索收录或排名。
最新 TDK 与外链计划见 [SEO 完善](SEO_REFINEMENT.md)。公开页及同源 Markdown 的 AI 阅读能力、九个平台的抓取策略和 Google-Extended 用户选择见 [GEO 方案](GEO_PLAN_AND_SETUP.md)；本轮验证与上线后效果记录分别见 [联合测试](SEO_GEO_TEST_REPORT.md) 和 [GEO 评估](GEO_EVALUATION.md)。

## B 站与芒果 TV 下载扩展

后端已接入 Firefox 会话与新平台适配。B 站默认优先使用 Firefox，并检查是否登录；未登录或无法读取会话时回退匿名流程。下载保留分 P，主 CDN 网络失败时自动尝试平台返回的同格式备用地址。芒果采用已验证的官网 pcweb 播放请求，列出清晰度并检查完整清单，可尝试保存当前账号有权完整观看的电影、电视剧等视频。

2026-10-09 修复了 yt-dlp 包装 Cookie 读取异常导致匿名回退未执行的问题。本机继续优先 Firefox；宝塔服务器可关闭浏览器读取而使用匿名。云端不能直接使用访问者电脑的 Cookie，需要登录的字幕可能仍不可用。两种运行方式的具体配置和验收见 [本地／云端 Cookie 双模式](LOCAL_CLOUD_COOKIE_MODES.md)。

两平台使用自动/服务端方式下载，下载前检查是否仅有试看，文件完成后核对音视频轨道与时长。明确选择的画质不可用时提示重新解析，不静默替换；“最佳画质”仍自动选择当前可用格式。Cookie 和签名地址不发送到前端，也不导出文件。

在 Firefox 登录后，使用原启动命令并重启后端即可。可通过进程环境变量 `BILIBILI_USE_FIREFOX_SESSION=0` / `MGTV_USE_FIREFOX_SESSION=0` 分别禁用会话；`BILIBILI_FIREFOX_PROFILE` / `MGTV_FIREFOX_PROFILE` 可指定配置目录。这些变量不从 `.env` 读取，也不改变 YouTube 或 AI 字幕配置。实现与验收见 [后端适配接入报告](DOWNLOAD_ADAPTER_INTEGRATION.md)。

## AI 视频学习扩展

2026-10-10 新增云端 ASR 字幕兜底：原生字幕优先，不可用时通过私有 OSS 与北京 Paraformer-v2 转录，再复用现有总结。ASR 默认单视频 60 分钟、并发 1、应用月预算 10 元；原生字幕时长与现有下载保持兼容。百炼 Key 必须配置到 Python 进程环境，不能填到前端。配置、成本限制与宝塔部署步骤见 [ASR 部署说明](ASR_FALLBACK.md)，本地验证与真实调用边界见 [ASR 测试报告](ASR_TEST_REPORT.md)。

同日指定 B 站视频的真实登录/匿名两组验收通过：原生字幕 45 条时不调用 ASR；匿名字幕权限失败后真实转录 11 条，并完成总结、问答、导图及导出。旧账本保留，未部署生产。耗时、内存、费用估算及覆盖边界见 [B 站端到端报告](BILIBILI_ASR_E2E_REPORT.md)。

视频信息／下载与 AI 学习已整合到同一页面：桌面左侧查看视频信息并下载，右侧查看摘要、字幕、导图和问答，窄屏上下排列。点击“解析视频”后自动获取字幕，默认接续总结；开关可关闭并记住选择。下载无需等待总结，学习记录从右上角按需打开。

- 视频摘要：SSE 逐步显示分段/汇总草稿，进入下一阶段或修复时保留此前文本并标注状态，全部校验成功后保存中文总览、章节和核心知识点；引用可定位原字幕，刷新/断线后可接回后台任务。
- 字幕原文：保留原语言与时间戳，支持搜索、分页和切换语言；在字幕页选择 SRT 或带时间戳 TXT，点击“下载字幕”保存全部原文，无需生成摘要或配置模型。
- 思维导图：与摘要使用同一份内容，保留向右展开，节点宽高按内容调整，间距更紧凑；支持折叠、拖动与原文定位，滚轮上下移动、Shift＋滚轮横向移动、Ctrl＋滚轮以鼠标位置缩放；支持全屏阅读、完整高清 PNG 和 SVG 下载，窄屏保留树形列表。
- 视频问答：使用完整字幕进行 SSE 流式回答，生成中标明引用尚未校验，完成后校验引用并保存；支持刷新/断线接回后台任务、追问、历史保存及清空对话。
- 本机学习记录：SQLite 保存字幕、摘要、问答与中间结果，刷新/重启可恢复，支持手动删除及摘要 Markdown 导出。

图片下载包含所有分支与完整文字，不受当前折叠或缩放影响。PNG 优先 3 倍、较大图使用 2 倍，界面显示实际像素；超出安全图片尺寸时提示下载完整 SVG。字幕下载包含当前语言的全部字幕，不受搜索和分页影响。已保存摘要直接复用，刷新、历史恢复和语言切换不自动产生新模型调用；自动接续失败或服务重启后需手动重试；更新代码后请重启旧后端再验收。

支持优先获取 B 站、抖音、YouTube 的平台字幕；启用并配置云端 ASR 后，原生字幕不可用时尝试语音转录，再生成 AI 内容。获取及转录受阻时说明原因，同屏的视频下载仍可使用。当前真实验收覆盖指定 B 站视频的原生字幕和 ASR；不能据此保证三平台所有视频均能总结。尚不包含画面分析或字幕导入。

自动总结在提交解析时固定开关选择，字幕成功后由后台接续；关闭网页不取消已提交链路，服务进程停止则需手动重试。“重新生成”会产生新用量。详见 [同屏方案](UNIFIED_VIDEO_WORKSPACE_PLAN.md) 和 [验收报告](UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md)。

DeepSeek 密钥只在本机后端使用。在项目根目录的 `.env` 填写 `DEEPSEEK_API_KEY` 后，运行：

```powershell
# 默认 8000；如果原下载服务正在运行，可用另一个空闲端口。
.\start-local.ps1 -Port 8181 -UseFirefoxSubtitleSession
```

打开 `http://127.0.0.1:8181`，粘贴链接并点击 **解析视频**。也可不填 `.env`，而用 `-AskDeepSeekKey` 在终端隐藏输入。不要把密钥发到聊天、写入前端或填入 `.env.example`。没有密钥时仍可查看字幕；真实生成可能产生 DeepSeek 账户用量。仅运行一个学习服务实例；启动前先停止占用该端口的旧实例。

`-UseFirefoxSubtitleSession` 是用户批准的新增可选开关：仅 B 站/抖音字幕复用本机 Firefox 已登录会话，默认关闭；YouTube 继续使用 `-Browser` / `-Profile` 的原有设置。可用 `-SubtitleFirefoxProfile` 指定字幕用 Firefox 配置目录。平台可能在登录后仍拒绝字幕；不改变抖音独立下载通道，也不将 Cookie 发送给模型。

后端启动时读取项目根目录 `.env` 中的 **AI/学习配置**，进程环境变量优先；修改后重启后端。[.env.example](../.env.example) 仅为无密钥参考，不自动读取，不要放真实密钥。下载配置仍只使用原有进程环境，不从 `.env` 读取 `YTDLP_*`；前端不读取本机密钥。默认模型 `deepseek-flash`、非思考模式，也可设置 `DEEPSEEK_MODEL=deepseek-v4-pro`。默认最长 2 小时、有效字幕 120,000 字符、字幕资源 5 MiB、模型请求 700 KiB；超限会拒绝，不静默截掉后半段。模型输出的结构和引用均经服务端校验，内容准确性仍须结合原文验收。

学习数据默认位于 `backend/data/learning.sqlite3`，可通过 `VIDEO_LEARNING_DB` 改路径；数据目录已忽略 Git。应用删除会删除相关记录，下载任务与文件不受影响。中断任务需人工重试，成功分段可复用；“重新生成”会产生新的模型请求。问答携带最近 5 轮成功对话帮助理解追问，并仍以字幕为依据。

问答刷新或切换页面后可接回同一后台任务，不重复调用模型；短暂断流会自动恢复订阅。只有校验通过的完整回答作为正式历史保存。服务进程重启会中断未完成任务，需手动重试；引用校验修复沿用最多一次的原有规则，修复可能产生额外用量。详见 [流式问答方案](AI_QA_SSE_PLAN.md) 和 [测试报告](AI_QA_SSE_TEST_REPORT.md)。

摘要也使用 SSE，长视频按分段与汇总阶段保留草稿；修复前版本标注未通过校验，完成后更新正式摘要与导图，重新生成失败时保留上次成功的摘要。初始输出额度为 4,096 tokens，明确达到长度上限时最多一次修复并提高到 8,192。已校验分段可以复用，模型断流不自动重新计费调用。详见 [摘要 SSE 方案与验收报告](AI_SUMMARY_SSE_TEST_REPORT.md) 与 [摘要撤回修复报告](SUMMARY_STREAM_RESET_FIX.md)。

已补充旧版摘要 SSE 的草稿保留；文本前缀变化不再被猜测为模型修复，实际修复由后端报告原因。模型多返回的元数据不会触发整段重写，正文和引用校验继续保留；完成时优先接收正式摘要，防止并行读取留下空页面。前端会识别尚未重启的旧后端并阻止付费生成。2026-10-06 已更新本机 8000 端口服务，用户样例的八章真实摘要已保存，Ctrl＋F5 后可直接查看。见 [完整真实复测](SUMMARY_STREAM_REAL_VERIFICATION.md)。其他部署更新后仍需重启后端。

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

- [文档导航](INDEX.md)：当前说明与历史阶段的阅读顺序
- [同屏工作区方案](UNIFIED_VIDEO_WORKSPACE_PLAN.md)、[开发验收报告](UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md)：解析后的自动接续、去重与同屏状态规则
- [回归执行说明](TESTING.md)：单元回归、浏览器 fixture 和真实调用探针的区别
- [项目完成总结](PROJECT_SUMMARY.md)：当前功能、实现决策、验收证据与后续维护入口
- [B 站与芒果后端适配接入](DOWNLOAD_ADAPTER_INTEGRATION.md)：Firefox 优先、备用 CDN、清晰度、完整文件校验及真实 HTTP 验收
- [AI 视频总结竞品调研](AI_VIDEO_SUMMARY_COMPETITOR_RESEARCH.md)：BibiGPT、NoteGPT 对比与扩展依据
- [AI 视频学习功能方案](AI_VIDEO_SUMMARY_PLAN.md)：已批准并实施的需求、架构、处理上限与验收标准
- [AI 视频学习测试与验收报告](AI_VIDEO_SUMMARY_TEST_REPORT.md)：自动测试、真实字幕/模型结果和人工验收项
- [视频问答 SSE 方案](AI_QA_SSE_PLAN.md)：后台生成、草稿、最终引用校验、断线/刷新恢复及失败行为
- [视频问答 SSE 验收报告](AI_QA_SSE_TEST_REPORT.md)：215 项后端回归、44 项前端自动检查与真实调用状态
- [摘要 SSE 方案与验收报告](AI_SUMMARY_SSE_TEST_REPORT.md)：238 项后端、58 项浏览器回归及 6 项状态检查，含分段/汇总、重连、修复和旧摘要保留
- [摘要真实复测](SUMMARY_STREAM_REAL_VERIFICATION.md)：两轮官方 API 生成、草稿保留观察、实际服务更新与原记录恢复
- [摘要撤回修复报告](SUMMARY_STREAM_RESET_FIX.md)：用户长视频的截断原因、输出额度调整、草稿保留和字幕副本回放结果
- [导图与字幕下载扩展方案](MINDMAP_SUBTITLE_ENHANCEMENT_PLAN.md)：本次竞品调研、源码分析及用户确认的方案
- [导图与字幕下载验收报告](MINDMAP_SUBTITLE_ENHANCEMENT_TEST_REPORT.md)：194 项后端、33 项浏览器回归和 4 条已有学习记录的复核结果，含自适应样式前后尺寸对比
- [需求分析](REQUIREMENTS.md)
- [方案设计与阶段记录](DOWNLOAD_PLAN.md)
- [YouTube 配置与排障](YOUTUBE_SETUP.md)
- [YouTube 测试报告](YOUTUBE_TEST_REPORT.md)
- [抖音解析与下载验收](DOUYIN_TEST_REPORT.md)
- [前端改版验收](UI_REDESIGN_ACCEPTANCE.md)

## 使用边界

只处理公开 HTTP(S) 链接。请确保自己拥有版权或已获得授权，并遵守平台条款。个人本机模式下 B 站与芒果默认尝试 Firefox，会话可独立禁用；受限内容须由当前账号已有观看权限。项目不处理 DRM、播放列表或访问控制绕过，不保证所有站点始终可用。
