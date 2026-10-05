# YouTube 配置与排障

## 当前实现

解析与下载共享 YouTube 配置。自动模式使用服务端下载和 FFmpeg 合并，不再额外解析一次尝试直链；显式选择直链会提示改用自动或服务端。B 站保留原有流程。

YouTube 下载配置通过启动后端的进程环境读取，不从 `.env` 加载 `YTDLP_*`。新增 AI 学习配置可读取项目根目录 `.env`，与本节的下载配置分开。修改后重启后端。

| 环境变量 | 用途 | 默认行为 |
| --- | --- | --- |
| `YTDLP_PROXY` | YouTube 的 HTTP(S)/SOCKS 代理 | 不覆盖 yt-dlp 的系统代理发现 |
| `YTDLP_COOKIES_FROM_BROWSER` | 如 `firefox`、`edge:Default` | 不读取浏览器 Cookie |
| `YTDLP_NODE_PATH` | Node 可执行文件路径 | 从 PATH 查找 Node |
| `YTDLP_POT_BASE_URL` | bgutil HTTP 服务地址 | 不强制 mweb 客户端 |
| `YTDLP_FFMPEG_LOCATION` | FFmpeg 路径，所有平台共用 | 系统 FFmpeg 或 imageio 回退 |

Cookie、代理和 Token 客户端配置仅对 youtube.com 子域及 youtu.be 生效。Node 配置由所有提取器共用。

## 先处理登录验证

个人本地使用可在项目根目录运行 `./start-local.ps1`，默认读取 Firefox 会话并只监听 `127.0.0.1:8000`。先停止已占用 8000 端口的旧 API；脚本构建前端后，由同一进程提供页面和 API，直接打开该地址即可，无需另开 Vite。脚本不导出 Cookie，不更改全局环境变量。可用 `./start-local.ps1 -Browser edge` 切换浏览器，或通过 `-Profile` 指定浏览器配置目录、`-Proxy 'http://127.0.0.1:7890'` 指定代理。它会停用先前测试的强制 mweb/Provider 地址设置，以使用 yt-dlp 默认客户端。

Edge 必须能被 yt-dlp 正常读取；启动脚本不能解决数据库占用或 DPAPI 解密错误。遇到数据库占用时，保存工作并完全退出浏览器后再尝试。

本机匿名测试曾返回 `LOGIN_REQUIRED / Sign in to confirm you're not a bot`。Node 和 EJS 均已被识别，这不能靠安装 FFmpeg 解决。

先确认目标视频能在浏览器播放。仅在对应浏览器已有登录会话且希望使用时配置 Cookie；浏览器与后端使用同一 Windows 用户，尽量保持网络出口一致。

```powershell
# 按实际代理端口设置；不需要显式代理时省略。
$env:YTDLP_PROXY="http://127.0.0.1:7890"
# 仅当 Firefox 已登录且要使用其会话时设置。
$env:YTDLP_COOKIES_FROM_BROWSER="firefox"
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Edge/Chrome 数据库被占用时完全退出浏览器后重试；DPAPI 解密失败是另一类问题，关闭浏览器不保证解决，可使用本机可正常读取的 Firefox 会话。不要上传或提交 Cookie。

## 可选 PO Token 服务

仅在出现 Token 警告、格式缺失或相关 403 时启用。需要同时安装 Python 插件并运行服务；仅设置 URL 不会安装或启动服务。以下固定插件与服务均为 2.0.1，升级时一起验证。

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-youtube.txt
docker run --name video-downloader-pot -d --init -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider:2.0.1
$env:YTDLP_POT_BASE_URL="http://127.0.0.1:4416"
```

然后重启 API。此配置启用 `mweb`，并通过 `youtubepot-bgutilhttp.base_url` 传给插件。服务必须能访问其所需的上游；Docker 容器中的 localhost 与宿主机不同，不能把宿主机 127.0.0.1 代理地址直接当作容器代理。

没有 Docker 时，可按上游 README 克隆相同版本，在 server 目录执行 `npm ci`、`npx tsc`、`node build/main.js`，保留其默认本机监听地址。

Token 不保证解决登录验证、IP 限制或所有 403。停用项目的强制 mweb 配置可执行 `Remove-Item Env:YTDLP_POT_BASE_URL` 并重启；已安装插件仍可能被 yt-dlp 自动发现。

## 诊断与验收

服务日志只记录上游错误分类，不记录原始 Cookie、代理凭据和签名 URL：`login_required`、`cookie_decryption`、`cookie_database`、`js_challenge`、`po_token`、`network`、`forbidden`、`rate_limited`、`unavailable`、`formats` 或 `unknown`。前端使用已有错误提示展示具体操作建议。

匿名命令行诊断（仅解析，不读取浏览器会话）：

```powershell
backend/.venv/Scripts/python.exe -m yt_dlp --ignore-config --verbose --simulate --no-playlist --js-runtimes node "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
```

项目的 `YTDLP_*` 变量由 Python 服务读取，不会自动变成上述 CLI 参数。CLI 测试代理、Cookie 或 Provider 时需分别传 `--proxy`、`--cookies-from-browser`、`--extractor-args`。verbose 输出可能含网络配置，不应原样公开。插件列在日志中只证明已加载；实际生成 Token 还需看到上游文档所示生成记录。

验收：公开普通视频返回标题与清晰度 → 自动下载得到可播放且有音频的文件 → B 站解析与下载回归。单元测试模拟上游，不能替代真实会话与网络验收。

参考：[EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS)、[Cookie](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)、[PO Token](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)、[bgutil](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)。
