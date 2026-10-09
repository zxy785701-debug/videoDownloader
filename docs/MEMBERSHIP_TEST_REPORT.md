# 会员功能开发与验收报告

日期：2026-10-08。状态：代码与自动验证完成，Stripe 沙盒配置与启动检查通过，用户已测试付款；账号速度问题已修复并复测，正式邮件及完整人工验收待完成。

## 最终行为与实现

下载不限量；会员模式下普通账号每日新生成摘要 3 次，会员 30 次，北京时间零点重置。¥19.90 一次购买 30 天，不自动续费，有效期内禁止重复购买。失败释放额度，复用和导出不扣，重新生成扣一次；DeepSeek 模型费用沿用本机 Key。字幕和问答保持原行为。

新增邮箱注册、登录、重置密码、会员窗口和独立会员服务；按用户最新要求，注册及登录暂不要求邮箱验证，注册也不生成或发送验证邮件，已有未验证账号可直接登录。保留可选验证能力，不把未验证邮箱误记为已验证。本机视频、字幕、摘要、Cookie 和模型 Key 不上传。未配置会员地址时保留个人模式，配置后才开启新摘要账号与额度门槛。防绕过边界、隐私及业务规则见 [已确认方案](MEMBERSHIP_STRIPE_PLAN.md)。

入口为 `backend/billing/`、`backend/app/membership_client.py`、`backend/app/membership_routes.py`、`frontend/src/membership/MemberPanel.vue` 和 `start-membership.ps1`。Stripe SDK 固定为 `16.0.0`，本次默认 API 版本 `2026-09-30.endive`；本机代理不导入 Stripe，密钥只属于独立服务。

服务端固定 Price、1990 分人民币、数量 1；一个账号一个未解决订单，固定幂等键，响应丢失或重启复用原单，未知旧单禁止盲目重建。Webhook 验证原始体签名和环境，再查询 Stripe 当前状态并核对账号、订单、金额、商品；授权绑定订单唯一。成功跳转和未付款完成事件不能开通权益。

全额成功退款撤销对应授权，部分退款保持权益；争议按最新状态处理。异步支付失败且旧付款未安全结束时转人工核实，不调用不适用的 Checkout PaymentIntent 取消接口。额度事务预留，摘要保存与任务成功状态原子提交，持久化待办支持断网和重启补记，结算归原日期。

## 自动验证结果

| 验证 | 本轮结果 | 范围 |
| --- | --- | --- |
| 全部后端 | 298 通过 | 原 255 项＋43 项会员测试，隔离 SQLite、假支付与假模型；本次连接与初始化修复后完整回归 |
| 会员浏览器 | 26 通过 | 无验证与开启验证两种模式各 13 项；两服务、真实本机代理和 Vue；注册、登录、拒付、同单继续、开通、退出、本机重置邮件和访客解析 |
| 初始化与迟到响应 | 7 通过 | 设置请求未返回时入口与登录仍可用；并发请求合并、旧状态和旧 401 不覆盖新登录；个人模式不请求远端 |
| 会员布局复核 | 3 通过 | 1280、390、320 像素，截图人工查看，无横向溢出 |
| 原同屏浏览器 | 13 通过 | 个人模式的自动／手动摘要、字幕、复用、下载、历史、失败和响应式布局 |
| SEO／GEO 规则 | 10＋6 通过 | 公开包、阅读导出与爬虫边界 |
| 前端和独立公开构建 | 通过 | 本次 Vue、TypeScript 构建通过；独立公开构建沿用前次通过结果，本次未修改公开页面 |

新增测试覆盖并发与未知创建、固定 Stripe SDK 实际请求头和参数、重复／篡改／过期签名、9 种付款不匹配、未付款跳转、退款、争议、异步失败安全状态、并发额度、午夜、会员到期、失败、缓存、自动接续和断网恢复。

