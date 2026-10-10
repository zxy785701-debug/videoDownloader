# ASR 本地交付与测试报告

日期：2026-10-10。范围由用户确认：B站、抖音和 YouTube 增加 ASR 兜底；60 分钟只限制 ASR；原生字幕仍支持原有限制，其他平台下载保持原实现。

## 修改文件及职责

| 文件 | 作用 |
| --- | --- |
| `backend/app/asr/__init__.py` | 独立云 ASR 包 |
| `backend/app/asr/config.py` | 环境变量、资源/预算限制、识别参数指纹 |
| `backend/app/asr/providers.py` | Provider 抽象、阿里云异步文件 API、Groq 预留接口 |
| `backend/app/asr/service.py` | 原生优先调度、缓存、付费提交、原任务恢复、轮询、清理 |
| `backend/app/asr/audio.py` | 有截止时间、可取消的媒体子进程监督 |
| `backend/app/asr/audio_worker.py` | 复用平台解析/FFmpeg 定位，优先音频，转换与完整性校验 |
| `backend/app/asr/network.py` | 公网 HTTPS、DNS 固定、逐跳校验、限量分块下载 |
| `backend/app/asr/storage.py` | 官方 OSS SDK、凭证链/STS、私有 ACL、签名与删除 |
| `backend/app/asr/temporary.py` | 随机临时目录、进程间锁、磁盘检查、安全过期清理 |
| `backend/app/asr/subtitles.py` | 复用原归一化，将毫秒句子转为统一秒时间轴 |
| `backend/app/asr/store.py` | SQLite 任务 ID、两级缓存、保守预算和调用账本 |
| `backend/app/asr/maintenance.py` | 一次性用量报告与异常资源清理命令 |
| `backend/app/analysis_jobs.py` | 原字幕任务接入 ASR、默认单线程、已验证用户限流身份 |
| `backend/app/analysis_routes.py` | 传递哈希客户端地址，保留已有请求/响应字段 |
| `backend/app/analysis_store.py` | 字幕来源字段的增量迁移和持久化 |
| `backend/app/subtitle_service.py` | 原生字幕增加来源标签；Cookie 与 API 逻辑保持原实现 |
| `backend/requirements-asr.txt` | 可选 OSS/凭证依赖，不增加本地模型 |
| `backend/tests/conftest.py` | 旧测试明确禁用云兜底，继续隔离真实数据库/配置 |
| `backend/tests/test_asr.py` | 云端 Mock、安全、恢复、费用、并发、摘要与真实本地 FFmpeg 测试 |
| `backend/tests/test_asr_live.py` | 真实 OSS/Paraformer 集成入口，默认跳过 |
| `backend/tests/asr_live_support.py` | 真实上传、匿名/签名读取、云端响应、远端删除的脱敏观测及持久测试账本 |
| `backend/tests/test_asr_live_checks.py` | 10 项 Mock 回归：检查脚本、脱敏、拒绝公开对象、删除失败、未知提交保护、跨次缓存 |
| `test-asr-live.ps1` | 在已配置凭证的本地 PowerShell 中启动真实测试，不输出密钥、不重启服务 |
| `frontend/src/learning/api.ts` | 云端语音转录来源标签 |
| `frontend/src/learning/types.ts` | 兼容新增的可选字幕来源/Provider 字段 |
| `.env.example` | 无密钥环境变量示例，明确 ASR 需注入进程环境 |
| `start-local.ps1` | 分别提示 DeepSeek 总结 Key 与百炼 ASR Key 状态，不输出密钥 |
| `docs/ASR_FALLBACK.md` | 配置、安全、成本、宝塔部署/重启、资源与风险 |
| `docs/ASR_TEST_REPORT.md` | 本报告及测试证据边界 |
| `docs/README.md` | 文档入口 |
| `docs/TESTING.md` | 最新回归结果与真实集成边界 |

