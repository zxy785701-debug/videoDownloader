# 万能视频下载总结器 · SaveAny

Vue 3 + TypeScript 前端与 FastAPI 后端，提供视频下载、平台字幕、AI 摘要、思维导图及视频问答。桌面使用视频信息与学习内容同屏的双栏工作区，解析后可自动接续总结。

项目文档统一保存在 `docs/`：

- [文档导航](docs/INDEX.md)：当前说明、方案、验证及历史记录。
- [安装、配置与运行](docs/README.md)：本机启动和开发环境。
- [项目现状与架构](docs/PROJECT_SUMMARY.md)：功能范围、代码入口和接口。
- [同屏工作区方案](docs/UNIFIED_VIDEO_WORKSPACE_PLAN.md) 与 [开发验收报告](docs/UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md)。
- [SEO 审计与方案](docs/SEO_PLAN_AND_AUDIT.md)、[公开站点配置与发布](docs/SEO_SETUP.md)、[SEO 验证](docs/SEO_TEST_REPORT.md)。
- [SEO 五项策略完善](docs/SEO_REFINEMENT.md)、[GEO 方案与抓取配置](docs/GEO_PLAN_AND_SETUP.md)、[上线后 AI 评估](docs/GEO_EVALUATION.md)、[本轮联合验证](docs/SEO_GEO_TEST_REPORT.md)。

已安装依赖时，在仓库根目录运行 `./start-local.ps1`，访问 <http://127.0.0.1:8000>。DeepSeek 配置、Firefox 会话及首次安装步骤见运行文档。

本机密钥、数据库、下载文件和 `.local/` 验收产物均不纳入 Git。自动验证通过与用户人工验收分别记录，当前同屏改版的人工验收仍待确认。

新增中英文静态介绍与教程位于 `/zh/`、`/en/`。尚未上线时默认不收录；正式域名通过 `SEO_SITE_URL` 配置。`npm.cmd run build:site --prefix frontend` 可单独生成 `frontend/site-dist/` 公开站点，不包含本机工作区和学习服务。
同一公开内容源还生成每页 `index.md`、`/llms.txt` 和 `/llms-full.txt`；AI 阅读能力与训练爬虫偏好见 GEO 文档，真实平台引用和推荐待上线后测量。

可选会员模式新增独立账号和 Stripe 支付服务：下载不限量，普通账号每日 AI 总结 3 次、会员 30 次，¥19.90 一次购买 30 天，不自动续费，模型费用沿用本机 Key。先看 [Stripe 入门与本机测试](docs/STRIPE_TESTING_GUIDE.md)；`start-membership.ps1 -Mock` 可体验模拟付款，配置 `MEMBERSHIP_SERVICE_URL` 后工作区才显示会员入口。个人模式保留原功能；[开发验收报告](docs/MEMBERSHIP_TEST_REPORT.md) 区分自动模拟与待执行的真实沙盒交易。
