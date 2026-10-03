# save any

面向个人学习与获授权公开视频保存的 Web 原型。前端为 Vue 3 + TypeScript + Vite + Tailwind CSS，后端为 FastAPI；哔哩哔哩、YouTube 等使用 yt-dlp，抖音使用独立的公开分享页解析模块。

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
- [需求分析](REQUIREMENTS.md)
- [方案设计与阶段记录](DOWNLOAD_PLAN.md)
- [YouTube 配置与排障](YOUTUBE_SETUP.md)
- [YouTube 测试报告](YOUTUBE_TEST_REPORT.md)
- [抖音解析与下载验收](DOUYIN_TEST_REPORT.md)
- [前端改版验收](UI_REDESIGN_ACCEPTANCE.md)

## 使用边界

只处理公开 HTTP(S) 链接。请确保自己拥有版权或已获得授权，并遵守平台条款。支持显式配置后读取本机浏览器会话；不处理 DRM、付费墙、播放列表和访问控制绕过，不保证所有站点始终可用。
