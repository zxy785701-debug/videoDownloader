# 抖音解析与下载验收

日期：2026-10-03。测试环境为本机 Windows、FastAPI 和项目现有 Python 虚拟环境。

## 核实结果

- 用户链接：`https://www.douyin.com/jingxuan?modal_id=7691322577818201073`。
- 现有 yt-dlp 抖音提取器识别 `/video/<id>`，不直接匹配这种精选页链接；其 Web detail API 路径还可能要求 fresh cookies。
- 实测旧 `https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/` 返回 HTTP 200、空响应体，不能作为主解析路径。
- 移动分享页第一次返回页面外壳并下发 `ttwid` 匿名访客 Cookie；同一 HTTP 会话第二次请求返回 `window._ROUTER_DATA` 中的 `videoInfoRes.item_list`。
- 专用模块只在内存中接收平台下发的访客 Cookie，不读取抖音浏览器登录态，不要求用户导出或填写 Cookie，不调用第三方解析服务。
- `playwm` 改写只作用于可信平台域名下的 `/aweme/v1/playwm/` 路径，查询参数不变。这一步必须在成功获得作品信息以后使用，不能代替元数据解析。

参考实现：[rathodpratham-dev/douyin_video_downloader](https://github.com/rathodpratham-dev/douyin_video_downloader/blob/main/downloader.py)、[yt-dlp Douyin extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/tiktok.py)、[media-parser 抖音解析说明](https://github.com/ucmao/media-parser/blob/main/docs/parsers/douyin.md)。本项目编写独立适配器，没有引入这些仓库的运行服务或完整代码。

## 真实网络测试

| 输入 | 结果 |
| --- | --- |
| 用户精选页 `modal_id=7691322577818201073` | 解析成功：1080×1920、395.534 秒，标题、封面、MP4 格式可用 |
| 短链 `https://v.douyin.com/b80nLPyT6cc` | 解析成功：目标作品 7674550636700011810、1920×1080、459.105 秒 |
| 长链接 `/video/6961737553342991651` | 解析成功：1080×1920、19.782 秒 |
| 移动链接 `https://m.douyin.com/share/video/7685345542323834441` | 解析成功：1080×1920、59.134 秒 |

用户视频实际完整下载为 `douyin_7691322577818201073.mp4`，43,204,005 字节。MP4 容器检查通过；FFmpeg 读取视频和音频流的检查退出码为 0。

网页端也完成了真实的解析、点击下载、任务变为 `ready` 和出现“保存到设备”。文件接口的 Range 请求返回 `206 video/mp4`，范围 `bytes 0-15/43204005`，文件头为 ISO BMFF `ftyp`。这些结果不是模拟测试。

哔哩哔哩 `BV1nPaE6NE4g` 和 YouTube `aqz-KE-bpKQ` 的现有解析接口均返回 HTTP 200，分别列出 5 和 10 个格式。此次没有重复下载这两个平台的完整视频。

## 自动测试与构建

- 后端：80 项测试通过，包含原有 30 项及新增 50 项抖音测试。
- 新测试使用 MockTransport，覆盖匿名会话隔离、短链与 modal_id、精确作品编号、嵌套 JSON、非法跳转阻止、MIME/长度/容器校验、断流和残片清理、日志脱敏、任务/Range 交付、原平台分流。
- 模拟 MP4 仅用于协议和容器结构测试，不代表真实编码视频；可读取媒体流的证据来自上述真实下载文件及 FFmpeg 检查。
- 前端 `npm run build` 成功；仅增加抖音支持站点提示及必要的换行布局，没有调整前端业务流程。

## 实现范围

新增 `backend/app/douyin.py`；在 `video_service.py` 中分流抖音，其他平台继续使用原 yt-dlp 逻辑。公开 API 的路径、请求/响应模型与前端调用保持不变。抖音下载阶段重新解析媒体地址，并使用服务端流式下载与现有任务进度、文件交付流程。

仅支持公开普通视频、自动/服务端交付，单文件上限 1 GiB。图集、直播、私密和已删除作品不在本次范围内。匿名访客会话不等于账号登录，也不能保证所有网络出口和未来平台版本都可用。文件校验检查长度和容器结构，不替代完整解码或内容哈希校验。