工作开始前已有 `frontend/src/components/HelloWorld.vue` 删除和工作流 Markdown 未跟踪状态，本次没有修改或恢复这些用户变更。没有编辑真实 `.env`、生产配置或密钥，没有提交 Git、部署或重启服务。

## 测试结果

首次开发专项：**50 passed，1 skipped**。当时跳过项是真实云端集成。前端 TypeScript 检查和 Vite 生产构建通过；ASR Python 模块编译检查通过。

完整后端回归：**518 passed、1 skipped，68.49 秒**。前端生产构建通过。保留一条既有 Starlette/httpx 弃用提示，另有两条 OSS SDK 内部 `datetime.utcnow()` 弃用提示，无失败。Windows 沙箱最初限制了 Python TestClient 的内部 socketpair，定位后在允许的本地测试权限下执行；不属于云端网络验证。

首次真实验收准备后，新增测试检查器专项与原 ASR 专项一起执行：**60 passed，8.00 秒，3 条依赖弃用提示**。这 60 项属于 Mock/本地验证。PowerShell 启动器语法检查、`git diff --check` 通过。本次只扩充测试和文档，未再次运行前端构建或声称已运行包含新增用例的完整回归。

| 用户要求 | 证据 |
| --- | --- |
| B站原生字幕可用不调用 ASR | 原生返回时验证音频/Provider 均零调用 |
| 需要登录、空字幕、解析/网络失败自动兜底 | 五种错误码 + 名义成功但无字幕内容的 Mock 用例 |
| ASR 成功复用现有总结格式 | API → 后台 ASR → 原自动总结 → 摘要与引用、字幕来源接口 |
| 超时明确状态 | 超时错误码、轮询截止时间、保留 ID 后查询原任务 |
| 缺少 Key 明确错误 | `ASR_NOT_CONFIGURED`，不开始音频下载 |
| OSS 失败清理 | 上传失败清理本地目录/随机对象，安全重试准备阶段 |
| 有限重试 | 仅免费查询/结果重试；云端明确拒绝的手动提交也有限制 |
| 重试控制重复计费 | 超时/5xx/无 ID 进入未知保护；重启查询已有 ID；失败原任务不重新提交 |
| 重复任务缓存 | 同视频免下载；同音频跨视频免计费；语言/参数改变不混用；各视频元信息保留 |
| 超长视频拦截 | 时长大于 3600 秒不上传；本地 FFmpeg 实际采样时长校验 |
| 并发资源约束 | 4 个并发调用最大只有 1 个音频执行；配置两个名额也不对同音频重复提交 |
| 原下载、Firefox、匿名 API | 完整既有回归覆盖 B站、芒果、抖音、YouTube、Cookie/API、会员、SSE |
| 安全与清理 | URL 协议/内网 DNS/重定向/敏感头、Bucket 公有拒绝、私有上传、签名时效、角色凭证、过期目录、取消杀子进程、延迟清理恢复 |

SDK 测试使用已安装的 `oss2 2.19.1` 与 `alibabacloud-credentials 1.0.12` 执行本地构造/签名，所有 OSS 网络操作 Mock。真实本地 FFmpeg 用 2 秒合成音频验证单线程 FLAC 转换和源文件删除；不代表真实语音识别质量。

## 本地代码审查

已检查付费提交前/后崩溃窗口、两并发名额的同内容竞争、取消时子进程退出、旧任务重启恢复、数据库增量迁移、原生成功路径对 OSS 故障的隔离、私有对象清理失败、估算与实际账单区分，以及跨视频缓存元信息。审查发现的问题已修正并补充针对行为的回归用例。未调用额外代理审查。

后续真实 B 站验收工具增加后，完整后端回归为 **540 passed、1 skipped，133.61 秒**。测试工具修正后相关专项 **22 passed，2.70 秒**。指定视频的登录/匿名链路已真实通过，详细文件列表、Mock 边界、耗时、内存与首次浏览器误拦截处理见 [B 站端到端验收报告](BILIBILI_ASR_E2E_REPORT.md)。

## 首次真实阿里云验收

