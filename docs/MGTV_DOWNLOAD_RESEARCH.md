# 芒果 TV 下载：开源调研、策略与独立测试

日期：2026-10-05。状态：**调研与独立测试脚本完成；《流浪地球》、用户提供的电视剧样例及对照节目均已完整下载，并通过音视频完整解码。电影与用户电视剧样例可共用官网 pcweb 参数适配。**

独立研究阶段按用户要求暂缓 B 站接入，保留独立测试结果；当时未修改生产下载、AI 学习、前端或启动配置。

后续接入记录：用户随后要求整合 B 站与芒果方案，后端已新增平台适配层。本文件保留独立研究和实验阶段的结果；正式接入方式和新验收见 [后端适配接入报告](DOWNLOAD_ADAPTER_INTEGRATION.md)。

## 1. 开源项目比较

以下依据仓库源码、GitHub 提交 API 和公开问题记录。维护时间只针对相关文件，不能代表整个项目的维护状态；支持声明不能替代真实下载验证。

| 项目 | 已核对的实现与维护情况 | 本轮用途 |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/mgtv.py) | 内置 MangoTV 提取器：元信息 → getSource → 分清晰度资源地址 → HLS。相关文件最近提交为 2026-06 的 VIP 提取修复；项目现有版本 2026.08.19 已包含该逻辑 | **首选**，复用现有依赖、Firefox Cookie 读取与 HLS 下载器 |
| [you-get](https://github.com/soimort/you-get/blob/develop/src/you_get/extractors/mgtv.py) | 使用 pcweb player/video、player/getSource；支持四档清晰度与分片下载。相关文件最近提交 2024-08 主要修复 Python 语法警告；未见当前提取实现专门建立会员登录流程 | 参考另一官方接口路径；不以安装整个工具作为解决会员问题的依据 |
| [webvideo-downloader](https://github.com/jaysonlong/webvideo-downloader) | 浏览器 userscript 获取已登录页面的 getSource 响应，再交给本机 Python 下载器合并 HLS。该 userscript 最近提交为 2023-02 | **后备思路**：若 Firefox 正常完整播放，比较或捕获网页实际播放请求；代码较旧，不能直接保证现行网站可用 |
| [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) | 通用 HLS/DASH/MSS 下载工具，接受清单及请求头/Cookie；不是芒果会员播放权限解析器 | 已有可用清单后的可选下载引擎，本轮无需新增依赖 |

源码与维护证据：

- [yt-dlp MGTV 提取器源码](https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/yt_dlp/extractor/mgtv.py)。
- [VIP 提取修复提交](https://github.com/yt-dlp/yt-dlp/commit/6b67e1f2b77feb6d97852be08bfc2e0ab1c8aef0)。
- [2026-09-25 的 No video formats found 问题](https://github.com/yt-dlp/yt-dlp/issues/17734)，报告版本同为 2026.08.19；该问题不能直接证明本次样例的失败原因。
- [you-get 相关提交](https://github.com/soimort/you-get/commit/72b1a7bce13179f4678654d65e9f7cd9917dcaeb)。
- [webvideo-downloader userscript 源码](https://raw.githubusercontent.com/jaysonlong/webvideo-downloader/master/violentmonkey/WebVideoDownloader.user.js)、[相关提交](https://github.com/jaysonlong/webvideo-downloader/commit/cfe8d6061070eab74baddd1ff97859d55144c97c)。

## 2. 下载策略

1. 在独立进程中显式读取 Firefox 会话，仅在内存使用。先请求影片元信息与正常播放接口，确认平台是否返回可用资源；不把 Cookie 存入项目配置或报告。
2. 先测试现有 yt-dlp 提取器；失败时区分网络、会员识别、播放接口拒绝和提取器结构不匹配。结合其他开源实现和当前官网播放器源码，对齐正常网页的 pcweb 接口与参数；保留真实地区校验和账号会话。
3. 取得格式后列出清晰度，测试默认上限 480P，也支持 540P、576P、720P、1080P。部分节目返回 `480P`、`576P` 等标签，内置提取器的中文标签表无法识别；脚本在缺失尺寸时读取清单中的实际尺寸再选择格式。检查分片总时长、点播结束标记、缺失分片及预计大小；与影片元信息时长比较，避免把试看当成完整下载。
4. 下载完整分片，缺片必须失败，合并文件后核对音视频流与实际时长，并完整解码验收。单次测试大小上限 1 GiB；该上限和画质只是测试参数，不是正式产品规格。
5. 如果接口失败但 Firefox 能完整播放，比较网页播放器请求与提取器的差异；仍不能取得资源时才考虑浏览器捕获方案。本轮读取了该影片页面引用的公开播放器 JavaScript，未安装浏览器插件，也未导出 Cookie 文件或捕获 Firefox 网络请求。

脚本默认禁止不可播放的 DRM 格式；若实际清单要求受保护播放或当前不支持的加密格式，会停止并给出对应状态。当前选中的电影清单没有加密标记；没有进行许可证请求或受保护内容解密。

## 3. 用户样例的真实结果

样例：[https://www.mgtv.com/b/321423/5546935.html](https://www.mgtv.com/b/321423/5546935.html)。

| 检查 | 实测结果 |
| --- | --- |
| Firefox 会话读取 | 成功读取芒果域的有效 Cookie；数量随会话更新而变化，不以数量判断登录成功 |
| 影片元信息 | 《流浪地球》，video ID `5546935`，时长 7,503 秒，即 125 分 3 秒 |
| 平台会员识别 | player/video 返回 `code=200`、`user.isvip=1`；未保存昵称、账号 ID、ticket、IP 或设备 ID |
| 现有提取器 getSource | `tinker.glb.mgtv.com/player/getSource` 返回 `code=40005`，无资源数据 |
| 不使用系统代理 | 同一来源接口仍返回 `40005`；只调整测试进程，不修改系统代理 |
| 仅换 pcweb 接口 | 保留内置参数时仍被拒绝；因此不能把问题归因于接口域名这一项 |
| 旧版开源请求对照 | 仅保留 `pm2`、`tk2`、`video_id` 时 getSource 返回 200，但资源解析返回 617，仍无可用清单 |
| 官网网页参数适配 | pcweb 接口配合与 `tk2` 一致的生成设备标识、正常网页会员参数、空的 `src` / `abroad` 和 `definitionType=2`，getSource 返回 200，并取得四档格式 |
| 可选清晰度 | 平台标称标清 480P、高清 540P、超清 720P、蓝光 1080P；本次选择标清 |
| 完整清单 | 7,503.2 秒、752 个分片、点播结束标记；与元信息时长一致，预计分片约 560 MiB |
| 实际视频尺寸 | 清单返回 832 × 348；平台的标清档位名称不等于宽银幕影片的实际画面高度 |
| 加密情况 | 当前选中的 HLS 清单没有加密标记；元信息未提供 license 地址 |
| 完整下载验收 | 成功；合并后 554,953,559 字节（约 529.2 MiB），时长 7,503.12 秒，832 × 348，H.264 + AAC，完整解码退出码 0 |

平台 `40005` 的版权地区拒绝也见 [yt-dlp 已有问题](https://github.com/yt-dlp/yt-dlp/issues/12183)。用户已确认同一链接在 Firefox 中能完整播放；本次正常官网请求参数适配后取得了完整清单，说明最初错误不足以证明这个账号在真实网页中受到地区限制。适配同时改变了接口与多项参数，本轮没有逐项隔离实验，不能断言某一项参数是唯一原因。脚本没有伪造来源 IP，`geo_bypass=False`。

官方源码依据是影片页面引用的 [vplayer 9.0.7](https://s1.hitv.com/libs/??vplayer/9.0.7/vplayer.min.js?ver=202209260954)。其中元信息和 `/player/getSource` 的普通 pcweb 请求与内置提取器不完全相同。脚本复用 yt-dlp 的会话和 HLS 下载能力，仅在独立进程内对齐这些参数。

对照样例《拜托，请你爱我》（video ID `7329822`）使用内置接口即可取得完整资源，Firefox 模式完整下载文件 106,448,382 字节，时长 2,655.98 秒，832 × 468，H.264 + AAC，完整解码退出码 0。这说明内置提取器并非对所有芒果视频都失效，但不能据此保证电影或会员内容全部兼容。

用户在现有网站观察到动漫、短剧、综艺可以解析，电影、电视剧无法解析。这是有价值的兼容性线索，但不能据此建立“每个类别固定一个接口”的规则。应按具体播放响应验证权限、资源链路和格式。

新增电视剧对照：[《我们的少年时代2》样例](https://www.mgtv.com/b/855808/24564644.html)，元信息时长 1,822 秒。读取同一 Firefox 会话后，内置提取器仍在 getSource 返回 40005；官网参数适配返回 200，四档格式可用，标清完整清单 1,822.12 秒、184 个分片、832 × 348、没有加密标记。完整下载合并后文件 114,677,547 字节（约 109.4 MiB），实测时长 1,822.05 秒，H.264 + AAC，完整解码退出码 0。两条用户失败样例可以使用同一个 pcweb 适配，不需要为电影和电视剧分别开发两个解析器；不能推广为全部同类内容均已支持。

| 已完成下载验收的样例 | 播放接口策略 | 实际时长 | 合并后大小 | 实际尺寸 | 验收 |
| --- | --- | --- | --- | --- | --- |
| 《流浪地球》`5546935` | 官网 pcweb 参数适配 + Firefox | 125 分 3.12 秒 | 529.2 MiB | 832 × 348 | 完整下载、时长匹配、音视频完整解码通过 |
| 用户电视剧《我们的少年时代2》`24564644` | 同一官网 pcweb 参数适配 + Firefox | 30 分 22.05 秒 | 109.4 MiB | 832 × 348 | 完整下载、时长匹配、音视频完整解码通过 |
| 对照《拜托，请你爱我》`7329822` | 内置接口 + Firefox；对缺失尺寸补读清单 | 44 分 15.98 秒 | 101.5 MiB | 832 × 468 | 完整下载、时长匹配、音视频完整解码通过 |

三次完整下载均选择标清，格式列表中的其他档位未完整下载验证。报告各有一条经过分类后为 `unknown` 的警告，未保留原始日志；完整解码、时长和文件验收均通过，不把未知警告解释成已证明无风险。

## 4. 为什么现有网站还不能直接解析

网站已有通用 yt-dlp 解析入口，芒果 URL 可以进入 MangoTV 提取器；失败发生在提取器获取可用播放地址的阶段。生产代码 `backend/app/video_service.py` 的 `_video_options()` 只在 `_is_youtube(source_url)` 成立时设置 `cookiesfrombrowser`，所以芒果请求不会自动带上 Firefox 登录会话。即使独立测试补上了会话，内置提取器仍因请求方式差异而无法解析这部电影。

后续接入可增加仅针对芒果的会话与播放器参数适配，让现有解析和下载入口复用同一策略，并保留原有平台行为。不能只给前端增加一个“芒果 TV”标签。本轮按用户要求先做独立验证，没有修改生产入口。

## 5. 测试脚本与复现

[独立测试脚本](../backend/tests/probe_mgtv_firefox.py)。在项目根目录：

```powershell
# 只检查元信息、格式与清单
backend/.venv/Scripts/python.exe backend/tests/probe_mgtv_firefox.py --url "https://www.mgtv.com/b/321423/5546935.html" --source-api pcweb-web --direct

# 使用正常官网网页参数，读取 Firefox 会话，完整下载标清档位
backend/.venv/Scripts/python.exe backend/tests/probe_mgtv_firefox.py --url "https://www.mgtv.com/b/321423/5546935.html" --source-api pcweb-web --direct --download

# 保留内置提取器作为失败对照
backend/.venv/Scripts/python.exe backend/tests/probe_mgtv_firefox.py --url "https://www.mgtv.com/b/321423/5546935.html" --source-api installed --direct
```

其他参数：`--profile` 指定 Firefox 配置，`--height 720` 选择测试画质上限，`--anonymous` 对照不读取会话。`--direct` 仅让该测试进程忽略系统代理，不修改系统设置。

`--source-api` 四种对照方式：`installed`（默认，保留现有提取器）、`pcweb`（只换接口）、`pcweb-legacy`（另一开源实现的旧请求参数）、`pcweb-web`（本次官网播放器参数适配）。

每次生成独立报告目录 `.local/mgtv-firefox-probe/<时间与模式>/`，已被 Git 忽略。报告只保存分类错误、受控元信息及 API 字段结构，不记录 Cookie 值、会员凭据、签名播放地址或原始响应。

- 内置提取器失败证据：`20261005-004823-251921-firefox/report.json`。
- 官网参数适配后的完整电影清单：`20261005-010639-876200-firefox/report.json`。
- 电影完整下载及解码：`20261005-011031-171726-firefox/report.json`；耗时 263.48 秒，SHA-256 `6a003fc4baa6f5198600b7a5c97050e67df84db841f0d341cece632b5eb65934`。
- 对照节目完整下载及解码：`20261005-005856-352020-firefox/report.json`。
- 用户电视剧内置提取器失败：`20261005-011559-277748-firefox/report.json`；官网参数适配取得完整清单：`20261005-011559-924921-firefox/report.json`。
- 用户电视剧完整下载及解码：`20261005-011647-132260-firefox/report.json`；耗时 56.31 秒，SHA-256 `4f2efd55adbd25998746e955343224bbb7ad0812167140bdc7f494f9d2821adc`。

验证情况：真实 API 多次得到上述结果；CLI 帮助与脚本执行通过；4 个模拟 HLS 清单用例通过（有效点播、未结束点播、受保护/不支持的加密、缺片标记）。电影、用户电视剧及对照节目均已验证完整下载、合并和音视频完整解码。其余电影、会员节目和更高清晰度未进行完整下载验证。
