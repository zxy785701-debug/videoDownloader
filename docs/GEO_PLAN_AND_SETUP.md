# GEO 方案、抓取策略与上线准备

日期：2026-10-08。对象：SaveAny／万能视频下载总结器。基于 [SEO 完善](SEO_REFINEMENT.md) 扩展，验证见 [联合测试报告](SEO_GEO_TEST_REPORT.md)，效果测量见 [GEO 评估](GEO_EVALUATION.md)。

## 用户确认

- 国内外平台：ChatGPT、Gemini、Claude、Perplexity、Copilot、豆包、DeepSeek、Kimi、通义。
- 仍未上线、暂无正式域名；先做上线前准备。
- 允许 AI 搜索与用户查阅，限制已知训练爬虫；本机学习记录、问答和文件继续不公开。
- Google-Extended 无法分别控制 Gemini 训练与检索引用，用户明确选择“Gemini 可见性优先”，接受公开内容可能用于训练。
- 用户已授权按需安装 skill。本轮安装并阅读原作者 `coreyhaines31/marketingskills` 的 `skills/ai-seo`，本机版本 2.7.4；其建议结合官方规则核对，不将第三方统计或平台排名猜测当成项目实测。

GEO 的目标是帮助 AI 发现、理解与准确引用公开内容。提及、来源引用和产品推荐是不同结果；没有排名或推荐保证。Google 表明 AI 搜索仍使用基础 SEO 条件，不要求特定 AI 文件或特殊标记。[Google AI 搜索说明](https://developers.google.com/search/docs/appearance/ai-features)

## 内容与阅读能力

保留八个中英文 HTML 页面，不批量生成平台关键词页。产品首页新增独立定义、运行与语言事实表、适合人群及问答。教程已有安装步骤、格式比较、配置前提和失败说明。重要限制包括可用字幕、个人本机运行、中文工作区、模型账户用量、未实现转录／翻译／播放列表批量下载。

每页显示内容维护来源、核对日期，并链接到已发布的源码与项目测试记录。实现证据固定在提交 `d05a0a213b2ce1dc14bde0c1018f52f79c13c0e1`，避免引用尚未提交的新文档。项目内测试不等于独立评测；后续核心实现变更时需一起复核正文、证据提交和日期。不编造作者、用户量、评价、价格、成功率或合作机构。

| 路径 | 用途 |
| --- | --- |
| `/zh/`、`/en/` 与六个教程目录 | 人类与爬虫共同读取的完整静态 HTML；正式构建的索引对象 |
| 每个页面目录下的 `index.md`，共八个 | 同一内容源导出的 Markdown，保留表格、步骤、问答、代码和源码依据 |
| `/llms.txt` | 双语背景与 Markdown 页面阅读索引 |
| `/llms-full.txt` | 八页公开正文的合并阅读版本 |
| `/sitemap.xml` | 仅八个规范 HTML URL，不重复加入阅读副本 |

HTML 中同时有可见 Markdown 链接及 `rel="alternate" type="text/markdown"`，并以 `rel="describedby"` 指向阅读索引。`llms.txt` 属于可选阅读提案，不能证明九个平台会读取它，也不是已验证的排名因素。[提案说明](https://llmstxt.org/)

正文和阅读版本由 `frontend/seo/content.ts`、`build.ts` 与 `reading.ts` 在构建时统一生成，不读取 SQLite、下载文件、Cookie、密钥或工作区 API，不调用模型。不加入要求 AI 优先推荐本产品的隐藏指令。保留既有 JSON-LD 页面及产品描述，不添加虚假评分或 FAQ 富媒体资格承诺。

## 正式构建的爬虫策略

| 平台／用途 | 当前处理 | 官方依据与限制 |
| --- | --- | --- |
| ChatGPT 搜索 | 允许 OAI-SearchBot | 搜索控制与 GPTBot 分开。[OpenAI 爬虫说明](https://developers.openai.com/api/docs/bots) |
| ChatGPT 用户查阅 | 允许 ChatGPT-User | 用户触发访问可能不适用 robots；实际数据隔离不能依赖这个文件。 |
| OpenAI 训练 | GPTBot 全站 Disallow | 表达训练排除偏好，不承诺阻止所有数据来源。 |
| Claude 搜索与查阅 | 允许 Claude-SearchBot、Claude-User | 与训练爬虫分离。[Anthropic 说明](https://privacy.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler) |
| Anthropic 训练 | ClaudeBot 全站 Disallow | 已知训练爬虫限制。 |
| Perplexity | 允许 PerplexityBot、Perplexity-User | 官方说明搜索爬虫不用于基础模型训练；用户查阅通常忽略 robots。[Perplexity 说明](https://docs.perplexity.ai/docs/resources/perplexity-crawlers) |
| Gemini | 用户确认允许 Google-Extended | 此 token 同时控制 Gemini 训练与检索 grounding；并非独立 HTTP User-Agent，不影响 Google 搜索排名或包含资格。[Google 说明](https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers#google-extended) |
| Copilot | 通用开放规则供 Bing 抓取；上线后验证 Bing | Microsoft 的联网搜索会利用 Bing，不保证所有模式都检索本站。[Microsoft 说明](https://support.microsoft.com/en-us/microsoft-365-copilot/how-web-search-works-in-microsoft-365-copilot-chat-and-agents) |
| Kimi | 中文静态正文、可直接读取的 URL、通用开放规则 | 官方帮助介绍联网搜索和定向 URL 查阅；未确认独立爬虫 token。[Kimi 说明](https://www.kimi.com/help/features/search) |
| 豆包、DeepSeek、通义 | 中文定义、问答、标准 HTML 与通用开放规则；上线后分别实测 | 本轮未确认可独立控制训练与检索的官方爬虫规范，不虚构专用 User-Agent，不宣称已被收录。 |

每个具体搜索／查阅 group 与 `*` group 都带相同的 API／接口文档排除，防止具体 group 不继承通用规则而意外开放这些路径。已知训练限制是 GPTBot 与 ClaudeBot；Google-Extended 是明确同意的例外。未识别的采集程序、第三方数据集或不遵守 robots 的访问，不能由当前规则保证排除。

未配置域名时仅输出 `User-agent: * / Disallow: /`，所有页面继续预览不收录。开发服务器也始终处于预览模式。robots 不是鉴权；上线只部署独立静态包，本机 FastAPI、SQLite 和浏览器会话不进入公开站点。

## 构建、缓存和部署

正式域名与验证码沿用 [SEO_SETUP](SEO_SETUP.md)，不新增模型配置或第三方统计。当前预览可访问：`http://127.0.0.1:8000/zh/`、`/en/`、`/zh/index.md`、`/llms.txt`、`/llms-full.txt`。

```powershell
npm.cmd run test:seo --prefix frontend
npm.cmd run test:geo --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run build:site --prefix frontend
```

公开包当前为 24 个文件。设置自己的 `SEO_SITE_URL` 后重新构建；不要上传本机含学习服务的整个项目，也不要发布 `.local/geo-public-site` 的示例域名测试包。

托管需让 HTML、Markdown 和文本文件直接返回 200，未知页面返回 404；Markdown 建议使用 `text/markdown; charset=utf-8`，文本使用 `text/plain; charset=utf-8`。建议对 `*.md`、`/llms.txt`、`/llms-full.txt` 配置 `X-Robots-Tag: noindex,follow`，对每个 Markdown 再以 HTTP `Link` 标注对应 HTML canonical，供支持这些规则的搜索引擎识别。阅读副本仍可供允许的爬虫抓取；noindex 不会阻止用户查阅。

Vite 开发服务器已经添加这些阅读响应头；构建产物是静态文件，正式响应头需在实际托管配置，上线前检查。当前 FastAPI 本机预览没有新增响应头中间件，依靠已有预览 robots 和本机访问边界；未声称静态文件自身能控制响应头。

HTML、Markdown、llms 文件、robots、sitemap 和固定路径 CSS 一起发布并重新验证缓存。公开内容无需执行 JS、登录、Cookie 或访问学习 API。若托管有 WAF，按官方 IP／爬虫验证规则检查是否误拦搜索抓取，不仅凭自报 User-Agent 放行私人服务；本轮未修改任何 WAF 或公网配置。

## 上线后的权威与效果工作

真实教程、仓库资料和相关社区引用沿用 [SEO 外链计划](SEO_REFINEMENT.md)。本轮未代发帖子、联系他人、购买链接或宣称第三方认可。先发布可核对的内容，再依据平台实际检索结果补充有价值的案例。

上线验收分为：公开可访问、被抓取／索引、被引用、被提及、被推荐、能力表述准确。当前只完成第一项的本机模拟与生成条件检查，真实公网访问及其余效果待正式域名上线后执行。[评估问题和记录方法](GEO_EVALUATION.md)
