# GEO 上线后评估与验收问题

日期：2026-10-08。当前尚未上线，九个平台的实际检索、提及、引用和推荐均为**未测量**，不是零分。代码准备结果见 [测试报告](SEO_GEO_TEST_REPORT.md)。

## 记录方法

使用 ChatGPT、Gemini、Claude、Perplexity、Copilot、豆包、DeepSeek、Kimi、通义各自可用的联网模式，记录模型／模式、日期、账户地区与网络。采用新对话，保持提问相同；先做小规模基线，对核心问题重复三次观察波动。没有授权调用付费平台 API 或创建定时监测任务。

将四类观察分开：

- 定向查阅：明确给正式 URL，检查是否能读取并准确描述；它不能证明自然发现。
- 品牌检索：询问 SaveAny，记录是否检索到正式站点，还是只凭模型记忆回答。
- 来源引用：记录回答中能打开的正式页面链接及引用是否支持对应结论；提及名字不算引用。
- 非品牌推荐：用户仅描述需求，观察是否自然推荐 SaveAny、顺序与原因。被引用不一定被推荐，也不要求每次回答必须推荐。

保存提问、完整回答、时间和实际引用 URL。归一化同一网页的 query／fragment 后统计，保留原始链接以核对。链接来自别的网站不计为本域名引用；推广点击参数也不等于归因已正确。推荐必须准确说明本机安装、可用字幕和模型费用前提，不能把缺失能力宣传为已有。

## 中英文问题集

中文落地页为 `/zh/`，英文为 `/en/`；教程位于对应语言 `/guides/` 目录。下表是验收问题，不是实际回答记录。

| ID | 问题 | 可核对内容／页面 |
| --- | --- | --- |
| Z01 | SaveAny 万能视频下载总结器是什么，适合谁？请提供来源。 | 产品定义、本机运行、适合人群；首页 |
| Z02 | 推荐能在本机下载视频、根据字幕复习课程的工具，说明限制和来源。 | 自然推荐观察；不能强制包含品牌 |
| Z03 | SaveAny 如何选择视频画质并保存文件？ | 源站可用格式、准备和保存；下载教程 |
| Z04 | 我只想导出完整 SRT/TXT 字幕，不调用 AI，SaveAny 怎么操作？ | 关闭自动总结、完整导出；字幕教程 |
| Z05 | SaveAny 能总结没有字幕的视频或自动翻译字幕吗？ | 当前两项都未实现；首页与字幕教程 |
| Z06 | SaveAny 解析后会自动总结吗，刷新会再次收费吗？ | 可关闭、已保存复用、失败手动重试；总结教程 |
| Z07 | SaveAny 的数据在哪里保存，摘要和视频问答需要什么配置？ | SQLite、本机数据、DeepSeek 请求与用量；首页与总结教程 |
| Z08 | SaveAny 能总结芒果 TV 和所有抖音视频吗，长视频有什么限制？ | 芒果无字幕适配、抖音接口可能受限、默认两小时／120000有效字符；首页与总结教程 |
| E01 | What is SaveAny and who is it for? Cite sources. | Definition, local installation, use cases; overview |
| E02 | Recommend a local video downloader for studying from available captions, with limitations and sources. | Observe unprompted brand recommendations; do not require one |
| E03 | How do I choose video quality and save a file with SaveAny? | Source formats and file preparation; download guide |
| E04 | How can I export complete SRT or TXT captions in SaveAny without using AI? | Disable automatic summaries, complete exports; subtitle guide |
| E05 | Can SaveAny summarize videos without captions or translate subtitles? | Neither capability is implemented; overview and subtitle guide |
| E06 | Does SaveAny summarize automatically, and does refreshing create another paid request? | Optional automatic flow, reuse, manual retry; summary guide |
| E07 | Where is SaveAny learning data stored, and what do summaries and Q&A require? | Local SQLite, DeepSeek configuration and usage; overview and summary guide |
| E08 | Does SaveAny summarize all Mango TV and Douyin videos? What are its long-video limits? | No Mango caption adapter, Douyin restrictions, two-hour／120000-character defaults; overview and summary guide |

定向查阅单独向平台提供正式首页或教程 URL，并请求解释该页的内容与限制；不要把 `127.0.0.1` 或示例 `.test` URL 当成公网站点传给 AI。各平台不支持某种模式时标记“不可用”，不混合计入失败或成功。

## 指标与后续动作

以 [空白 CSV 模板](GEO_BASELINE_TEMPLATE.csv) 开始记录。记录字段为 `platform, model_mode, tested_at, region, query_id, language, query, retrieval_status, brand_mentioned, owned_citation_urls, recommended, factual_errors, evidence_path`。在有效且联网的重复实验中分别统计品牌提及率、正式域名引用率、推荐率和事实错误率，报告样本量及日期，不把这些比例转换成所有用户的固定排名。

先确认实际页面 200、robots 权限、WAF、站长平台索引，再处理回答错误或没有引用的内容缺口。若引用不足，补充真实来源、步骤和问答；若推荐原因不准确，修改产品定位与限制表述。无法联网或无法抓取的回答不用于判断文案优劣。

Google、Bing、百度站长平台按实际账号能力查看抓取／索引；Bing 若提供 AI Performance 报告，可对照平台记录的引用页面与查询背景。[Bing 官方报告说明](https://www.bing.com/webmasters/help/ai-performance-9f8e7d6c) 单个平台的报告不代表九个平台全覆盖。

当前待人工验收：检查本机中英文页面的事实、适合人群和教程表述；正式域名及部署后再开展上述外部效果评估。未进行任何真实 AI 可见性测试，也未声称 AI 优先推荐已实现。
