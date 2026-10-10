# SSH 隧道下的同源 Mock 支付

日期：2026-10-10。只用于开发测试；不启用公网支付，不修改 Stripe 的支付和回跳逻辑。

## 问题与兼容方案

浏览器访问 Windows 的 `http://localhost:8080`，经 SSH 到服务器 Nginx 80。原 Mock Checkout 返回服务器内部 `http://127.0.0.1:8010/dev/checkout/...`，浏览器将连接 Windows 自己的 8010，因而拒绝连接。原后端 URL 校验还要求绝对地址，直接删掉域名会使订单创建失败。

现在 Mock Provider 返回严格的 `/dev/checkout/cs_test_mock_<随机标识>`。主服务 8000 新增这一条受保护的 GET/POST 路由：校验现有 Host/Origin 策略与 HttpOnly 登录会话，用账号对应的服务端 Bearer 向 8010 请求同一条页面；会员服务再次验证订单属于该账号。不会转发浏览器 Cookie、Authorization、Host 或代理头，不提供任意目标 URL 或通用会员 API 代理，也不跟随重定向。Vue 已支持 `window.open` 和链接的相对地址，无需修改支付跳转组件；Vite 开发代理补上同一路径。

旧订单中的内部绝对 URL 只在返回时转换为原 session 的同源路径。旧 Mock session、订单参数、幂等键、费用与权益记录不迁移、不删除，不因此创建新订单。已打开的旧 8010 页面应关闭，从网站会员窗口重新打开原订单。

## 安全与状态链路

- 页面只为已登录的订单所属账号提供。未知订单、其他账号及无登录访问不能读写付款页。
- Mock POST 必须带与 `BILLING_PUBLIC_URL` 完全一致的 Origin、当前付款页生成的 CSRF token 和合法表单；重复字段、额外金额/账号/状态字段及跨站操作拒绝。会员服务重启后旧表单 token 失效，重新打开原订单即可。
- “取消并返回”及拒付不发放权益、不撤销已有权益，保留原未付款订单供继续使用。页面链接始终为 `/`；GET 或 `?paid=true` 等参数不改变支付状态。
- 模拟成功先更新服务端 Mock session，再由会员服务生成通知并走原签名验证、付款核实和订单唯一授权流程。客户端不能提交会员期限或额度；同单重复提交不延长会员。
- 网站“刷新会员状态”仍查询原 `/api/v1/account/refresh`，订单查询仍通过 `/api/v1/account/me` 返回当前账号订单。购买和付款前后均保留原 3/30 次额度与禁止有效会员重复购买规则。
- Stripe 使用原绝对托管 URL、success/cancel URL、Webhook 和幂等逻辑；Stripe 模式不注册会员服务的 Mock 页面，production 配置继续禁止 Mock。

## 宝塔的最小 Nginx 增量

在实际处理 SSH 隧道请求的现有 `server` 块中增加下面一段。**代理到 8000 的受登录保护路由，不直接代理 8010。** 原 `/api/`、静态站点和 SSE 配置保留。

```nginx
# DEVELOPMENT / SSH TUNNEL ONLY. Remove when publishing the site.
location ^~ /dev/checkout/ {
    satisfy all;
    allow 127.0.0.1;
    allow ::1;
    deny all;

    client_max_body_size 2k;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 30s;
    proxy_cache off;
}
```

