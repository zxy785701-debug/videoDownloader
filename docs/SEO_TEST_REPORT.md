# SEO 开发与验证报告

日期：2026-10-07。范围和用户确认见 [SEO 审计](SEO_PLAN_AND_AUDIT.md)，配置与发布见 [SEO 说明](SEO_SETUP.md)。本次完成上线前的代码和内容准备，网站尚未上线，人工验收与真实收录待完成。

## 最终实现

新增八个静态公开页面：中英文产品介绍，以及视频下载、AI 视频总结、SRT／TXT 字幕下载教程。原根工作区、历史 `#learn/{id}`、下载任务、字幕、摘要 SSE、导图、问答和后端逻辑不改；空闲工作区增加两种语言的教程链接，根工作区标记不收录。

正式域名按 `SEO_SITE_URL` 构建，生成独立标题、描述、H1、canonical、双向 hreflang、x-default、Open Graph／Twitter 文本元数据、JSON-LD、robots 与 XML sitemap。公开域名尚未填写，当前本机与独立包均为预览不收录模式，未填入虚构正式 URL。

`frontend/site-dist/` 是独立纯静态包，14 个文件，约 69 KB；包含八个正文页、根语言入口、404、CSS、图标、robots 与 sitemap。无需公开部署 FastAPI，不含 Vue 工作区资源、本机数据库、视频、模型密钥或日志。构建不添加 npm 依赖，既有下载与 AI 环境配置方式不变。

## 自动验证结果

| 验证 | 最终结果 | 证据与边界 |
| --- | --- | --- |
| Vue／TypeScript 与 Vite 生产构建 | 通过 | 原工作区和新增页面共同构建 |
| 独立公开站点构建 | 通过 | 默认预览不收录；目录仅静态文件 |
| SEO 构建与开发模式规则 | 9 项通过 | 域名、元数据、语言关联、预览 noindex、sitemap、验证码转义、保留原入口、公开包边界；开发模式页面、API 代理与关闭后不写生产文件 |
| 公开页浏览器检查 | 36 项通过 | 渲染标签与 JSON-LD、多语言、390／320px 布局、内部链接、XML、robots、八页禁用 JavaScript 阅读、零工作区 API 请求 |
| 后端单元回归 | 255 项通过 | 使用隔离数据库与模拟依赖；一条既有 Starlette/httpx 弃用提示 |
| 同屏工作区模拟回归 | 13 项通过 | 自动接续、下载锁定、断线恢复、偏好、历史／语言、错误与窄屏 |
| 摘要 SSE 模拟回归 | 14 项通过 | 草稿保留、订阅恢复、引用修复、失败保留、长字幕和删除／切换 |
| 问答 SSE 模拟回归 | 11 项通过 | 流式草稿、引用校验、重连、刷新、删除和窄屏 |
| 字幕／导图导出模拟回归 | 20 项通过 | 完整字幕、多语言、SVG／PNG、全屏、大图和失败恢复 |
| 基础学习模拟回归 | 13 项通过 | 下载首页、字幕、摘要、问答、导图、历史与删除 |

原功能模拟浏览器流程合计 **71 项**，所有最终浏览器报告均没有脚本异常。公开页渲染使用浏览器读取 `script[type="application/ld+json"]`，不是仅从网页文本提取结果判断 schema 存在性。每个公开内容页仅有 JSON-LD 数据脚本，没有可执行页面脚本、外部字体或工作区 API 请求；未进行真实模型或新增真实平台下载调用。

另在真实 Vite 开发实例确认中英文页面、教程、CSS、robots、sitemap 及原 `/api/v1/health` 代理均返回 200，开发页面始终 noindex，未执行任务创建。开发服务器临时测试端口为 8191，验证后关闭。

测试中曾因 PowerShell 启动参数拼接错误，隔离回归服务未启动，首次浏览器回归报告连接被拒绝。随后修正测试启动命令、逐个验证服务健康，再完成全部 71 项；没有把首次未运行算成产品通过。初始服务日志与最终运行报告均留在本机 `.local/`，不加入 Git。

结构化数据本次验证了渲染后 JSON 可解析、URL／语言对应和内容真实性，没有执行 Google Rich Results Test 的线上验证，也没有宣称软件应用富媒体结果合格。当前没有真实价格或评分，不填写 `offers`／`aggregateRating`；Google 的 [SoftwareApplication 富媒体规则](https://developers.google.com/search/docs/appearance/structured-data/software-app)另有资格要求。

## 本机验收产物

- `.local/seo-browser-test/report.json`：36 项公开页检查。
- `.local/seo-browser-test/zh-desktop.png`、`en-desktop.png`、`zh-mobile.png`、`en-mobile.png`：已人工查看桌面与手机渲染。
- `.local/seo-build-tests/`：自动生成的元数据与保留原工作区输出用例。
- `.local/seo-public-site/`：带 `https://saveany.example.test` 的隔离测试包，仅用于本机验证正式标签逻辑，**不是生产域名或可发布网站**。
- `.local/seo-regression/`：本次隔离服务的初始及修正日志。
- 原流程报告位于 `.local/unified-workspace-test/`、`.local/summary-stream-browser-test/`、`.local/chat-stream-browser-test/`、`.local/learning-export-test/`、`.local/learning-browser-test/`。

## 可复现命令

从仓库根目录执行静态规则和构建：

```powershell
npm.cmd run test:seo --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run build:site --prefix frontend
```

生成正式标签的本机测试包，不改正式域名配置：

```powershell
node --experimental-strip-types --input-type=module -e "import { buildSeoSite } from './frontend/seo/build.ts'; await buildSeoSite('.local/seo-public-site', {siteUrl:'https://saveany.example.test'}, true)"
python -m http.server 8189 --bind 127.0.0.1 --directory .local/seo-public-site
```

服务保持运行，在另一个终端执行：

```powershell
# 需要可解析的 Playwright 包和 Microsoft Edge，依赖方式同既有浏览器回归。
node frontend/tests/seo-e2e.cjs
```

脚本默认验证 `8189` 与示例 `.test` canonical，支持 `SEO_TEST_URL`／`SEO_TEST_ORIGIN` 覆盖。本次使用已配置的 Codex Node／Playwright 运行时，通过进程 `NODE_PATH` 指定模块目录，没有将机器路径或 Playwright 加进生产依赖。原功能回归命令见 [TESTING](TESTING.md)。

## 人工验收与上线待办

本机预览：[中文](http://127.0.0.1:8000/zh/)、[English](http://127.0.0.1:8000/en/)。请核对品牌文案、两种语言的描述、平台范围及教程步骤；切换语言应保持同一主题，教程按钮应定位本机安装步骤。再返回原工作区，确认原记录与下载／总结交互符合预期。尚未把用户沉默或自动测试通过视为人工验收。

待实际上线后执行：

1. 确认真实域名与静态托管，构建并发布正式索引包。
2. 完成 Google／Bing／百度站长账号验证，提交正式 sitemap；其他搜索引擎按官方入口处理。
3. 使用真实 URL 验证抓取、canonical、语言关联和结构化数据。
4. 检查线上 HTTPS、404、重定向、缓存、移动性能和 Core Web Vitals。
5. 建立真实索引与自然搜索流量基线，观察展示、点击和查询词，再按数据维护内容。

当前没有提交搜索引擎、部署公网、测量线上排名或购买域名；不能将本机通过写成“全网已优先展示”。