用户于北京时间 **2026-10-10 12:05:17–12:05:26** 在自己已配置凭证的 PowerShell 中执行 `test-asr-live.ps1`。工具进程未读取用户窗口中的真实 Key/AccessKey，也未从截图、环境文件、进程内存或其他来源提取凭证。随后只读取测试生成的脱敏报告与字幕文件的结构/时间戳，核对用户提供的输出。

真实测试结果：**1 passed，8.91 秒，5 条依赖警告**。报告状态 `PASSED`，使用真实 OSS SDK 和真实 Paraformer HTTP 请求，云端部分没有 Mock；本地音频替代平台下载步骤。

| 项目 | 实测结果 |
| --- | --- |
| 音频 | `test_audio/test_audio_16k_mono.flac`，335728 字节，20 秒，16kHz，单声道 |
| OSS | `saveany-videodownloader`，北京公网 Endpoint；Bucket ACL 私有检查通过，上传成功 |
| 访问控制 | 去掉签名的匿名 GET 为 **403**；HTTPS V4 签名有效期 **900 秒**；签名读回 SHA-256 与原音频一致 |
| 百炼模型/接口 | `paraformer-v2`；真实提交 **1 次**，查询 **2 次**，均 HTTP **200**；主任务和音频子任务均 `SUCCEEDED` |
| 云任务持久化 | 已保存原任务 ID，任务状态 `ready`，提交调用次数 `1`；未在公开文档复制完整 ID |
| 字幕返回 | **4 条**，有效非空文本；时间范围 0–5.564、5.564–10.369、10.369–17.45、17.45–19.98 秒；`source=asr`、`provider=aliyun_paraformer` |
| 缓存 | 同次测试重复获取命中持久缓存，未产生额外提交或查询 |
| 清理 | 删除成功后 SDK HEAD 确认对象不存在；待清理对象 **0**；临时 UUID 音频目录已清理 |
| 费用 | 应用估算/保守预留 **¥0.0016**；云端上报计量时长 **20 秒**；实际账单金额 **未核对**（`actual_billed_cny=null`） |
| 权限/兼容性 | 本次实际执行的 ACL 查询、Put/Get/Delete/HEAD、签名及异步提交/查询均通过，没有观察到权限不足或接口不兼容 |

本地证据：`.local/asr-live-first/report.json`、`transcript.json`、`asr.sqlite3`，均位于 Git 忽略目录。报告不包含密钥、完整签名 URL、原始云端响应或识别文本；真实字幕只保存于本地字幕文件/缓存。保留账本以避免失败或重跑时盲目重复付费。

## 尚未验证的范围与限制

以下是首次 20 秒短音频测试结束时的边界。后续已补充指定 B 站视频的真实音频提取、ASR、总结、问答及浏览器验收，当前覆盖以 [B 站端到端报告](BILIBILI_ASR_E2E_REPORT.md) 为准；生产部署和目标服务器资源仍未验证。

- 已验证本地短 FLAC → 私有 OSS → 真实百炼 → 字幕 → 清理；此次没有调用 DeepSeek 总结，也未验证真实平台音频提取、长视频、STS/角色自动刷新、跨进程中断恢复或生产并发。相应恢复/费用限制由 Mock/本地回归覆盖，不能称为全部真实云端场景通过。
- 未连接生产服务器，没有修改 8000 端口、Nginx、真实密钥、线上环境变量或服务状态。
- 没有目标 2 核/2GB 服务器的内存/CPU 实测；并发测试验证排他执行，不能解释为测得了内存峰值。
- 当前 ASR 音频路径仅支持安全 HTTPS 直链/受限渐进视频；HLS/DASH 清单专有、DRM、平台拒绝媒体访问仍会明确失败。原有这些平台的下载通道不受此限制变更影响。
- 实际账单金额保留 null；应用预算不能替代云商账单限制。具体环境变量、资源估算、人工配置、部署与回滚见 [配置与部署文档](ASR_FALLBACK.md)。
