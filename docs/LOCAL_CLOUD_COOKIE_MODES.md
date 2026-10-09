# 本地 Firefox 与云端匿名双模式

更新日期：2026-10-09。无需切换源码或增加浏览器 Cookie 上传接口，同一份项目可分别在 Windows 本机、Ubuntu／宝塔服务器运行。

## 运行方式

| 场景 | 视频下载 | B 站／抖音字幕 |
| --- | --- | --- |
| Windows 本机后端 | B 站、芒果默认优先读取同一台电脑上 Firefox 的会话；无可用登录态时匿名 | 显式开启字幕专用 Firefox 会话后读取本机登录态；不可读取时尝试匿名 |
| 宝塔云端后端 | 建议关闭服务器浏览器读取，直接匿名；未关闭且服务器没有可用 Firefox 配置时，也能回退匿名 | 默认匿名；要求登录的字幕返回明确权限提示，下载可独立尝试 |

Firefox 会话永远来自**运行 Python 后端的设备和操作系统用户**。在自己的 Firefox 登录 B 站，再用 HTTPS 或 SSH 隧道访问云端网站，并不会让云服务器得到自己电脑的 B 站 Cookie。SaveAny 账号／会员的 Cookie 也不是 B 站登录 Cookie。[yt-dlp 官方浏览器 Cookie 说明](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)描述的是运行 yt-dlp 的机器上的配置读取。

不保证所有公开视频都可匿名下载；平台仍可能要求登录、限制云服务器网络出口或清晰度。需要登录的 B 站字幕、充电视频和会员资源仍由平台权限决定。匿名回退不会自动获得登录权限，也不会绕过付费、试看或 DRM 限制。

## 本次故障与修复

截图错误不是 HTTPS 证书或 Nginx 来源校验报错，而是读取 Firefox 配置失败。

项目当前 yt-dlp 版本为 `2026.08.19`：读取 Cookie 失败先生成 `CookieLoadError`，`YoutubeDL.cookiejar` 报告错误时又可能将其包装为 `DownloadError`。原平台适配只捕获第一种类型，因此“没有 Firefox 时匿名”的分支未执行。原测试仅模拟直接抛出 `CookieLoadError`，没有覆盖真实包装流程。

修复如下：

1. 检查异常链中的真实 Cookie 异常类型，不按错误文案模糊判断，也不吞掉所有下载异常。
2. 仅在会话准备阶段回退；关闭失败客户端后创建不带浏览器会话的匿名客户端。
3. 字幕专用 Firefox 同样提前加载 Cookie，在配置不可读取时回退匿名；保留默认关闭的明确开关。
4. 提取／下载已经开始后，不因权限、网络、试看或其他业务失败重试匿名，保留原清晰度与完整性检查。
5. 明确区分“没有字幕”和“字幕需要登录”，移除云端报错中只适用于 Windows 的 PowerShell 指引。

YouTube 明确选择的登录会话不被静默取消，抖音原匿名下载通道不变；本次不改变会员、额度、支付或来源校验策略。Cookie 不写入响应、模型请求、日志或导出文件，测试仅使用合成 Cookie。

## Windows 本机使用

用启动后端的同一 Windows 用户打开 Firefox，登录 B 站并确认该视频和字幕在网页可用。然后在项目根目录启动：

```powershell
# B 站／芒果默认已经是 1；这里明确覆盖可能残留的禁用配置。
$env:BILIBILI_USE_FIREFOX_SESSION = '1'
$env:MGTV_USE_FIREFOX_SESSION = '1'
.\start-local.ps1 -UseFirefoxSubtitleSession
```

浏览器访问 `http://127.0.0.1:8000`。B 站／芒果下载与字幕开关独立，字幕需要 `-UseFirefoxSubtitleSession`；YouTube 沿用脚本的 `-Browser`／`-Profile` 配置。可用 `-SubtitleFirefoxProfile` 指定字幕专用 Firefox 配置。

`BILIBILI_FIREFOX_PROFILE`／`MGTV_FIREFOX_PROFILE` 是下载用的可选进程变量，`VIDEO_LEARNING_FIREFOX_PROFILE` 是字幕用配置；都应指向后端所在机器，不能将 Windows 路径复制到 Ubuntu。

