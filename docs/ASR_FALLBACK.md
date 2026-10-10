# 低成本 ASR 字幕兜底：配置与宝塔部署

日期：2026-10-10。已完成本地开发及首次 20 秒短音频真实 OSS/Paraformer-v2 验收；未部署生产环境，也不代表所有视频平台音频提取均已真实验证。

2026-10-11 更新：ASR 滚动小时限额区分服务端核验的有效会员与普通账号，默认分别为 10 次与 3 次。此次只做本地开发和隔离回归，不重置既有账本，不重复真实付费验收。

## 行为与兼容范围

- B站、抖音、YouTube：先走原生字幕。没有字幕、字幕为空、登录会话不可用、字幕获取或解析失败时进入云端 ASR。
- 原生字幕成功时不提取音频、不上传 OSS、不提交 ASR。原生字幕仍沿用原来的最长 2 小时限制。
- 只有 ASR 默认限制 60 分钟。芒果 TV 及其他平台下载通道保持原实现。
- ASR 成功后保存与原系统兼容的 `{id,start,end,text}` 字幕，新增 `source`、`provider` 字段；原生为 `native_subtitle`，云端为 `asr`。时间单位为秒。
- 继续复用原来的总结、思维导图、问答、SRT/TXT 导出和自动总结接续。旧请求没有 `auto_summary=true` 时，仍需用户点击生成总结。
- ASR 没有结果时只返回真实错误，不用标题、简介或模型猜测代替转录。
- `ASR_ENABLED` 默认 `true`，关闭可恢复字幕优先的旧流程；没有 Key 时原生字幕仍正常，无字幕视频会提示管理员配置。

## Key 应写在哪里

百炼 Key、OSS 凭证及下表 ASR 参数支持 **项目根目录 `.env`**，也继续支持 Python 主后端进程的环境变量。读取顺序为：进程环境变量（包括显式空值）→ 根目录 `.env` → 默认值。只读取服务端白名单，不向进程环境全局注入、不读取网页输入；原来的 DeepSeek 配置行为不变。

本地在 `D:\nbproject\videoDownloader\.env` 追加或修改下面的配置。已有 DeepSeek、访问控制等配置应保留，不要用模板覆盖整份文件。仅在自己的文件中填写真实值，保存为 UTF-8；下方空值仅为示例：

```dotenv
ASR_ENABLED=true
ASR_PROVIDER=aliyun_paraformer
ASR_MODEL=paraformer-v2
DASHSCOPE_API_KEY=
ALIYUN_OSS_BUCKET=saveany-videodownloader
ALIYUN_OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_ACCESS_KEY_ID=
ALIYUN_OSS_ACCESS_KEY_SECRET=
# 仅使用 STS 临时凭证时填写，固定 RAM AccessKey 留空。
ALIYUN_OSS_SECURITY_TOKEN=
```

百炼 Key 填入 `DASHSCOPE_API_KEY`；专用 RAM 用户的 AccessKey ID/Secret 分别填写两个 `ALIYUN_OSS_ACCESS_KEY_*`。ECS 角色方式应同时省略/留空这两项，由官方 SDK 默认凭证链处理，SDK 自身的角色配置仍按官方规范放在进程环境或 SDK 凭证文件中。STS 临时凭证需同时填写 ID、Secret 和 Token，到期后更新。

`.env` 已被 Git 忽略，前端只使用构建后的静态目录。服务器上的 `.env` 应仅服务用户可读，不得置于对外静态目录。请勿把真实 Key 填入 `.env.example`、`VITE_*`、前端代码、仓库文档或聊天消息。宝塔仍可在 Python 项目环境变量中配置；这会覆盖 `.env` 中同名值。

本地 PowerShell 可隐藏输入，随后在同一窗口启动后端：

```powershell
$env:DASHSCOPE_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host '百炼 Key' -AsSecureString)).Password
$env:ASR_ENABLED = 'true'
# 还需设置下面的 OSS 配置。然后使用现有启动脚本或启动后端。
./start-local.ps1
```

修改 `.env` 或 Shell 变量后，需重新启动自己的本地后端；配置在 Python 启动时读取。已经用 PowerShell 设置过同名变量时，它们仍优先；切换为文件配置可关闭旧窗口，使用未设置这些变量的新窗口启动。不要打印环境变量确认密钥。百炼 Key 应属于北京地域，并具有 Paraformer-v2 权限。