2026-10-08 注册调整追加 6 项后端用例：无验证注册不调用邮件、未验证账号可使用免费额度与购买会员、已有未验证账号登录、重复注册不改密码、重新启用验证约束旧会话、环境开关解析，以及本机／SMTP 提示不泄露账号是否存在。默认关闭验证，设置 `BILLING_REQUIRE_EMAIL_VERIFICATION=true` 后可恢复验证要求。密码重置仍使用有时限的单次邮件令牌；未配置 SMTP 的邮件只保存在本机，界面不再声称已发送到真实邮箱。

最新证据目录为 `.local/pytest-membership-performance-complete-20261008/`、`.local/membership-performance-20261008-run1/` 和 `.local/membership-performance-verify-20261008-run1/`，两种浏览器模式各有报告、耗时和桌面／移动截图。原工作区、SEO／GEO 与三种尺寸布局的表中结果沿用前次验证。最新完整后端 298 项包含原功能回归；33 项会员／初始化浏览器检查无页面脚本错误。前次取消邮箱验证的证据仍保留在 `.local/pytest-registration-complete-20261008/` 等目录。

浏览器发现并修复了模拟表单被 `no-referrer` 来源保护误拦截的问题。模拟页改为 `same-origin` 并保留来源校验；真实 Stripe 模式仍为 `no-referrer`。最终成功和拒付流程已通过。

本轮无真实扣款、平台抓取或模型费用；SQLite、模拟邮件、截图和日志仅在 `.local/`。后端有一条既有 Starlette/httpx 测试客户端弃用提示，不影响通过结果。

## 重现与人工验收

### 本机 Stripe 沙盒接入检查（2026-10-08）

用户在私密配置中填好商品和沙盒凭据后，实际向 Stripe 查询 Price 与 Product，确认商品有效、价格为一次性 `1990` 分 `cny`、`livemode=false`。CLI 能读取同一价格，核对为同一个沙盒。发现配置中的 Webhook 签名密钥与本机 CLI 不一致，已替换为当前 CLI 签名密钥并复核一致；旧转发器只订阅完成通知，已补齐异步支付、过期、退款及争议通知。没有更改商品或发起付款。

实际服务通过项目启动入口重新启动：工作区 `http://127.0.0.1:8000/`，独立会员服务 `http://127.0.0.1:8010/`；支付通知转发在后台运行。健康、前端输出、账号代理、真实 Stripe 接入标志、免验证注册及访客登录门槛检查通过，启动前后公开 AI 配置一致。原 `8187` fixture 是单独的模拟验收入口，实际 Stripe 测试使用 `8000`。

诊断证据与进程标识仅在忽略目录 `.local/stripe-sandbox-runtime/` 和 `.local/stripe-setup-check.json`，CLI 日志在落盘前遮盖签名密钥。私密 `backend/.env.billing` 与根 `.env` 均受 Git 忽略规则保护。用户随后报告测试付款成功；本次读取账本确认已记录沙盒付款与退款、存在有效会员授权，通知转发有 5 次 200 响应且无拒绝。本次速度诊断未发起新付款、退款或模型调用；其他测试卡场景仍需人工验收。

### 注册、登录和刷新速度修复（2026-10-08）

原因：本机账号代理每次调用都新建 HTTPX Client，默认按代理配置创建多个 TLS 上下文。此机器一次构建耗时 8,837 毫秒，其中证书加载累计约 8,573 毫秒；独立会员服务公开配置仅需约 17 毫秒，本机代理同一接口却耗时 9,589～10,845 毫秒。前端入口还等待这个远端配置请求，登录再串行读取状态，因此延迟叠加。密码 scrypt 单次实测约 471 毫秒；没有降低加密参数。

修复：复用线程安全的 HTTPX 连接池，在工作区关闭时释放；仅已经校验为环回 HTTP 的地址不读取外部代理、不加载无用途的 CA 文件，HTTPS 仍使用默认完整证书校验及已有代理／CA 配置，继续禁止跳转。构造显式请求，不把连接池中的 Cookie 或另一账号的 Bearer 凭据带入当前请求。访客状态先判断本机会话，再处理额度待办。