无需导出 Cookie，更不必上传 Cookie 到云端或发到聊天中。只能下载当前账号本来有权访问的内容。

## 宝塔云服务器配置

在宝塔的 **8000 主服务进程环境变量**中设置：

```dotenv
BILIBILI_USE_FIREFOX_SESSION=0
MGTV_USE_FIREFOX_SESSION=0
VIDEO_LEARNING_FIREFOX_SESSION=0
YTDLP_COOKIES_FROM_BROWSER=
```

`BILIBILI_*`、`MGTV_*` 和 `YTDLP_*` 沿用已有约定，只从**进程环境**读取；不要仅将它们放入仓库根 `.env` 后期待生效。`VIDEO_LEARNING_FIREFOX_SESSION` 支持根 `.env`，但进程环境优先。使用进程管理器／systemd EnvironmentFile 时同理，将上述值交给现有主服务进程，然后重启该进程。

此配置避免服务器尝试读取不存在的 Firefox。若继续使用默认的自动探测，本次修复也会处理真实 Cookie 读取失败并回退匿名。

来源与 HTTPS Cookie 配置继续按 [可信来源部署说明](ORIGIN_PROXY_DEPLOYMENT.md)执行，不能用关闭来源校验解决 Cookie 读取问题。主服务、会员服务继续绑定 `127.0.0.1`，Mock 支付服务不能反代到公网。本次无需修改 Nginx、重建前端或重启会员服务。

不建议给公网服务共用运营者的个人 B 站会话。若以后要为每位云端用户提供自己的平台登录授权，需要另行设计本地伴随程序／平台授权流程及用户隔离；本轮没有增加或默认开启这种共享能力。

## 验收方法

提交、推送代码不会自动修改宝塔配置或部署服务器。服务器部署由用户确认后另行执行；更新到本版代码、设置上述进程变量后，通过宝塔重启现有 8000 服务。

1. 云端解析一个确认可以匿名播放的公开视频，应取得元信息并可尝试下载，不再因缺失 Firefox 配置直接退出。
2. 同时获取字幕：若平台要求登录，显示字幕权限提示；不阻断视频信息和下载，不把权限失败标记为成功摘要。
3. 本机在 Firefox 登录后启动上述命令，验证登录态可用的清晰度、视频及字幕仍能获取。
4. 暂时移除／禁用 Firefox 配置，确认走匿名；恢复后确认能继续使用本机登录态。

若匿名请求仍被平台 403／412、风控或网络限制拒绝，应检查服务器网络和平台返回类别；不能据此认定仍是 Firefox 回退问题。不要打印或分享原始 Cookie、带签名的媒体地址或个人配置路径。

## 自动验证记录

新增测试用当前安装的真实 yt-dlp Cookie 包装流程、模拟读取失败和合成会话验证双模式，不触碰真实 Firefox Cookie，也不访问平台、模型或 Stripe：

- 配置缺失、权限错误的真实异常包装及匿名回退，日志不含原始路径或 Cookie。
- B 站／芒果可用 Firefox 会话继续被选择，解析与下载 API 可在缺失 Firefox 时完成模拟完整文件下载。
- 字幕配置缺失时回退，可用会话保留，服务器关闭开关时不读取浏览器，失败客户端与匿名客户端都被关闭。
- 无字幕与登录受限分开报告；提取后的业务错误不触发匿名重试；YouTube 明确配置保持原行为。

新增 24 项双模式回归，完整后端 **434 项全部通过**，耗时 97.89 秒；保留一条既有 Starlette/httpx 弃用提示，没有新增依赖或修改会员业务代码。首次完整运行发现既有会员预留过期测试依赖当前时间，在夜间推进两小时会跨北京时间零点；已仅固定该测试的时钟，独立跨日规则测试继续通过。

从仓库根目录复跑：

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
```

阿里云实际平台访问和用户本机真实登录态仍待人工验收，自动模拟通过不代表所有视频都会成功。
