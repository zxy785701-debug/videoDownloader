# 宝塔 B 站 HTTP 412 与 API 解析模式

更新日期：2026-10-10。公网对照视频为 `BV1N2pc6gErK`，真实网络验证仅获取元信息和播放信息，没有下载该视频、读取真实 Firefox Cookie、调用模型或支付。文件交付测试使用本地合成音视频。

## 已确认的事实

| 检查 | 结果 | 能说明什么 |
| --- | --- | --- |
| Windows 后端匿名解析 | 成功，5 个界面选项，时长 125.888 秒 | 同一链接在本地可匿名解析 |
| Windows 原始 yt-dlp 匿名解析 | 成功，15 个原始格式 | 原始格式经界面去重后数量不同，不能直接比较 |
| 宝塔 Python / yt-dlp | 3.11.17 / 2026.08.19 | yt-dlp 与本地版本一致 |
| 宝塔原始 yt-dlp，不读 Cookie | 下载视频网页时 HTTP 412 | 失败发生在网页提取阶段，尚未获取播放与字幕信息 |
| 宝塔 curl，正常 Referer | 视频页、view、nav 均为 HTTP 200 | 这些请求能建立连接；未据此验证页面正文、播放权限或文件下载 |
| 宝塔 yt-dlp，增加 Referer | 网页仍为 HTTP 412 | 单独补充来源页不能解决该样例 |
| 宝塔 yt-dlp，curl 客户端标识 | 跨过 412，随后报 `Unable to extract initial state` | HTTP 200 不代表收到解析器可用的完整视频页面 |
| 宝塔可用浏览器兼容客户端 | 均为 unavailable | 当时尚未安装 curl-cffi 可选网络库 |
| 宝塔安装 curl-cffi 0.16.0 后，Chrome 模式 | 网页仍为 HTTP 412 | 浏览器兼容模式未解决本次样例，没有据此增加默认请求模式 |
| 宝塔直接调用 view 与 yt-dlp 签名播放 helper | `metadata_code=0`，15 个原始格式，完整元信息 126 秒／播放 125.888 秒 | 服务器可以经 API 取得此样例完整时长的播放信息 |
| 修复后的 Windows 主服务 API 模式 | 5 个界面选项，125.888 秒；仅 view、nav、playurl 三个 API | 已用项目真实解析代码验证新路径，不访问视频网页 |

服务器没有正式域名不会直接造成此次错误。用户访问 SaveAny 的入口域名、网站证书，与后端向 `www.bilibili.com` 发出的请求是两条链路。这里的 412 来自视频平台，尚不能证明具体是整个服务器 IP 被封、请求特征检查、代理差异还是其他平台策略。

同时排查的 X 链接在宝塔原始 yt-dlp 中连接 `api.x.com:443` 超时，发生于获取 guest token 阶段，属于另一条网络问题；用户确认暂时没有服务器代理，先只修 B 站。芒果 TV 由用户确认可正常解析。不能据此断言全部 yt-dlp 平台都被这次代码改动破坏；本轮不改 X、芒果、抖音或 YouTube 的网络、Cookie 与解析策略，也不新增通用代理配置。

## 代码修复范围

- 增加 `BILIBILI_METADATA_SOURCE=api`：直接获取公开投稿元信息，复用 yt-dlp 当前 B 站提取器的 `_download_playinfo`、WBI 签名、格式解析和已选择 Cookie；不依赖视频网页 HTML。
- 解析、下载重新提取和 B 站字幕入口使用同一 API 模式；字幕仍要求真实可用权限，不用标题、弹幕或伪造内容代替字幕。
- 默认 `webpage`，保持原本地 Firefox 优先流程；API 模式在请求前明确选择，失败不会自动切换网页或重新以匿名会话尝试。
- 校验 API 返回的视频身份、指定分 P、完整时长、试看标记和可用格式；下载继续走 FFmpeg 音视频及完整时长校验和平台原备用 CDN，不降低用户选择的画质。
- 识别明确的 HTTP 412 状态，显示“平台拒绝当前请求”的指引，日志只记录 `upstream_blocked` 分类，不输出上游原始错误、Cookie 或签名链接。
- 识别 `Unable to extract initial state`，说明返回页面缺少解析所需信息，不再统一提示检查公开视频权限。
- 字幕遇到致命 412 时报告获取失败；只收到 412 警告且没有字幕时，同样不会误报“视频没有字幕”。
- 不改会员、模型、支付、下载接口或可信来源策略，不写入真实密钥或 Cookie。

此模式解决本次“网页拒绝、官方 API 可用”的已验证路径。若某视频的播放 API 也拒绝访问，仍应失败并说明原因；不承诺所有视频、字幕或媒体文件都能匿名访问。

## 宝塔配置与更新