本机 `/api/v1/account/config` 只检查是否已配置会员服务，详细远端选项由新增 `/settings` 读取；前端并行读取选项和账号状态，入口及表单不等待它们。重复打开弹窗合并尚在执行的初始化请求，用操作版本防止迟到的旧账号或旧 401 覆盖新登录结果。个人模式继续隐藏账号入口。

| 测量项目 | 修复后本机实测 |
| --- | --- |
| 本机入口配置，5 次 | 3.5～27.8 毫秒 |
| 远端选项经本机代理，5 次 | 41.2～55.0 毫秒 |
| 已登录状态，3 次 | 56.6～78.3 毫秒 |
| 无验证注册浏览器流程 | 448 毫秒 |
| 无验证登录至额度显示 | 881 毫秒 |
| 有验证模式注册／登录至额度显示 | 794／870 毫秒 |

前三项来自实际运行的 `8000`／`8010` 服务，账号身份和凭据未写入报告；后三项使用隔离模拟支付的两服务浏览器，账号与密码代码为实际实现，不能当作公网网络延迟保证。原始测量在 `.local/stripe-sandbox-runtime/latency-before.json`、`latency-after.json` 与两种浏览器报告中。追加三项后端测试覆盖并发连接复用、逐请求认证及 Cookie 隔离、HTTPS 校验、关闭后不重建，以及入口检查无远端依赖。[HTTPX 连接池依据](https://www.python-httpx.org/advanced/clients/)、[证书校验依据](https://www.python-httpx.org/advanced/ssl/) 已经 Context7 与官方文档核对。

先安装 `backend/requirements-billing.txt`，在 backend 执行：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests -q --basetemp=../.local/pytest-membership-new-run
```

浏览器完整验证每次使用新的 `.local` 目录。三个窗口都先在项目根目录设置以下变量，按顺序启动服务和测试；Playwright 依赖设置见 [回归说明](TESTING.md)：

```powershell
$env:MEMBERSHIP_TEST_DIR = Join-Path (Get-Location) '.local/membership-browser-new-run'
$env:MEMBERSHIP_TEST_SERVICE_URL = 'http://127.0.0.1:8190'
$env:MEMBERSHIP_TEST_APP_URL = 'http://127.0.0.1:8187'
$env:MEMBERSHIP_TEST_VERIFY_EMAIL = '0' # 默认无需验证；另建新目录并改为 1 可测试开启验证
# 窗口一
& .\backend\.venv\Scripts\python.exe -m uvicorn tests.billing_preview:app --app-dir backend --host 127.0.0.1 --port 8190 --no-access-log
# 窗口二
& .\backend\.venv\Scripts\python.exe -m uvicorn tests.membership_preview:app --app-dir backend --host 127.0.0.1 --port 8187 --no-access-log
# 窗口三
node frontend/tests/membership-e2e.cjs
node frontend/tests/membership-initialization-e2e.cjs
```

`MEMBERSHIP_LAYOUT_ONLY=1` 可在完整测试留下的账号上复核三个布局。这些 fixture 只用于本机模拟，不部署公网。

请先验收模拟购买和额度，再按 [Stripe 入门与本机测试](STRIPE_TESTING_GUIDE.md) 配置同一沙盒的私有 Key、Price 和 CLI Webhook Secret，测试成功卡、拒付、3D Secure、关闭返回页和全额退款。

当前没有公网域名。已配置 Stripe 沙盒密钥、Price 和本机 CLI 签名密钥，商品查询、服务启动及用户沙盒付款记录检查通过；尚未验收正式邮件投递或正式收款，完整沙盒场景仍待人工确认。上线事项按教程完成后才启用正式收费。
