# YouTube 匿名下载测试报告

## 后续个人登录态测试：成功

2026-10-02，用户在 Firefox 登录并授权读取后，保持当前网络环境，原版 yt-dlp CLI 成功列出 Big Buck Bunny 的 144p–2160p 格式。随后使用项目的 `parse_video` 和 `process_download`，以 `video:134`（360p 视频 + 自动选择音频）、`auto` 模式完成服务端下载。

- 文件：`backend/downloads/youtube-firefox-validation/Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film [aqz-KE-bpKQ].mp4`。
- 文件大小：49,361,328 字节。
- FFmpeg 显式选择视频轨和音频轨，对整个文件解码检查，退出码 0。
- 未导出或保存 Cookie；未设置强制 mweb/Provider 地址，未启动独立 Token 服务。
- 结果记录：`.local/youtube-tests/firefox-download.json`。
- `start-local.ps1` 默认浏览器已改为 Firefox。正在运行的旧 API 不会自动继承此设置，需停止旧进程并使用脚本重新启动。

**个人本地路径已验证成功；下文匿名模式失败结论仍然有效。** 本次验证直接调用项目服务层，未执行浏览器点击下载或完整 HTTP 端到端验收。

测试日期：2026-10-02。本次未读取或导入任何账号 Cookie，也未使用公共账号。

## 结论

**当前出口下匿名下载未通过。** Provider 可以正常生成 PO Token，但 YouTube 在返回格式清单之前要求登录。补充 GVS Token 未解决这个上游响应，因而未得到媒体文件，音视频合并验收没有执行条件。

这说明当前配置和出口的组合未成功，不证明所有部署环境均不可行，也不能仅凭本次结果确定一定是 IP 限制。

## 环境

- Windows、Python 3.13.9、Node 24.14.1。
- yt-dlp 2026.8.19、yt-dlp-ejs 0.8.0。
- 新安装 Python 插件 bgutil-ytdlp-pot-provider 2.0.1。
- Provider 源码：`.local/bgutil-ytdlp-pot-provider`，上游 2.0.1 标签，提交 `2df09aeaa71a4eec1e31901e84fbddbf0c7c54a9`。
- 本机未提供 Docker，因此使用 Node 构建运行；Canvas 预编译依赖通过本机代理下载后构建成功。
- Provider 仅监听 `127.0.0.1:4416`；测试后停止。
- 解析、Token 生成使用本机 HTTP 代理 `127.0.0.1:7890`。未修改代理节点、系统代理或全局环境变量。

## 结果

| 测试 | 结果 | 证据文件（相对项目目录） |
| --- | --- | --- |
| Provider `/ping` | 成功，版本 2.0.1 | 测试命令输出 |
| Provider `/get_pot` | 成功，返回非空 Token（120 字符）；未保存 Token 内容 | `.local/youtube-tests/provider-generation.json` |
| Big Buck Bunny，mweb | 插件已加载；LOGIN_REQUIRED；未触发自动 Token 生成 | `.local/youtube-tests/mweb.json` |
| 同视频，mweb/tv/web_safari | 三个客户端均 LOGIN_REQUIRED | `.local/youtube-tests/multi-client.json` |
| 同视频，显式提供 mweb.gvs Token 并请求下载 | Token 已生成并传入；仍 LOGIN_REQUIRED，无媒体文件 | `.local/youtube-tests/explicit-token-download.json` |
| 第二个公开视频 jNQXAC9IVRw，三个客户端 | 三个客户端均 LOGIN_REQUIRED | `.local/youtube-tests/second-video.json` |
| 无代理直连 YouTube robots.txt | 连接失败，URLError | `.local/youtube-tests/direct-network.json` |
| B 站 BV1nPaE6NE4g 真实解析 | 成功，返回 5 个选项（含最佳画质） | `.local/youtube-tests/bilibili-regression.json` |
| 后端回归 | 30 passed；一个现有 Starlette/httpx 弃用警告 | pytest 输出 |

PO Token 返回非空只证明生成服务成功，不证明 YouTube 接受该 Token；本次失败发生在取得媒体 URL 之前。未宣称完成 YouTube 下载或音视频验证。B 站仅做真实解析回归，没有重复下载已有视频。

## 复现

在项目根目录的一个终端启动 Provider：

```powershell
Push-Location .local/bgutil-ytdlp-pot-provider/server
node build/main.js --host 127.0.0.1 --port 4416
```

另一个终端运行匿名探针（脚本显式禁用账号 Cookie，不保存上游签名 URL 或 Token）：

```powershell
Push-Location backend
.venv/Scripts/python.exe tests/probe_youtube_anonymous.py --output ../.local/youtube-tests/mweb.json
.venv/Scripts/python.exe tests/probe_youtube_anonymous.py --clients mweb,tv,web_safari --output ../.local/youtube-tests/multi-client.json
.venv/Scripts/python.exe tests/probe_youtube_anonymous.py --supply-token --download --output ../.local/youtube-tests/explicit-token-download.json
```

代理通过 `--proxy` 显式传入，默认本机 7890；替换为实际运行环境的地址。该脚本是人工网络测试工具，不参与 pytest。下载样例限制到 360p，单媒体文件大小限制 50 MiB。成功提取不等于文件验收通过，仍需确认生成文件及音视频轨道。

## 下一步

应在计划部署的服务器出口重复同一组匿名测试，与本机结果对比，记录出口环境而非收集账号 Cookie。当前证据不支持把“装好 Provider”当作恢复下载的保证。只有实际得到媒体文件并验证音视频后，才能把该部署标记为可用。

参考：[bgutil 验证与限制](https://github.com/Brainicism/bgutil-ytdlp-pot-provider#verification)。