可在 `backend` 目录运行 `.venv\Scripts\python.exe -m app.asr.settings` 做不联网的配置存在性检查：只输出缺少的变量名称，不输出密钥、不读取账本、不提交云任务。检查通过不代表凭证或云权限已验证。

## 所有环境变量

下表各项均支持主进程环境变量和项目根目录 `.env`；进程环境优先，修改后重启后端。真实付费测试的 `ASR_RUN_*` 授权开关不从 `.env` 读取，填写密钥不会自动触发测试。

| 名称 | 默认值 | 作用 |
| --- | --- | --- |
| `ASR_ENABLED` | `true` | 是否在原生字幕失败后开启兜底 |
| `ASR_PROVIDER` | `aliyun_paraformer` | 目前可用 Provider；`groq_whisper` 仅预留，明确报未实现 |
| `ASR_MODEL` | `paraformer-v2` | 当前支持的录音文件异步模型 |
| `ASR_MAX_DURATION_SECONDS` | `3600` | ASR 单视频最长时长，可配置 1–7200 秒 |
| `ASR_MAX_CONCURRENT_JOBS` | `1` | 跨进程 ASR/音频处理名额，可配置 1–2；2GB 服务器保持 1 |
| `ASR_MONTHLY_BUDGET_CNY` | `10` | 整个服务的月度预算/预警值；按北京时间自然月 |
| `ASR_STOP_ON_BUDGET` | `true` | 本次预估加累计保守预留超过预算时，停止新付费提交 |
| `ASR_PRICE_CNY_PER_SECOND` | `0.00008` | 单声道识别估价，管理员需随官方价格调整 |
| `ASR_USER_HOURLY_LIMIT` | `3` | 普通账号及未核验会话每滚动 60 分钟新任务/提交尝试上限，1–100；命中缓存不增加次数 |
| `ASR_MEMBER_HOURLY_LIMIT` | `10` | 服务端核验的有效会员每滚动 60 分钟上限，1–100；与每日 AI 总结额度独立 |
| `ASR_JOB_TIMEOUT_SECONDS` | `1800` | 等待名额、音频、上传、识别轮询共用截止时间，60–7200 秒 |
| `ASR_AUDIO_TIMEOUT_SECONDS` | `900` | 音频子进程最长时间，10 秒至任务总超时 |
| `ASR_POLL_INTERVAL_SECONDS` | `5` | 云端排队/运行状态查询间隔，1–60 秒 |
| `ASR_MAX_RETRIES` | `2` | 状态查询/结果获取额外重试次数，0–3；明确拒绝后的手动提交也受总次数限制 |
| `ASR_MAX_AUDIO_MB` | `120` | 转换后音频上限，单位 MiB，1–256 |
| `ASR_MAX_DOWNLOAD_MB` | `256` | 音频源/必要的低码率渐进视频下载上限，单位 MiB，1–512 |
| `ASR_SIGNED_URL_TTL_SECONDS` | `7200` | OSS HTTPS 签名时效；至少任务超时加 300 秒，最多 86400 秒 |
| `ASR_FFMPEG_THREADS` | `1` | FFmpeg 解码/编码线程数，1–2；服务器保持 1 |
| `ASR_API_BASE` | `https://dashscope.aliyuncs.com/api/v1` | 北京地域接口；也接受 `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/api/v1` |
| `ASR_TEMP_DIR` | 学习数据库旁 `asr-tmp` | 专用临时根目录，管理员不可指向公共静态资源目录 |
| `DASHSCOPE_API_KEY` | 无 | 必填，服务端百炼北京地域 Key |
| `ALIYUN_OSS_BUCKET` | 无 | 必填，已有私有 Bucket 的名称 |
| `ALIYUN_OSS_ENDPOINT` | `https://oss-cn-beijing.aliyuncs.com` | 公网地域 HTTPS Endpoint；推荐与百炼同在北京，不接受 internal Endpoint |
| `ALIYUN_OSS_ACCESS_KEY_ID` | 无 | 可选固定 RAM 凭证；推荐省略并使用官方凭证链 |
| `ALIYUN_OSS_ACCESS_KEY_SECRET` | 无 | 上一项的 Secret，禁止主账号 AccessKey |
| `ALIYUN_OSS_SECURITY_TOKEN` | 无 | 使用显式 STS 临时凭证时的 Token；静态 STS 到期需更新 |