`proxy_pass` 后不加 `/`，保留 `/dev/checkout/` 路径。`allow`/`deny` 按连接来源限制为 SSH 在服务器建立的回环连接，不能用可伪造的请求头代替访问控制；不要配置任意来源可信的 real-IP 规则。若前面还有会把公网连接伪装成回环来源的代理，应使用专用回环监听或先修正其访问控制，再启用 Mock。指令依据：[Nginx 代理文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)、[访问控制文档](https://nginx.org/en/docs/http/ngx_http_access_module.html)。

不新增 `/api/membership/`、`/webhook`、`/health` 或整个 `/dev/` 到 8010 的 location，不放行 8000/8010 安全组端口。两服务继续绑定 `127.0.0.1`。8000 路由同样严格限制随机 Mock session 路径和 GET/POST。

## 配置与更新步骤（由管理员执行）

先确认修复已发布、备份当前配置与数据，保留已有数据库；不要强制重置服务器工作区。项目路径和服务名称以实际宝塔配置为准。

1. 在实际项目根目录检查 `git status --short` 后 `git pull --ff-only`。未发布时不要认为本地修改已更新服务器。
2. 主服务保持以下配置；如已正确设置则不用改：

   ```dotenv
   ALLOWED_ORIGINS=http://localhost:8080
   ALLOWED_HOSTS=localhost,127.0.0.1
   ACCOUNT_COOKIE_SECURE=false
   MEMBERSHIP_SERVICE_URL=http://127.0.0.1:8010
   ```

3. **独立会员服务**的非敏感配置设为：

   ```dotenv
   BILLING_ENV=development
   BILLING_PROVIDER=mock
   BILLING_PUBLIC_URL=http://localhost:8080
   ```

   `BILLING_PUBLIC_URL` 是浏览器地址，不是监听地址；没有尾部 `/`。这一步只改变 Mock 来源校验配置，不改 Stripe 密钥或真实付款配置。本次实现不支持多个 Mock 浏览器 Origin；保持浏览器统一使用 `localhost`。本机打包 UI 则设为 `http://127.0.0.1:8000`，Vite 则使用实际 `http://localhost:5173`。

4. 加入上述 Nginx 段，运行 `nginx -t`，通过后在宝塔重载 Nginx。按现有进程管理方式重启主服务 8000 和会员服务 8010，保持监听地址和端口。无新增依赖、数据库迁移或产品组件改动；服务器已有当前前端包时无需重建。
5. 保持 Windows SSH 隧道 `localhost:8080 → 服务器127.0.0.1:80`。登录测试账号，从会员窗口打开原订单，确认地址为 `http://localhost:8080/dev/checkout/...`。分别取消/返回、拒付、继续原单、模拟成功、刷新会员状态和页面刷新；确认权益仅在服务端模拟成功后开通，同单重复操作不延期。
6. 未登录或换账号不得查看原单；跨站 POST、伪造 token 和状态参数应失败。公网连接访问该 location 必须为 403。缺少 Origin、Origin 配错或 Cookie 过期时修正配置/重新登录，不删除订单，不绕过安全校验。

此文档不代表已替用户修改配置、重启服务或在阿里云执行验收。未来切换 Stripe 时移除此开发 location，使用原独立 Stripe 配置及其 Webhook 部署步骤。

## 自动化验证

`backend/tests/test_mock_checkout.py` 用真实账号代理、隔离 SQLite 与 Mock HTTP 传输覆盖同源链路、Nginx Host 去端口、原订单恢复、权限、CSRF、重复发放、过期、代理边界及 Stripe 参数。`frontend/tests/membership-e2e.cjs` 在真实本机 HTTP 服务与浏览器中覆盖注册/登录、相对跳转、取消、返回、拒付、原单继续、成功、刷新与重新加载。

`backend/tests/mock_tunnel_preview.py` 是测试专用 HTTP 代理，模拟 Nginx 的 Host 去端口；它不是 Nginx，也不应部署。三个独立终端共用以下**测试变量**，选择未占用端口和全新 `.local/` 子目录：

```powershell
$env:MEMBERSHIP_TEST_DIR = 'D:\nbproject\videoDownloader\.local\mock-tunnel-acceptance'
$env:MEMBERSHIP_TEST_SERVICE_URL = 'http://127.0.0.1:8590'
$env:MEMBERSHIP_TEST_APP_URL = 'http://localhost:8580'
$env:MEMBERSHIP_TEST_UPSTREAM_URL = 'http://127.0.0.1:8587'
$env:MEMBERSHIP_TEST_VERIFY_EMAIL = '0'
$env:ALLOWED_ORIGINS = 'http://localhost:8580'
$env:ALLOWED_HOSTS = 'localhost,127.0.0.1'
$env:ACCOUNT_COOKIE_SECURE = 'false'
$env:ASR_ENABLED = 'false'
```

分别启动 `tests.billing_preview:app`（8590）、`tests.membership_preview:app`（8587）和 `tests.mock_tunnel_preview:app`（8580），均使用 `backend/.venv/Scripts/python.exe -m uvicorn ... --app-dir backend --host 127.0.0.1 --port ...`。另一个同变量终端运行 `node frontend/tests/membership-e2e.cjs`；需要已构建前端、可解析的 Playwright 和本机 Edge。开启邮箱验证时换全新目录并将 `MEMBERSHIP_TEST_VERIFY_EMAIL=1`。

2026-10-10 本地专项：`test_mock_checkout.py`、原会员及来源控制共 **172 passed，79.77 秒**。真实 Edge 浏览器在上述三层本机 HTTP 拓扑中通过 **32 项检查**（无需邮箱验证和开启验证各 16 项），均无页面脚本错误；前端 TypeScript/Vite 构建通过。

最终完整后端回归 **585 passed、1 skipped，124.60 秒**；跳过项为显式启用的真实付费 ASR，3 条既有 Starlette/httpx 与 OSS SDK 弃用提示。`git diff --check` 通过。测试均在修改完成后运行，前期转发层响应关闭/响应头问题已修正并通过最终回归。

浏览器证据为 `.local/mock-ssh-0-20261010-46d4bd42/` 与 `.local/mock-ssh-1-20261010-991a1713/`；全部使用临时账号、模拟支付、隔离数据库。测试进程已关闭，正式 8000/8010 服务未操作。模拟代理与真实浏览器通过不代表真实 Nginx 或阿里云 SSH 验收；本机无 Nginx 可执行文件，配置仍需管理员在宝塔执行 `nginx -t`。

## 修改文件

| 文件 | 作用 |
| --- | --- |
| `backend/billing/security.py` | 随机 Mock session 的固定路径规范 |
| `backend/billing/provider.py` | 新旧 Mock session 返回同源路径，保留幂等参数 |
| `backend/billing/service.py` | 接受严格相对 Mock 路径，旧订单返回时兼容，Stripe 分支独立 |
| `backend/billing/main.py` | 订单归属、CSRF 表单、取消/拒付/成功及返回链接 |
| `backend/app/membership_client.py` | 固定支付页面的认证转发、限量响应及安全头白名单 |
| `backend/app/membership_routes.py` | 复用 Host/Origin/登录会话，受限 GET/POST 同源页面 |
| `backend/app/main.py` | 在静态站点挂载前注册支付页面路由 |
| `frontend/vite.config.ts` | 本地开发支付路径代理到 8000 |
| `backend/.env.billing.example` | Mock 浏览器 Origin 配置提示，未修改真实配置 |
| `backend/tests/test_mock_checkout.py` | 新增 24 项支付、代理、安全及 Stripe 回归 |
| `backend/tests/billing_preview.py` | 浏览器 fixture 区分内部服务地址与外部网站 Origin |
| `backend/tests/mock_tunnel_preview.py` | 仅测试的 Host 去端口 HTTP 代理 |
| `frontend/tests/membership-e2e.cjs` | 增加同源、取消、返回、订单及刷新验收 |
| `docs/MOCK_CHECKOUT_SSH.md` | 本说明、配置、部署及验证边界 |
| `docs/ORIGIN_PROXY_DEPLOYMENT.md` | 更新开发 Mock 的访问方式，继续禁止公开 8010 |
| `docs/TESTING.md` | 最新完整回归与浏览器结果 |
| `docs/MEMBERSHIP_TEST_REPORT.md` | 追加本次验收及历史结果边界 |
