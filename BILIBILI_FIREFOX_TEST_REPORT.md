# B 站充电视频：Firefox 会话独立下载测试

日期：2026-10-05。独立测试阶段结论：**用户提供样例的第 4 P 已完整下载并通过音视频解码验证；当时尚未接入项目下载流程。**

后续接入记录：用户已确认 Firefox 优先、未登录时回退原匿名流程，并在 2026-10-05 要求整合。后端现在已接入相应策略；本文件保留前期独立测试证据，最终实现和新验收见 [后端适配接入报告](DOWNLOAD_ADAPTER_INTEGRATION.md)。下面“待确认”方案为前期记录，实际接入默认优先 Firefox。

## 样例与结果

- 视频：[BV18YEQz4E1M，第 4 P](https://www.bilibili.com/video/BV18YEQz4E1M/?p=4)。
- 标题：RIIZE《bag bad back》全曲翻跳＋全曲保姆级教程｜综合位。
- 分 P：主歌1（讲解＋数拍＋0.8倍速），CID `30032726179`。
- 使用已登录 Firefox 的本机会话，B 站登录状态接口返回 `isLogin=true`；作品元信息的 `is_upower_exclusive=true`。
- 成功下载：480P、852×480，HEVC 视频＋AAC 音频，合并为 MP4。
- 平台分 P 时长：2,503 秒；提取器时长：2,502.686 秒；实际文件时长：**2,502.67 秒（41:42.67）**，误差不到 1 秒。
- 文件大小：**83,728,717 字节**，约 79.85 MiB。
- FFmpeg 对整段视频和音频执行解码，显式选择两种流，**退出码为 0**。
- 成功一轮含获取元信息、下载、合并和完整解码约 **60.95 秒**，不代表一般下载速度。

## 网络故障与处理

默认主 CDN 下载出现 TLS 协议异常；本机系统 HTTP/HTTPS 代理指向 `127.0.0.1:7890`。仅在测试中禁用代理后，主 CDN 仍连接超时。

脚本在同一平台播放响应中读取音视频资源的 `backupUrl` / `backup_url`，选择第一个备用地址后成功下载。成功一轮保留系统代理，音视频资源分别来自 `upos-sz-mirrorhw.bilivideo.com` 与 `upos-sz-estgoss.bilivideo.com`。没有修改系统代理、浏览器数据库、项目依赖或已安装的 yt-dlp 源码。

匿名对照只检查了元信息：也能取得与完整时长一致的格式信息，但没有下载或解码匿名结果。因此，**本次证明 Firefox 登录会话下可完整下载此样例，不能证明 Cookie 对这条视频必不可少，也不能保证其他充电视频都可下载。**

## 复现

独立脚本：[probe_bilibili_firefox.py](backend/tests/probe_bilibili_firefox.py)。在项目根目录运行：

```powershell
backend/.venv/Scripts/python.exe backend/tests/probe_bilibili_firefox.py --url "https://www.bilibili.com/video/BV18YEQz4E1M/?p=4" --download --backup-index 1
```

默认只检查元信息；`--download` 才下载并完整解码。`--profile` 可指定 Firefox 配置；`--anonymous` 禁用会话；`--direct` 仅对本次测试忽略代理；`--height` 支持 360、480、720、1080，默认 480。`--backup-index 0` 使用主 CDN，1/2 使用平台提供的对应备用地址。单资源大小上限 300 MiB，网络超时与重试有限制。

脚本保留 `p=4`，核对分 P 身份与完整时长，识别提取器的试看提示，不将短试看标记为成功。每次生成独立本机目录；未导出 Cookie 文件，也未保存账号信息、Cookie 值或签名媒体 URL。输出只包含受控元信息、公开 CDN 主机名和分类错误。

本次成功证据：

- `.local/bilibili-firefox-probe/20261005-002121-658028-firefox/video.mp4`
- 同目录 `report.json`、`media-validation.json`。
- 视频 SHA-256：`6a5e3362b9abf56e0dd6636d10168ade5c233e1faede539df1dd3b21237cb07b`。

媒体与原始证据被现有 `.gitignore` 排除，不随 Git 分发。本轮只新增手动测试脚本和文档，没有修改生产下载服务、前端或启动脚本；原有 AI 扩展改动也保留。

## 建议接入方案，待用户确认

1. 为 B 站下载增加独立、默认关闭的 Firefox 会话开关，可指定配置；解析与下载使用同一会话规则，继续保持 YouTube 和抖音现有行为。
2. 在 B 站提取器中保留平台返回的备用 CDN；主地址遇到网络错误时，有限次数尝试同一格式的备用地址。只在服务端使用，不把签名地址或会话发给前端。
3. 会话下载使用服务端文件交付；区分登录失效、充电权限不足、试看和网络错误，失败不显示已完整下载。
4. 接入后补充配置隔离、分 P、试看识别与备用地址的回归检查，并以同一真实样例验收网页下载闭环。

先验收本次 MP4，再按确认后的范围实施上述扩展。