`VIDEO_LEARNING_DB` 继续使用现有配置规则。ASR 数据库为该学习库旁的 `asr.sqlite3`，必须与学习数据一同持久保存。不要为释放预算而删除它，否则会丢失付费任务身份和缓存。

官方接口/价格依据：[Paraformer 录音文件 REST API](https://help.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api)、[百炼模型价格](https://docs.bailian.console.aliyun.com/en/model-studio/model-pricing)。当前估价对应北京录音文件单声道；按完整音频时长保守预估，60 分钟约 ¥0.288，未抵扣免费额度，未包含 OSS、网络、DeepSeek 费用。

## OSS 与最小权限

1. 管理员在北京创建/选用私有 Bucket，确认 Bucket ACL 为 private，Bucket Policy 不向匿名主体授予读取权限，也未配置公共 CDN。
2. 应用启动 ASR 前查询 Bucket ACL；非私有 Bucket 拒绝使用。每次上传同时指定对象 private ACL，不会自动修改 Bucket 或已有对象权限。
3. RAM 角色权限限定为目标 Bucket 的 `oss:GetBucketAcl`，及 `asr/*` 前缀的 `oss:PutObject`、`oss:GetObject`、`oss:DeleteObject`。指定上传对象 ACL 时还需 `oss:PutObjectAcl`。不得授予不相关 Bucket 管理权限。
4. 优先使用 ECS RAM 角色/官方默认凭证链，支持 SDK 刷新凭证；其次使用 STS；最后才是专用 RAM 用户固定 Key。省略 `ALIYUN_OSS_ACCESS_KEY_ID` 时自动采用官方凭证链。其角色/STS 环境配置遵循[官方 OSS 凭证文档](https://help.aliyun.com/en/oss/developer-reference/python-sdk-v1/)。角色凭证剩余寿命也会限制签名 URL 实际可用时间。
5. 给 `asr/` 前缀设置 **1 天后删除的 OSS 生命周期规则**，兜底处理断电、进程强杀和长时间网络故障。规则由管理员在 OSS 控制台配置，应用不会改 Bucket 生命周期。

签名 URL 只发送给识别服务，不进入前端、数据库或生产日志。应用只保存随机对象键和云端任务 ID。安全下载会逐次校验重定向并将连接固定到已验证的公网 IP；FFmpeg 只读本地文件，禁用网络和清单型媒体输入。现有 yt-dlp/平台元信息请求及浏览器 Cookie 边界仍沿用原实现，不应把新增下载校验描述为重写了所有旧提取器网络行为。

## 任务、缓存、重试与费用

- 复用现有 `AnalysisEngine`、SQLite 学习任务状态和线程池，默认 1 个执行线程，保留原队列容量 12。长任务在后台运行，HTTP 创建请求返回 202。
- 音频提取运行于短生命周期子进程，不是新增常驻 worker。优先音频直链；无独立音频时才尝试受大小限制的渐进视频。仅有 HLS/DASH 清单、DRM、无有效公开直链时明确失败；本阶段不承诺这些视频可转录。
- 转为 16kHz、单声道 FLAC，去掉媒体标签，文件分块读写。校验元信息时长、转换后实际时长、文件上限和下载完整性，不截断后伪装完整字幕。
- 缓存键包含 Provider、模型、识别语言/参数、音频处理版本及规范化音频 SHA-256；另建视频 URL/分 P 与参数索引。同视频可直接复用，不同视频的相同音频也不重复计费；标题、视频来源各自保留。
- SQLite 费用预留事务与 OS 文件锁共同限制并发和重复提交。未提交前失败释放预留；超预算时不上传或提交新任务，允许复用结果/查询原任务。
- 提交前保存 `submitting`，收到结果立即保存任务 ID。网络超时、5xx、响应缺少 ID、保存 ID 前进程崩溃均视为未知，保留预算预留，禁止盲目重提。
- 已知 ID：重试先查询原任务。查询/下载识别结果有限重试。云端任务失败不会自动创建新的付费任务。
- 云端明确拒绝受理（例如 401、429）可在修正后手动重试，次数和用户限流仍生效；不自动重试付费 POST。
- 重启沿用旧系统的 `interrupted` 状态与手动“重试获取字幕”。不会自动重新消费历史任务；重试可恢复查询保存的云端 ID。百炼结果保存时效有限，过期后明确提示，不自动重提。
- 有账号登录时，通过服务端会员服务验证账号后使用哈希账号标识限流；只有服务端返回的有效会员到期时间才启用会员限额。不接受网页提交的会员标志、到期时间或限额。会员到期、撤销或普通账号使用普通限额；会话失效或会员服务无法核验时回退到哈希客户端地址与普通限额。应用不会自行信任转发头。ASGI 服务器的代理信任设置必须正确；未区分匿名用户时，同一 Nginx 地址共享保守上限。

### ASR 小时限额与会员额度

ASR 小时限额用于控制云端转录尝试，与会员服务的每日 AI 总结额度（普通账号 3 次、会员 30 次）分别计算。有效会员默认每滚动 60 分钟 10 次 ASR，普通账号/未核验会话默认 3 次。服务端身份在进入 ASR 兜底时核验；原生字幕不查询会员状态，不计 ASR 次数。

小时计数沿用既有 `asr.sqlite3`：升级或撤销会员不会更换账号哈希，也不会清空先前记录。缓存和已保存云任务的恢复查询不增加新提交次数；费用预留成功后，即使 OSS 上传失败，也可能占一次限流记录，这不等于云厂商已收费。在预留之前失败的分享页解析、音频提取不占次数。次数达到上限时，提示会明确说明类别、滚动 60 分钟和实际配置的上限。

服务总月度预算仍默认 10 元，会员也受此约束；应用限制不替代云厂商账单限制。修改限额不改变缓存指纹、任务 ID 或月度费用记录。已有失败学习记录不会在更新后自动重跑，未知付费任务继续阻止重复提交。

本次更新只需管理员拉取代码并重启现有 8000 单进程后端。可在项目根目录 `.env` 明确写入下列非敏感项，不填写时使用相同默认值。进程环境中同名配置仍优先；不需要改前端、Nginx、8010 会员服务或数据库。

```dotenv
ASR_USER_HOURLY_LIMIT=3
ASR_MEMBER_HOURLY_LIMIT=10
```

查看无密钥输出的应用用量报表：

```bash
cd /www/wwwroot/videoDownloader/backend
.venv/bin/python -m app.asr.maintenance usage
```

报表分别记录 `submission_attempts`、`accepted_tasks`、`estimated_cny`、`budget_reserved_cny`、`reported_seconds`、`actual_billed_cny`。实际账单没有接入自动对账，因此 `actual_billed_cny` 保持 null，**不得把估算或计量时长称为真实账单金额**。未知/在途请求跨月仍保守占用预算。此预算只覆盖应用已记录的识别任务，无法覆盖同账号其他调用、价格调整、外部请求及 OSS/LLM 费用，不能代替云服务商预算、账单告警或费用限制。

遇到 `ASR_SUBMISSION_UNKNOWN` 时，管理员先在百炼核对提交时间、模型、对象及账单。只有确认对应关系后才能人工对账/修复任务记录；不要直接删除缓存或把状态重置成可提交。删除前端学习记录不会删除 ASR 费用记录。

## 清理与资源上限

完成、失败、取消会终止自己的音频进程并清理临时目录和 OSS 对象。OSS 删除失败会保留清理义务，下次 ASR 或以下维护命令重试。启动/处理前回收专用目录中超过 24 小时的 UUID 目录；不会遍历链接或删除根目录外的文件。

本地取消或超时不保证已受理云端任务停止运行或计费，不释放未知费用预留。若排队任务尚未读取音频，清理对象可能导致原云端任务失败；后续仍查询原任务，不能以清理为理由自动重新提交。

```bash
cd /www/wwwroot/videoDownloader/backend
.venv/bin/python -m app.asr.maintenance cleanup
```

管理员可在宝塔计划任务中每小时运行一次上述 **一次性维护命令**，并加载与主进程相同的受保护环境文件。若完全没有后续任务，需依靠此维护任务和 OSS 生命周期完成异常清理。清理仍在有效时段的在途任务时保持对象，过了签名时效才回收崩溃残留。

默认最多约 256 MiB 源文件 + 120 MiB 转换音频 + 5 MiB 结果文件；下载和转换阶段会短暂同时存在源文件与 FLAC。启动处理前要求临时目录至少 600 MiB 空闲；提高文件上限时会相应提高所需空间。建议预留至少 1 GiB 可用磁盘，并监控旧下载目录。

内存预估：现有 Python 后端加临时提取进程/FFmpeg 可能使用数百 MiB，取决于视频提取器、Cookie/YouTube 插件和原应用负载。音频以 64 KiB 块读写，FFmpeg 单次内存分配限制 64 MiB，但这不是进程总内存限制。本地并发测试证明默认只有一个音频处理进入执行；**尚未测量目标 2GB 宝塔机器峰值**。既有下载任务仍用原通道，多个用户同时下载仍可能争用 CPU、磁盘及内存。不要部署多个主后端 worker：原学习任务恢复机制本就按单进程设计。

## 宝塔部署与重启步骤（需管理员自行执行）

1. 获得部署授权后，在宝塔停止现有主后端，备份源码、`learning.sqlite3` 及已有 `asr.sqlite3`；数据库应在干净停机后复制，或使用 SQLite 在线 backup。不要只复制运行中的主库而遗漏 WAL。
2. 在现有 Python 虚拟环境安装：
   ```bash
   cd /www/wwwroot/videoDownloader/backend
   .venv/bin/python -m pip install -r requirements.txt -r requirements-asr.txt
   ```
   云存储依赖单独提供；没有安装时原生字幕与下载仍可工作，ASR 返回依赖未安装错误。继续使用现有 FFmpeg/imageio-ffmpeg；无需 GPU、PyTorch、FunASR、Redis 或新端口。
3. 在宝塔主进程环境或服务器项目根目录受保护的 `.env` 中配置上述 ASR 变量、私有 OSS 和凭证；保留 `BILIBILI_METADATA_SOURCE=api` 及现有 Cookie、DeepSeek、访问域名配置。`BILIBILI_METADATA_SOURCE` 等下载参数仍按原规则放在进程环境，此次不扩展下载配置读取范围。不要复制示例中的空白 Key 覆盖真实配置。
4. 本次有字幕来源标签变更，在开发/构建环境执行 `npm run build --prefix frontend`，发布得到的原有 `frontend/dist`，沿用当前静态资源部署方式。
5. 使用原有宝塔 Python 管理器或 Supervisor 重启同一个主服务，端口保持 **8000**，worker 为 1。不要再启动一个争用 8000 的服务。无需修改 Nginx。
6. 使用项目根目录 `.env` 时由后端自动读取，现有启动命令无需变更。也可继续用受保护的 `/etc/video-downloader/asr.env`（管理员创建、0600、仓库外），由启动器加载为进程环境。下方 Supervisor 配置仅适用于后一种方式，路径/用户必须按服务器实际环境替换，并与现有启动方式二选一：
   ```ini
   [program:video-downloader]
   directory=/www/wwwroot/videoDownloader/backend
   command=/bin/bash -c 'set -a; . /etc/video-downloader/asr.env; set +a; exec /www/wwwroot/videoDownloader/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers'
   user=www
   autostart=true
   autorestart=true
   stopsignal=TERM
   stopasgroup=true
   killasgroup=true
   stopwaitsecs=45
   redirect_stderr=true
   stdout_logfile=/www/wwwlogs/video-downloader.log
   ```
   环境文件须能被指定服务用户读取，同时禁止其他用户读取。`--no-proxy-headers` 的示例对匿名用户采用共享 Nginx 地址限流；若服务器已有安全、明确的代理信任方案，可保留该方案。不要使用不受限的代理信任来区分用户。
7. 检查现有健康接口与日志，先验证有原生字幕的视频不产生 ASR 调用，再用一个短、确有讲话且无原生字幕的视频验证真实链路，最后检查 OSS 清理与费用报表。只在此人工验收通过后扩大使用。

## 本地测试与真实集成

常规测试全部 Mock 云端和平台响应；其中一个用例确实运行本地 FFmpeg，SDK 用例只进行本地签名且 Mock OSS 网络。这些均不等于真实阿里云调用成功。结果见 [ASR 测试报告](ASR_TEST_REPORT.md)。

```powershell
Push-Location backend
./.venv/Scripts/python.exe -m pytest tests -q
Pop-Location
npm.cmd run build --prefix frontend
```

真实集成入口为 `backend/tests/test_asr_live.py`，默认跳过。只有管理员显式设置进程变量 `ASR_RUN_LIVE_TESTS=1`、百炼/OSS 凭证已配置在进程环境或根目录 `.env`，且 `ASR_LIVE_AUDIO_PATH` 指向含清晰讲话的 **30 秒以内、2 MiB 以下、16kHz 单声道 FLAC** 时才会上传并产生可能的计费。不代表所有视频平台音频提取已获得真实验证。

### 第一次真实测试：本地 PowerShell

在已经配置进程凭证的同一 PowerShell 窗口运行；若凭证已写入根目录 `.env`，可从新窗口运行。不需要启动网站或重启后端，脚本本身会发起真实付费测试，须已有对应授权：

```powershell
cd D:\nbproject\videoDownloader
# 以下两项为非敏感配置；已设置也可以保持原值。
$env:ALIYUN_OSS_BUCKET = 'saveany-videodownloader'
$env:ALIYUN_OSS_ENDPOINT = 'https://oss-cn-beijing.aliyuncs.com'
.\test-asr-live.ps1
```

启动器通过 Python 统一读取进程/文件配置，仅检查百炼 Key、Bucket 是否存在和固定 ID/Secret 是否成对，不输出值、不联网验证。Endpoint 默认北京；两个固定 Key 都未配置时，允许后续 SDK 使用角色/默认凭证链，预检查不会提前获取角色凭证。STS 另需 `ALIYUN_OSS_SECURITY_TOKEN`。缺少凭证时可填写本机 `.env` 或使用本文前面的隐藏输入方式；不要打印环境变量、使用 `--showlocals` 或粘贴含凭证的截图。

启动器为测试子进程设置 `ASR_RUN_LIVE_TESTS=1`、音频绝对路径和 `ASR_LIVE_WORK_DIR`，退出时恢复这些非敏感变量。测试只在进程内设置启用 ASR、300 秒总超时、900 秒签名有效期及隔离临时目录，不修改服务配置文件或线上环境。每次运行最多提交一个新的付费任务；20 秒音频按项目当前估价约 ¥0.0016，未含 OSS/流量，也不是实际账单金额。

依次验证：私有 Bucket ACL、真实上传、去掉签名后匿名 GET 返回 403、HTTPS V4 签名与有效期、签名 GET 下载后 SHA-256 与原音频一致、异步受理并持久保存任务 ID、查询到主/子任务成功、真实字幕及秒级时间戳、重复获取命中缓存而无新请求、删除后 SDK HEAD 确认对象不存在、本地临时目录清理。

脱敏报告写入 `.local/asr-live-first/report.json`；字幕写入同目录 `transcript.json`。报告仅包含检查布尔值、HTTP 状态、白名单错误码/Request ID、云任务 ID、次数与费用估算，不含 Key、AccessKey、原始响应或签名 URL。字幕文本仅在本地字幕文件和缓存中。`PASSED` 表示本次真实提交并通过全部检查；`RESUMED_VERIFIED` 表示恢复查询原真实任务；`CACHED_VERIFIED` 表示复用已有结果，云端检查证据来自历史运行，不能称为又一次真实提交。

费用库持久保存在 `.local/asr-live-first/asr.sqlite3`（独立于主服务预算）。**失败或超时后保留整个目录，再运行同一命令**：有 ID 先查原任务，提交未知时拒绝重提。不要删除账本、换目录或反复换音频尝试规避保护。真实账单需在百炼/OSS 控制台核对，报告 `actual_billed_cny` 为 null。

若失败，查看报告的 `error_code`、`last_operation`、`failure_diagnostics`、`cloud_responses` 和 `cleanup_error`：

| 失败位置 | 优先检查 |
| --- | --- |
| `oss_bucket_acl` / `AccessDenied` | RAM 的 Bucket 级 `oss:GetBucketAcl`；Bucket 名称和北京 Endpoint |
| `oss_upload` / `AccessDenied` | `asr/*` 上的 `oss:PutObject`、`oss:PutObjectAcl`，以及 Bucket Policy 显式拒绝 |
| `oss_signed_get` | `asr/*` 上的 `oss:GetObject`、签名、系统时钟和 STS 到期 |
| `asr_submit` / 401、403 | 北京地域百炼 Key、业务空间/模型权限，Key 不应含输入提示或多余字符 |
| `asr_query` / 非 200 | 任务 ID、地域及官方异步接口兼容性；不重新提交付费任务 |
| 子任务 `InvalidFile.DownloadFailed` | 签名有效期、OSS 下载权限/网络及 STS 是否提前到期 |
| `cleanup_error` / `AccessDenied` | `asr/*` 上的 `oss:DeleteObject`；删除后 HEAD 还需 `oss:GetObject` |

测试不需要新增 `ListObjects` 或 `GetObjectAcl` 权限，不会修改 Bucket ACL、Policy 或生命周期。删除失败会将任务保留为待清理，不会将识别成功误报为全部检查成功；生命周期 1 天规则仍是异常兜底。

B 站视频信息正常但提示“音频与识别结果必须使用公开 HTTPS 地址”时，也可能是平台音轨首选地址使用了 `8082` 或 `4483` 非标准端口。ASR 提取器现会使用同一音轨已有的标准 HTTPS 备用地址，不放开内网或非标准端口访问。修复、真实音频提取证据及无需主服务重启的更新方式见 [CDN 备用地址修复报告](ASR_CDN_FALLBACK_FIX.md)。

### 真实 B 站端到端验收

已完成用户指定 `BV1HnSVY6Eho` 的登录/匿名两组真实验收：原生字幕不调用 ASR；匿名权限错误自动兜底，并验证 OSS、云端字幕、总结、问答、导图与导出。耗时、内存、费用和范围见 [B 站端到端报告](BILIBILI_ASR_E2E_REPORT.md)。未部署宝塔。

测试工具额外依赖 `backend/requirements-test-e2e.txt` 中的 psutil、可解析的 Playwright 及本机 Edge；不需要安装到生产。保留 `.local/asr-live-first/` 中的 ASR 账本、两组学习库和 LLM 提交意图账本。在已经配置百炼/OSS 和 DeepSeek 的 PowerShell 中运行：

```powershell
cd D:\nbproject\videoDownloader
.\test-bilibili-e2e.ps1 -VideoUrl 'https://www.bilibili.com/video/BV1HnSVY6Eho/'
```

默认先登录组后匿名组，前组失败即停止；可用 `-Mode Native` 或 `-Mode Anonymous` 只验证其中一组。8000 被占用时停止，不重启旧服务。测试子进程独立设置会话开关及元信息 API 模式，退出不改变正常启动配置。已保存字幕、总结和同一问题复用；未知付费请求不盲目重提。新视频或识别参数可能产生新用量，需要明确付费范围。

## 兼容性风险与回滚

- 主学习线程从默认 2 改为 1，任务等待可能变长；ASR 最长等待 30 分钟会占用这个后台名额。API 本身仍可响应，下载通道保持原状。
- 学习库只为 cues 增加两个有默认值的字段，旧数据标记为原生字幕，旧字段/返回结构保留。新前端显示“云端语音转录”。严格拒绝未知 JSON 字段的外部客户端需检查新增字段。
- ASR 缓存持久保留转录文本和费用身份，删除学习记录不会清除此账本；数据目录应保持私有并纳入备份，后续如需合规删除需专门处理身份/费用保留策略。
- 已验证本机短音频与指定 B 站视频的真实云端链路；其他视频、平台、凭证类型和服务器仍可能有地域、权限、有效期、反爬和计费差异。HLS-only/DRM/登录受限媒体有明确不支持边界。
- 紧急关闭兜底可将 `ASR_ENABLED=false` 后重启原服务。不要删除 ASR 数据库；原来的 Firefox 字幕会话和匿名 B站元信息行为均未改动。

当前本地 RAM/私有 OSS、短音频与指定 B 站视频已验收；生产仍需人工配置凭证与权限、Bucket Policy/生命周期、宝塔环境变量和经授权的服务重启、目标机器资源监控、其他真实样例验收、云账单核对及告警。生产优先使用实例角色或 STS。
