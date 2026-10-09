# SEO 五项策略完善记录

日期：2026-10-08。用户要求先完善 SEO，再在其基础上完善 GEO。既有 [SEO 审计](SEO_PLAN_AND_AUDIT.md) 和 [上线说明](SEO_SETUP.md) 继续适用；本轮证据见 [联合测试报告](SEO_GEO_TEST_REPORT.md)。

## 实施结果

| 用户策略 | 实施与边界 |
| --- | --- |
| TDK | 八页独立标题、描述和 5 个相关关键词；核心功能在前、品牌在后。中文标题 ≤30 字符，英文标题 ≤60 字符，中英文描述均 ≤80 字符，自动检查唯一性和长度。 |
| 外链／友情链接 | 站内教程互链和源码依据已完成，真实外链计划如下。尚未联系合作站点、交换链接或向第三方发布。 |
| SSR／SSG | 保留 SSG：直接构建完整 HTML 正文，不依赖 Vue、登录或 API 渲染。当前公开内容只有八页，静态构建适用；本机 Vue 工作区负责交互。 |
| robots.txt | 正式构建开放公开内容，排除 API 和接口文档；预览全站禁止抓取。robots 管理抓取，页面 noindex 管理索引，公开包隔离私人数据。 |
| sitemap | 正式构建包含八个规范 HTML URL、双语对应关系与实际内容核对日期；预览不生成占位 URL。Markdown 阅读副本不重复加入地图。 |

长度是本项目的文案约束，不是搜索引擎统一的硬性排名门槛。Google 根据页面及其他信息决定最终标题、摘要，展示长度受设备宽度影响；不保证使用原文或提高点击率。[标题说明](https://developers.google.com/search/docs/appearance/title-link)、[摘要说明](https://developers.google.com/search/docs/appearance/snippet)

关键词按用户要求输出为 `meta keywords`，同时用于保持主题一致；Google 明确不使用它决定索引和排名，因此主要投入仍是正文、标题、教程和可抓取性。[Google 元数据说明](https://developers.google.com/search/docs/crawling-indexing/special-tags)

| 内容 | 中文标题 | 英文标题 |
| --- | --- | --- |
| 产品介绍 | AI视频总结与下载 - 本机学习 \| SaveAny | AI Video Summaries & Downloads \| SaveAny |
| 下载教程 | 视频下载 - 画质选择教程 \| SaveAny | Video Downloads - Setup & Quality Guide \| SaveAny |
| 总结教程 | AI视频总结 - 字幕与导图 \| SaveAny | AI Video Summaries - Captions & Mind Maps \| SaveAny |
| 字幕教程 | 字幕下载 - 完整SRT与TXT \| SaveAny | Subtitle Downloads - Complete SRT & TXT \| SaveAny |

摘要文案准确说明本机运行、可用字幕和实际导出能力；不使用“任意视频都可总结”等超出实现范围的承诺。所有 TDK 与 Open Graph、Twitter 共享内容源，正文和标题保持对应。

## 真实外链与内容发布计划

外链价值与来源质量、主题关联和用户价值有关，不能仅以链接数量判断。Google 将过度交换链接和为操纵排名生成的链接列为链接垃圾行为。[Google 链接政策](https://developers.google.com/search/docs/essentials/spam-policies#link-spam)

| 上线后动作 | 可提供的材料 | 完成标准 |
| --- | --- | --- |
| 更新源码仓库的站点入口 | 正式域名、安装说明、平台支持边界 | 官方仓库与网站名称及链接一致；不要提前填假域名 |
| 发布有用教程 | 经确认可公开的字幕导出／课程复习示例，中文与英文原文 | 读者可复现，提供来源并自然链接对应教程 |
| 寻找相关引用 | 视频学习、字幕处理、开发者工具领域的真实维护者 | 对方因内容价值自主引用，记录来源 URL、页面主题与链接日期 |
| 维护产品目录或社区资料 | 真实功能、运行方式、费用前提 | 遵守平台规则；付费／赞助链接正确标注，不编造评价 |

维护链接台账：来源 URL、落地页、链接类型、是否付费、发现日期和有效性。上线后结合站长平台的展示、点击、索引和引荐流量评估。当前没有正式域名或合作对象，这些是待执行动作，不是已获得的反向链接。公开页面链接到源码仓库属于出站引用，不计为其他网站给本产品的反向链接。

## 后续效果评估

以实际站长平台数据记录中文／英文页面展示、点击率、查询词、索引数量和页面体验，保留修改日期与观察窗口。八页尚未上线，当前没有自然流量基线。先验证域名、200／404、robots 和 sitemap，再观察；不要把本机自动检查通过当成已收录或排名提升。