代码提交、推送到 GitHub 不会自动部署服务器。用户确认发布后，服务器再拉取更新并重启原 8000 主服务；仅添加变量而不更新代码不会生效。本轮未执行远程部署或修改线上配置。

在 **8000 主服务进程环境变量**添加：

```dotenv
BILIBILI_METADATA_SOURCE=api
```

服务器没有 Firefox 时，继续保持原云端配置 `BILIBILI_USE_FIREFOX_SESSION=0`、`VIDEO_LEARNING_FIREFOX_SESSION=0`，不要上传个人 Cookie。芒果等已经工作的配置无需调整。B 站的新变量只读取**进程环境**，不是仅复制到项目根 `.env`。

如果宝塔通过自定义命令启动主服务，可在原命令前加环境变量，例如以下一行；项目工作目录和其他原有来源／会员环境变量保持原配置：

```bash
env BILIBILI_METADATA_SOURCE=api BILIBILI_USE_FIREFOX_SESSION=0 VIDEO_LEARNING_FIREFOX_SESSION=0 /www/server/pyporject_evn/videoDownloader-env/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

通过宝塔重启现有进程，避免另起一个占用 8000 的重复进程。无需修改 Nginx、重新构建前端或重启会员服务；两个后端继续绑定回环地址，Mock 会员服务不能暴露到公网。

本机无需改配置：默认 `webpage`，原 Firefox 会话方式继续工作；若希望本机也用 API，可设置同一变量为 `api`，仍可保留本机 Firefox 会话。回退到旧提取方式只需设为 `webpage` 并重启主服务。

## 支持范围与权限

- 本轮支持普通投稿的 BV／AV 直接视频链接，分 P 通过 `?p=N` 指定，默认第 1 P。
- 不扩展短链接、互动视频或番剧跳转；遇到互动／番剧跳转、仅有需特殊拼接的多段旧 FLV 格式时明确拒绝，不把部分内容当作完整视频。
- 未登录可用的清晰度由平台决定；API 模式不会解锁平台会员画质或付费内容。
- 云端无法读取访问者电脑的 Firefox Cookie；需要登录的字幕仍显示权限提示。本机字幕登录开关与下载开关保持独立。
- 无新依赖。复用的是当前已验证的 yt-dlp `2026.08.19` helper；升级 yt-dlp 时需重跑本报告的 API 回归，不能假设内部 helper 永远不变。[上游提取器源码](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py)。

## 请求客户端兼容性验证

yt-dlp 官方支持通过 `curl-cffi` 使用浏览器请求兼容模式，包含 TLS 特征处理；仅改变客户端标识并不等于使用该模式。[官方依赖说明](https://github.com/yt-dlp/yt-dlp#dependencies)、[官方网络选项](https://github.com/yt-dlp/yt-dlp#network-options)。

用户已在宝塔项目自己的虚拟环境安装当前 yt-dlp 的已锁定可选库 `curl-cffi==0.16.0`，对同一公开视频进行匿名、无下载的 Chrome 模式验证，结果仍为网页 HTTP 412。未将这个无效方案接入项目；仅安装该库也不会让 Python API 自动使用 Chrome 模式。

随后用户回传公开元信息与签名播放 API 的成功结果，15 个格式、125.888 秒与 126 秒完整元信息相符，因此实现了上述显式 API 模式。此证据支持本次路径修复，尚不代表媒体 CDN 文件和需要登录的字幕都允许云端访问。

本地与云端 Firefox 配置继续见 [双模式说明](LOCAL_CLOUD_COOKIE_MODES.md)。本地模式可继续使用当前电脑上的有效会话；云端无法直接读取访问者电脑的 Cookie。

## 验证状态

API 模式新增 28 项验证：真实 SDK 提取与 WBI 签名、匿名与已登录播放参数、默认网页模式保留、分 P、身份不符、试看与非法时长、无格式、旧分段格式拒绝、API 拒绝不重试、字幕权限、合成文件交付与 Range，以及真实 FFmpeg 音视频／时长检查。专项 28 项通过；此前 Cookie／字幕等 111 项组合回归也通过（后续又补充了签名和文件测试）。

最终完整后端 **468 项全部通过**，耗时 158.26 秒；保留一条既有 Starlette/httpx 弃用提示。相对上一版 434 项，新增 28 项 API 模式和 6 项错误分类／字幕失败检查。未改会员、支付、可信来源或其他平台的网络策略。

从项目根目录复跑：

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
```

人工验收：更新服务器后解析同一 BV 链接，确认显示封面、时长和格式；选画质下载完整文件并播放至结尾；尝试 `?p=N` 的真实多 P 视频；登录受限字幕应提示权限；本机 Firefox 原方式和芒果等已工作的链接继续正常。真实服务器的新版应用和媒体文件下载仍待部署后验收，本轮未执行远程部署。
