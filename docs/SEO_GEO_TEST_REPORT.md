# SEO 完善与 GEO 准备：开发验证报告

日期：2026-10-08。用户要求先落实五项 SEO 策略，再扩展 GEO；用户已确认平台范围、抓取偏好、Gemini 例外与尚未上线状态。方案见 [SEO 完善](SEO_REFINEMENT.md) 和 [GEO 配置](GEO_PLAN_AND_SETUP.md)。

## 最终变更

八页中英文 TDK 精简并输出每页 5 个相关关键词；保留 SSG、canonical、语言关联、JSON-LD、robots 与 sitemap。首页增加定义、事实表、适合人群及常见问题，每页增加维护与核对信息和固定提交的实现依据。

同源生成八个 Markdown 阅读副本、`llms.txt` 和 `llms-full.txt`。独立公开包从初轮的 14 个文件扩为 24 个文件，仅公开内容，不含 Vue 工作区、API、SQLite、视频、密钥或日志。搜索／用户查阅爬虫允许公开页，GPTBot 与 ClaudeBot 禁止抓取，Google-Extended 按用户明确选择允许。预览仍全站禁止抓取，正式站点地图仍只有八个 HTML URL。

本轮没有修改下载、学习、SSE 或后台模型实现，也没有新增 npm 依赖。保留用户已有工作树改动，包括示例组件删除；没有自动提交或推送。源码依据链接使用已发布提交，不把尚未提交的新文档链接当成公开证据。

## 自动验证结果

| 检查 | 本轮结果 | 主要覆盖 |
| --- | --- | --- |
| SEO 规则 | 10 项通过 | 独立 TDK、字符约束、域名、canonical、语言关系、sitemap、验证标签、预览、静态包与开发服务器边界 |
| GEO 规则 | 6 项通过 | HTML／Markdown 所有正文、表格、问答、步骤与源码引用一致；完整导出；爬虫组私有路径保留；训练限制；预览关闭；证据提交中的文件存在；不转发额外秘密参数 |
| 公开页面浏览器 | 38 项通过 | 八页真实 DOM 元数据、JSON-LD、390／320px 布局、内部链接、XML、禁用 JS 的阅读、Markdown 内容一致性及真实生成 robots 的规则语义 |
| 原同屏工作区模拟回归 | 13 项通过 | 下载与自动总结、已保存复用、刷新／语言恢复、开关偏好、无字幕、未配置模型、错误恢复、移动布局 |
| 前端生产构建 | 通过 | Vue／TypeScript 类型检查、Vite 工作区构建并追加公开页面 |
| 独立公开构建 | 通过 | 无正式域名时输出预览包；正式标签在隔离示例域名 fixture 中验证 |
| 文档链接与本机入口 | 通过 | 34 份 Markdown 的本地文件链接有效；8000 端口原根页、双语页与阅读／SEO 文件返回 200 |

公开浏览器流程的工作区 API 请求与页面脚本错误均为 0。同屏模拟回归页面错误为 0，使用独立本机端口、模拟平台／模型与隔离 SQLite；未调用真实模型、重新下载真实视频或写入正式学习库。

初轮 [SEO 报告](SEO_TEST_REPORT.md) 的 255 项后端、71 项完整浏览器结果属于 2026-10-07。本轮后端实现没有变动，针对新生成页面运行上述检查，并重跑 13 项同屏专项；没有把历史数量冒充本轮新执行结果。

爬虫语义检查验证本项目生成规则中的具体 group、通用 group 和最长路径匹配；不是爬虫实际访问或遵守 robots 的证明。Markdown 响应头在 Vite 开发模式验证，生产响应头取决于托管配置，静态文件不会自行设置它们。

## 本机证据

- `.local/geo-browser-test/report.json`：38 项公开浏览器检查，来源于本轮真实运行；包含测试 URL、示例 canonical、通过项、API 请求与错误记录。
- `.local/geo-browser-test/zh-desktop.png`、`zh-mobile.png`、`en-desktop.png`、`en-mobile.png`：本轮页面截图，已查看中文桌面与手机版；手机无横向溢出由浏览器尺寸检查确认。
- `.local/unified-workspace-test/results.json`：本轮 13 项模拟专项。
- `.local/geo-public-site/`：隔离正式标签 fixture，域名为 `https://saveany.example.test`，仅用于本机测试，不能部署为正式网站。
- `.local/geo-build-tests/` 与 `.local/seo-build-tests/`：单元检查生成的隔离目录。

日志、截图和数据库均为忽略 Git 的本机产物。测试服务只监听本机，与用户的 8000 端口分离；验证结束清理自己启动的服务，保留正式本机服务。

## 复现

在仓库根目录执行：

```powershell
npm.cmd run test:seo --prefix frontend
npm.cmd run test:geo --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run build:site --prefix frontend
node --experimental-strip-types --input-type=module -e "import { buildSeoSite } from './frontend/seo/build.ts'; await buildSeoSite('.local/geo-public-site', {siteUrl:'https://saveany.example.test'}, true)"
python -m http.server 8189 --bind 127.0.0.1 --directory .local/geo-public-site
```

在另一个配置好 Playwright／Microsoft Edge 的终端运行：

```powershell
$env:SEO_TEST_OUTPUT = '.local/geo-browser-test'
node frontend/tests/seo-e2e.cjs
```

本次使用 Codex 已提供的 Playwright 运行时，通过终端 `NODE_PATH` 指定模块目录，没有加入生产依赖或把本机模块路径写入项目。Node 需满足现有项目版本要求。原功能模拟 fixture 和命令见 [TESTING](TESTING.md)。

## 人工与上线验收

本机人工验收：打开 `/zh/`、`/en/`，检查文案、支持范围、问答与 Markdown；回到 `/`，确认原下载／学习操作仍符合预期。默认没有正式域名，页面不参与收录，这是当前预期状态。

待上线后确认：实际域名与 TLS、200／404、托管响应头与缓存、WAF、站长平台验证、sitemap 提交、真实索引、线上性能及九个平台的检索／引用／推荐。问题集与空白记录模板见 [GEO_EVALUATION](GEO_EVALUATION.md)。本轮没有真实 AI 可见性数据，不能证明“各个 AI 优先看到”已发生。
