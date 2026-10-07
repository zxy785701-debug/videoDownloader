# 项目文档导航

更新日期：2026-10-07。代码以当前仓库为准，旧方案和测试报告保留各阶段事实；当前交互和协议以本页链接的最新说明为准。

## 当前版本

| 文档 | 用途 |
| --- | --- |
| [运行说明](README.md) | 安装依赖、个人本机启动、配置和常见使用方式 |
| [项目总结](PROJECT_SUMMARY.md) | 功能范围、架构、代码入口、API、配置与证据边界 |
| [同屏工作区方案](UNIFIED_VIDEO_WORKSPACE_PLAN.md) | 用户确认的布局、自动总结规则、兼容性和状态约束 |
| [同屏工作区开发及验收](UNIFIED_VIDEO_WORKSPACE_TEST_REPORT.md) | 最终实现、255 项后端回归、71 项模拟浏览器流程、布局及真实记录副本验证 |
| [回归执行说明](TESTING.md) | 隔离测试命令、浏览器依赖、真实调用探针的区别 |

当前流程为“解析视频 → 显示下载信息 → 获取平台字幕 → 按提交时的开关选择自动总结”。已保存摘要复用，失败或服务重启中断后手动重试；历史恢复、语言切换与流式重连不自动创建付费模型请求。默认开关开启且可记住关闭选择，下载不等待学习任务。

## 学习功能演进

| 阶段 | 方案与证据 |
| --- | --- |
| 最初的 AI 学习扩展 | [方案](AI_VIDEO_SUMMARY_PLAN.md)、[竞品研究](AI_VIDEO_SUMMARY_COMPETITOR_RESEARCH.md)、[测试报告](AI_VIDEO_SUMMARY_TEST_REPORT.md) |
| 导图阅读与文件导出 | [方案](MINDMAP_SUBTITLE_ENHANCEMENT_PLAN.md)、[验收报告](MINDMAP_SUBTITLE_ENHANCEMENT_TEST_REPORT.md) |
| 视频问答 SSE | [方案](AI_QA_SSE_PLAN.md)、[测试报告](AI_QA_SSE_TEST_REPORT.md) |
| 摘要 SSE | [方案与测试](AI_SUMMARY_SSE_TEST_REPORT.md) |
| 摘要草稿保留与真实复测 | [撤回修复](SUMMARY_STREAM_RESET_FIX.md)、[真实复测](SUMMARY_STREAM_REAL_VERIFICATION.md) |

早期文档中的独立“AI 学习”页面和“先获取字幕、再点击总结”属于当时版本，现已由同屏工作区替代。历史测试数量、真实模型用量和平台样例成功记录不代表本次新增验证。

## 下载与平台维护

- [需求分析](REQUIREMENTS.md)、[下载方案与阶段记录](DOWNLOAD_PLAN.md)、[早期页面验收](UI_REDESIGN_ACCEPTANCE.md)。
- [B 站与芒果适配接入](DOWNLOAD_ADAPTER_INTEGRATION.md)、[B 站 Firefox 验证](BILIBILI_FIREFOX_TEST_REPORT.md)、[芒果下载研究](MGTV_DOWNLOAD_RESEARCH.md)。
- [YouTube 配置](YOUTUBE_SETUP.md)、[YouTube 验证](YOUTUBE_TEST_REPORT.md)、[抖音验证](DOUYIN_TEST_REPORT.md)。

## 文档与数据约定

方案、实现、自动验证和人工验收分开记录。用户提出修改或确认后更新当前说明，历史报告继续保留原日期和证据范围。

`.env`、浏览器 Cookie、SQLite、下载文件、截图、探针输出及 `.local/` 运行产物留在本机；仓库保存代码、测试脚本、无密钥配置模板和可复现说明。本次自动验证已通过，同屏改版人工验收仍待用户确认。
