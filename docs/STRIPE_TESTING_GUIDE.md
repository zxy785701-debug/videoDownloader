# Stripe 入门、本机测试与上线操作

日期：2026-10-08。适用：香港商户、人民币 ¥19.90 一次购买 30 天、无公网域名。

## 先认识四个东西

| 名称 | 用途 | 放在哪里 |
| --- | --- | --- |
| Stripe 沙盒 | 不产生真实资金的测试环境 | Stripe 后台切换到目标沙盒 |
| Secret Key，`sk_test_…` | 会员服务调用 Stripe | `backend/.env.billing`，仅服务端 |
| Price ID，`price_…` | 标识一次性 ¥19.90 商品价格 | 同一文件；必须属于同一个沙盒 |
| Webhook Secret，`whsec_…` | 验证付款通知 | 同一文件；本机取自当前 `stripe listen` |

不要把密钥发到聊天、写到前端或提交 Git。应用使用托管 Checkout，不需要你收集银行卡号，也不需要前端 Publishable Key。沙盒密钥和正式密钥不能混用。

“没有公网域名”可以完成真实沙盒付款：浏览器、会员服务与 Stripe CLI 需要能访问 Stripe；CLI 将 Stripe 通知转发到本机。电脑完全断网时，只能完成下述模拟测试，不能完成真正的 Stripe 沙盒付款。[官方本机转发说明](https://docs.stripe.com/cli/listen)

## 第一步：先体验完全离线的模拟流程

以下命令都在项目根目录的 PowerShell 执行；依赖安装需要网络，安装好之后模拟流程不需要 Stripe 网络。

```powershell
& .\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements-billing.txt
.\start-membership.ps1 -Mock
```

另开一个窗口，在根目录已有 `.env` 追加一行（保留原来的 DeepSeek 配置）：

```dotenv
MEMBERSHIP_SERVICE_URL=http://127.0.0.1:8010
```

然后启动本机工作区。如果端口 8000 已有旧服务，先在原启动窗口按 Ctrl+C 停止旧服务，再启动：

```powershell
.\start-local.ps1
```

打开 `http://127.0.0.1:8000/`，点击“账号 / 会员”。注册自己的测试邮箱和至少 12 字符的密码，然后直接登录。当前无需邮箱验证，也不发送注册验证邮件；已有未验证账号同样可以登录。

“找回密码”仍需要重置邮件。未配置 SMTP 时，邮件只保存在 `.local/mock-billing-mail/`，真实邮箱收不到；界面会明确提示本机测试模式，用编辑器打开最新 `.eml` 读取正文重置码。若使用当前自动验收预览 `http://127.0.0.1:8187/`，对应目录为 `.local/membership-browser-20261008-final/mail/`。这些文件不要公开或提交 Git。

点击“购买会员”，弹出的页面会写明“仅限本机模拟，不会扣款”。先选择“模拟银行卡拒付”，返回刷新，会员应未开通；继续原支付页，选择“模拟付款成功”，返回点击“刷新会员状态”，应显示会员和每日 30 次额度。有效期内再购买会被禁止。

离线模拟只验证本站账号、订单、签名处理和权益业务；它不是 Stripe 扣款、支付方式或商户审核的验收。现有真实 AI 总结仍需要 DeepSeek 网络和有效 Key，自动测试使用假模型且不扣模型费用。

## 第二步：在 Stripe 沙盒创建商品

登录 [Stripe 后台](https://dashboard.stripe.com/)，切到你准备使用的沙盒。检查页面明确显示测试／沙盒，后续 CLI、Key、Price 都必须使用同一个环境。

进入商品目录，新建商品，例如“SaveAny 30 天会员”。价格类型选择**一次性**，币种选择 **CNY / 人民币**，金额填 **19.90**，不要选择每月循环收费。保存后复制 `price_…`。

进入该沙盒的 API 密钥页面，复制 Secret Key（`sk_test_…`）到本机私有配置。人民币是展示和付款币种，香港银行账户的结算币种、换汇和手续费以账户配置为准；首次正式上线前再核对 [香港价格说明](https://stripe.com/en-hk/pricing)。支付方式由 Stripe 账户和 Checkout 适用性决定，不保证支付宝或微信在未配置的账户自动出现。[支持币种说明](https://docs.stripe.com/currencies)

## 第三步：安装 CLI，并把通知转发到本机

根据 [Stripe CLI 安装说明](https://docs.stripe.com/cli) 安装 Windows 版本，确认 `stripe --version` 能显示版本。当前官方也提供 `npm install -g @stripe/cli`；如果需要组织管理员启用 CLI 权限，按后台提示操作。

```powershell
stripe login
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,checkout.session.expired,charge.refunded,refund.updated,refund.created,charge.dispute.created,charge.dispute.closed,charge.dispute.updated --forward-to http://127.0.0.1:8010/api/membership/v1/webhook
```

登录后核实 CLI 当前账号和沙盒与商品一致。`listen` 会显示一个 `whsec_…`，将它复制到下面的配置；保持此窗口运行。CLI 的签名密钥与后台注册 Webhook 的签名密钥通常不同，不能互换。

停止模拟会员服务，复制 `backend/.env.billing.example` 为 `backend/.env.billing`，在编辑器中填写：

```dotenv
BILLING_ENV=development
BILLING_PROVIDER=stripe
BILLING_PUBLIC_URL=http://127.0.0.1:8010
STRIPE_SECRET_KEY=sk_test_在本机填写
STRIPE_WEBHOOK_SECRET=whsec_当前listen提供
STRIPE_PRICE_ID=price_同一沙盒的一次性1990分人民币商品
```

不要把省略号或中文占位符当成真实值。当前注册不要求验证；开发环境未配置 SMTP 时，重置邮件写到 `.local/billing-mail/`，不会发送到真实邮箱。模拟数据库和真实沙盒数据库相互独立，需要重新注册测试账号。

后续启用邮箱验证：在会员服务的私密 `backend/.env.billing` 中设置 `BILLING_REQUIRE_EMAIL_VERIFICATION=true`，配置并验收真实 SMTP，再重启会员服务。默认值为 `false`。已有未验证账号届时需完成验证；系统不会因本次跳过验证而误记其邮箱已验证。SMTP 提交成功也不等于邮件已到达，仍需在收件箱中人工核对。

先检查商品配置，再启动会员服务：

```powershell
Push-Location .\backend
try { & .\.venv\Scripts\python.exe -m billing.cli check } finally { Pop-Location }
.\start-membership.ps1
```

检查输出 `price_valid` 应为 `true`，`simulated` 为 `false`。工作区地址仍为本机 8000；会员服务 8010、CLI 转发窗口和工作区都要保持运行。配置变化需要重启相应服务，CLI 换了签名密钥后也要更新并重启会员服务。

## 第四步：完成真实沙盒验收

在工作区注册并登录，点击购买并打开 Stripe 托管页。只使用测试银行卡：成功卡 `4242 4242 4242 4242`，未来有效期（如 `12/34`）、任意三位 CVC；拒付卡 `4000 0000 0000 0002`；需要 3D Secure 验证的卡 `4000 0000 0000 3220`。[官方测试卡](https://docs.stripe.com/testing)

| 操作 | 应看到的结果 |
| --- | --- |
| 拒付或取消 | 不开通会员；回到原支付页继续，不另建未解决订单 |
| 成功支付后直接关闭支付页 | 返回工具刷新也能开通；无需依靠成功跳转 |
| 连点、多标签页购买 | 同一未解决订单；付款成功后禁止有效期内再买 |
| Stripe 后台重发同一通知 | 不重复开通，不延长有效期 |
| 暂停 CLI，付款后恢复并刷新 | 服务端查询 Stripe 付款结果；最终只开通一次 |
| 后台对该笔付款执行全额退款并成功 | 对应会员撤销；部分退款不自动折算天数 |
| 普通账号 3 次成功新总结后再生成 | 拒绝第 4 次；失败不扣、读取／导出不扣 |

同时核对 Stripe 沙盒后台只有预期的一次付款，并在本机会员窗口记录订单标识。`stripe trigger checkout.session.completed` 创建的是 Stripe 示例商品，不一定属于本站订单；它到达接口后**不应**随意开通会员。真实购买流程与本站商品才是完整验收。[Checkout 履约说明](https://docs.stripe.com/checkout/fulfillment)

## 遇到问题时

- 创建支付页失败：先检查三项配置是否在同一沙盒、商品是否为一次性 CNY 19.90；不要改币种或金额来绕过检查。
- 付款后会员未显示：点击刷新，检查 CLI 是否仍运行、通知是否返回 2xx；若签名错误，核对当前 `listen` 的 `whsec_…`。不凭返回页面截图手动放行。
- “订单结果待核实”：创建请求可能超时但 Stripe 已经处理。保留订单，不创建新幂等键。运营者在 Stripe 后台根据订单元数据查找 Checkout Session；确认归属后运行下面的对账工具。工具会校验同一订单、商品和账号，没有强制清空待付订单的选项。
- 异步支付失败：旧会话已完成但付款未安全终止时，系统转入人工核实，暂停新付款。Checkout 关联的 PaymentIntent 通常不能直接取消，已完成会话也不能当作开放会话过期；应依据 Stripe 当前终态或联系支持处理，不调用不适用的取消接口。确认已取消／会话已过期后对账，才可创建新订单。[官方取消约束](https://docs.stripe.com/api/payment_intents/cancel)

```powershell
Push-Location .\backend
try { & .\.venv\Scripts\python.exe -m billing.cli recover-order --order 本站订单标识 --session cs_test_核实后的会话 } finally { Pop-Location }
```

若后台查不到会话，继续核对 Stripe 请求日志并联系 Stripe 支持；不要猜测“没有付款”后强制重开。Stripe 幂等结果不是永久保存，本站在原创建窗口过期后暂停自动重试。[幂等保障范围](https://docs.stripe.com/api/idempotent_requests)

若额度显示“处理中或待同步”，任务可能仍在执行或断网后等待结算。保持本机与会员服务连通，刷新状态；重启工具会释放已中断任务，已及时完成的任务会补记成功。摘要任务限两小时，逾期后不能继续生成成功结果；尚未同步的预留仍占原日额度，第二天独立重置。请保持电脑和服务器时钟准确。

## 正式上线前你还需要做什么

1. 给独立会员服务准备 HTTPS 域名和服务器；原本机下载／学习后端继续只监听本机。静态公开介绍页仍使用现有独立发布包。
2. 完成香港账户正式收款审核及银行账户设置，确认该商品和付款币种／方式适用。
3. 使用正式 Key 和正式一次性 Price，设置 `BILLING_ENV=production`、HTTPS `BILLING_PUBLIC_URL`，注册上述事件的正式 Webhook，填后台该端点的签名密钥。生产模式禁止模拟支付。
4. 配置经认证的 STARTTLS SMTP；验证邮箱、重置密码、发信域名的 SPF／DKIM／DMARC 在真实邮箱中人工验收。
5. 反向代理只公开独立会员服务，限制请求体和连接，配置访问限流、监控、数据库备份与恢复。SQLite 首版运行一个实例；多实例前迁移共享数据库。
6. 配置正式会员服务地址到本机客户端。发布清楚的会员权益、模型费另计、隐私、联系和退款条款；核对税务要求。确认这些以后才启用正式付款。

本次没有替你配置密钥、创建 Stripe 商品、开通正式收费或执行真实沙盒交易。这些步骤需要你自己的账号与本机私有配置。
