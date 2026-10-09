# SEO 审计与实施方案

日期：2026-10-07。基线提交：`d05a0a2`。对象：SaveAny／万能视频下载总结器。

## 用户确认与范围

用户确认尚未上线，面向中英文用户，同时覆盖国内外搜索引擎；按推荐范围新增公开产品介绍与使用教程，保留原下载／总结工作区，学习记录、问答与下载文件不作为公开搜索内容。用户另外授权安装 `seo-audit` skill。

采用用户指定的 [seo-audit](https://www.skills.sh/coreyhaines31/marketingskills/seo-audit)；已通过 Codex 内置安装器安装原作者仓库的 `skills/seo-audit`，读取 `SKILL.md` 与国际化参考。2026-10-08 按用户授权补充安装 `ai-seo`，见 [GEO 方案](GEO_PLAN_AND_SETUP.md)。用户五项策略的后续落实见 [SEO 完善记录](SEO_REFINEMENT.md)。

目标是改善公开内容的抓取、理解和相关搜索可见度。排名由搜索引擎决定，不能保证全网优先排名；未上线之前也不能验证真实收录、自然流量或线上 Core Web Vitals。[Google SEO 入门指南](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)

## 审计结论与优先级

| 优先级／影响 | 问题 | 本项目证据 | 处理 |
| --- | --- | --- | --- |
| P0／高 | 尚无可抓取的正式网站 | 用户确认“尚未上线”；启动脚本绑定 `127.0.0.1` | 提供纯静态公开站点构建；域名与公网部署待确定 |
| P1／高 | 首页正文依赖 JavaScript | 原 `frontend/index.html` 只有空 `#app`，内容由 Vue 挂载 | 新增八个静态中英文页面，正文与链接直接存在 HTML |
| P1／高 | 只有工作区，没有公开教程和主题入口 | 原入口、hash 历史与帮助弹窗均服务本机操作 | 新增产品介绍、视频下载、AI 总结、字幕下载四类内容及内部链接 |
| P1／高 | 缺少域名规范化、站点地图和语言关联 | 基线源码未配置 canonical、hreflang、sitemap 或 robots | 按构建时的正式 HTTPS 域名统一生成；默认预览不收录 |
| P1／高 | 公开站点与本机服务不能直接等同 | `analysis_routes.local_access` 限制学习 API 的本机 Host／Origin；本机会话、数据库和模型配置为个人用途 | 公开包仅静态文件，部署无需开放本机 API，访问不请求学习记录 |
| P2／中 | 标题、描述没有覆盖总结功能 | 原标题 `save any · 保存视频到设备`，描述仅说明本机下载 | 公开页面独立标题、描述、一个 H1、可见正文、Open Graph 和 Twitter 文本元数据 |
| P2／中 | 没有中英文等价内容 | 原工作区主要中文 | 产品正文、教程、元数据全部提供中英文；保留工作区语言现状 |
| P2／中 | 结构化信息缺失 | 源码检索未见 JSON-LD；渲染的工作区中 JSON-LD 数量为 0 | 配置域名后的公开页面生成 WebSite、SoftwareApplication、WebPage、BreadcrumbList；浏览器渲染后核对 |
| P3／中 | 缺少线上效果证据 | 尚无正式域名、站长账号或流量基线 | 上线后完成账号验证、提交 sitemap、检查实际收录和性能 |

这里的结构化数据结论包含浏览器 DOM 检查，不以网页文本提取器漏掉脚本为证据。原 hash 学习记录继续用于本机恢复，不改成对外内容页，也不加入 sitemap。抓取不同公开内容使用独立路径，符合 [Google JavaScript SEO 文档](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics)对可抓取 URL 的说明。

## 页面与关键词映射

以下关键词来自当前真实能力与查询意图，尚未使用搜索量工具；没有声称它们已有流量或竞争优势。

| 页面 | 中文主要意图 | 英文主要意图 |
| --- | --- | --- |
| `/zh/`、`/en/` | 万能视频下载总结器、视频下载与 AI 总结 | video downloader、AI video summarizer |
| `/{lang}/guides/video-download/` | 视频下载教程、选择画质、保存文件 | how to download videos、choose video quality |
| `/{lang}/guides/ai-video-summary/` | 根据字幕生成 AI 视频总结、章节与思维导图 | video summary from captions、AI summary guide |
| `/{lang}/guides/subtitle-download/` | 下载 SRT／TXT 字幕、导出完整字幕 | download SRT subtitles、export TXT transcript |

正文包含实际安装命令、可用平台范围、模型配置前提、失败恢复与导出差异。没有添加虚构评价、用户数、价格、成功率、奖项或“所有视频可用”等宣传。英文页面明确工作区与结构化摘要主要中文，避免把英文介绍误写成英文功能支持。

## 已实施的架构

- `frontend/seo/content.ts`：受版本管理的中英文正文、页面关系和内容核对日期。
- `frontend/seo/build.ts`：静态 HTML、SEO 元数据、语言关联、JSON-LD、XML sitemap 和 robots 生成器。
- `frontend/seo/build-site.ts`：单独构建纯公开站点，输出 `frontend/site-dist/`。
- Vite 构建插件：给原 `frontend/dist/` 追加公开页面，保留原根首页和应用资源。
- Vite 开发模式：直接提供相同静态正文，始终预览不收录；根工作区与原 API 代理保留，关闭开发服务器不写生产构建目录。
- 原工作区：增加 `noindex,follow` 和空闲状态下的教程链接；`#learn/{id}`、下载、字幕、SSE、模型调用与后端路由不改。

每个语言页面 canonical 指向自己，包含双向 `zh-CN`／`en` 与同主题英文 `x-default`，HTML 与 sitemap 使用同一份路径映射。没有根据 IP 或浏览器语言自动跳转。[Google 多语言页面说明](https://developers.google.com/search/docs/specialty/international/localized-versions)

无正式域名时不生成绝对 canonical／hreflang／结构化 URL，正文仍可预览；robots 阻止抓取，sitemap 没有占位 URL。配置正式域名后仅八个公开页参与索引，本机根工作区始终 `noindex`。robots 对 `/api/` 等非内容入口的排除不替代鉴权或隔离。[Google robots.txt 说明](https://developers.google.com/search/docs/crawling-indexing/robots/intro)

## 后续工作

具体构建与上线步骤见 [SEO 配置和发布说明](SEO_SETUP.md)，自动验证及人工验收入口见 [SEO 测试报告](SEO_TEST_REPORT.md)。

上线后先验证域名和 sitemap，再观察真实搜索展示、点击、查询词与页面体验。根据用户真实问题增加有内容差异的教程，优先补充可复现案例；不批量堆砌平台、地区或同义关键词页面。公开案例需要另行确认来源和可公开内容，不能直接从本机记录批量导出。
