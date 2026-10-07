# 万能视频下载器 · SaveAny

Vue 3 + TypeScript 前端与 FastAPI 后端，提供视频下载、平台字幕、AI 摘要、思维导图及视频问答。桌面使用视频信息与学习内容同屏的双栏工作区，解析后可自动接续总结。

项目文档统一保存在 `docs/`：

- [文档导航](docs/INDEX.md)：当前说明、方案、验证及历史记录。
- [安装、配置与运行](docs/README.md)：本机启动和开发环境。
- [项目现状与架构](docs/PROJECT_SUMMARY.md)：功能范围、代码入口和接口。
- [同屏工作区方案](docs/UNIFIED_VIDEO_WORKSPACE_PLAN.md) 与 [开发验收报告](docs/UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md)。

已安装依赖时，在仓库根目录运行 `./start-local.ps1`，访问 <http://127.0.0.1:8000>。DeepSeek 配置、Firefox 会话及首次安装步骤见运行文档。

本机密钥、数据库、下载文件和 `.local/` 验收产物均不纳入 Git。自动验证通过与用户人工验收分别记录，当前同屏改版的人工验收仍待确认。
