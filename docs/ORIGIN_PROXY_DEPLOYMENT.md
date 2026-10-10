# Nginx / SSH 隧道的可信来源配置

更新日期：2026-10-09。本修复只涉及主服务 8000 的来源校验、会话 Cookie 和部署验证，不开放会员 Mock 服务，不改变支付、额度或下载业务。

## 原因与修改

浏览器访问 `http://localhost:8080`，注册／登录 POST 携带相同的 Origin。SSH 只转发 TCP，不改写 HTTP 头；Nginx 的 `proxy_set_header Host $host` 传入 `Host: localhost`，没有浏览器的 8080 端口。原 `local_access()` 用 `request.url.port or 80` 生成列表，因而把可信请求误判为 `ORIGIN_FORBIDDEN`。会员和 AI 路由共用这个依赖，所以同时受影响。

新实现保留接口依赖，改为独立校验配置的 Host 和 Origin；不再从请求 URL 或 `X-Forwarded-*` 推导权限。CORS 与路由使用同一来源列表，预检也检查 Host／Origin。无 Origin 的 `/account/config` GET 成功，只代表会员已配置，不能证明浏览器 POST 的来源检查通过。

## 配置

写入**仓库根 `.env`** 或宝塔管理的**主服务进程环境变量**；进程环境优先。配置在主服务启动时读取，修改后重启 8000。不要写在前端 `VITE_*` 或会员 `.env.billing` 中。

| 变量 | 默认值／格式 |
| --- | --- |
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1`；域名／IP，不带协议、端口或路径 |
| `ACCOUNT_COOKIE_SECURE` | `false`；HTTPS 上线设为 `true`，HTTP 隧道／本地开发保持 `false` |

显式配置**替换**默认列表，不自动保留开发来源。多个值使用英文逗号，不允许空列表、空项、`*` 或通配子域名。Origin 是协议＋主机＋可选端口，不能带结尾 `/`、路径、查询、片段、用户信息、百分号编码、控制字符或多个来源。域名使用 ASCII／Punycode；浏览器按规范序列化来源（主机小写，默认 80／443 端口省略）。配置的 Host 允许规范域名、IPv4、方括号 IPv6；收到的 Host 的端口会验证合法性，但不会用来自动授权 Origin。

非法配置使服务启动失败，不会静默放宽权限；错误只回显配置名称，不打印值。Cookie 继续为 HttpOnly、SameSite=Strict、Path=/、不带 Domain；Secure 标记只取决于显式配置，不取决于代理头。Session、支付签名及幂等处理保持不变。

### Windows 本地开发

Vite 5173、FastAPI 8000 使用默认配置即可，不需要新增变量。前端继续使用 Vite 的相对路径 `/api` 代理，会员 8010 不直接暴露给浏览器。

```powershell
# 仓库根目录，两个终端分别运行
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
npm.cmd run dev --prefix frontend
```

浏览器访问 `http://localhost:5173` 或 `http://127.0.0.1:5173`。其他自定义端口须明确加入允许来源，不能依赖请求端口自动获得权限。

### 当前宝塔 + SSH 隧道

在服务器**主服务**中设置以下变量，重启 8000：

```dotenv
ALLOWED_ORIGINS=http://localhost:8080
ALLOWED_HOSTS=localhost,127.0.0.1
ACCOUNT_COOKIE_SECURE=false
MEMBERSHIP_SERVICE_URL=http://127.0.0.1:8010
```

如还要在浏览器使用 `http://127.0.0.1:8080`，将其也加入 `ALLOWED_ORIGINS`；若需浏览器直接打开服务器 8000，同样显式加入对应来源。CLI 无 Origin GET 不需要这个额外来源。

```powershell
# Windows 保持连接，仅在 Windows 回环地址监听
ssh -L 127.0.0.1:8080:127.0.0.1:80 root@47.111.14.10
```

打开 `http://localhost:8080`。两个 FastAPI 服务继续只绑定 `127.0.0.1:8000`／`127.0.0.1:8010`，安全组与系统防火墙不放行这两个端口。Mock 阶段的工作区入口也应限制为 SSH 隧道／身份访问网关：使用专用回环 Nginx 监听，或给站点加入网络／访问控制。仅将允许来源设为 localhost，不会阻止互联网客户端伪造请求头。

### 正式 HTTPS 域名

以下是占位示例，必须替换为真实域名：

```dotenv
ALLOWED_ORIGINS=https://saveany.example
ALLOWED_HOSTS=saveany.example
ACCOUNT_COOKIE_SECURE=true
MEMBERSHIP_SERVICE_URL=http://127.0.0.1:8010
```

这适用于 Nginx 保留原域名 Host 的部署；若管理员刻意改成内部 Host，需明确加入那个 Host。不同子域名逐一配置，正式环境移除开发来源。前端和 API 建议仍用同一站点 `/api/`，保留现有 SameSite=Strict Cookie 行为，本次不实现跨站 Cookie 登录。即使 Nginx 到后端使用 HTTP，浏览器收到的登录 Cookie 也会带 Secure，已有 Cookie 由 Nginx 转发到后端验证。

## 是否需要改 Nginx

**解决本次 403 不必将 `$host` 换成 `$http_host`，原代理可以保留。** 换 Host 保留端口不能替代白名单；新实现不会按收到的端口自动授权。继续保留 `/api/` 路径（`proxy_pass` 后不加 `/`），不要开启 SSE 缓冲：

```nginx
location ^~ /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # 单层 Nginx 的建议：覆盖客户端自带地址头。
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

现有 `$proxy_add_x_forwarded_for` 不是本次 403 的原因。未来增加 CDN／负载均衡时，要按真实拓扑设置信任范围后再处理地址链。主服务来源检查不使用这些头。

若 Uvicorn 需要代理头处理 HTTPS 重定向／客户端信息，限定可信代理：`--proxy-headers --forwarded-allow-ips=127.0.0.1`，不要设成 `*`，也不因此把 8000 改为公网监听。来源检查和 Cookie 配置不依赖这些参数。

Nginx 只接受明确的 `server_name`，未知 Host 由独立默认站点拒绝。**不能反代 8010 到公网**，也不公开会员 `/api/membership/v1/`。静态根目录用 `frontend/dist`，不要暴露含 `.env`／数据库／`.git` 的仓库根目录。开发环境的 Mock 同源付款页现可经 8000 的登录保护路由访问，仅为服务器回环连接增加 `/dev/checkout/` location；配置与限制见 [Mock SSH 隧道修复](MOCK_CHECKOUT_SSH.md)。不要直接将该路径反代到 8010，或向公网启用它。

## 缺失 Origin 与安全边界

- Host 必须存在、合法且在名单中，重复 Host 拒绝。
- 有 Origin 时必须是单个合法且在名单内的来源；空值、`null`、重复头也拒绝。
- 无 Origin 的 curl／服务端请求继续可用，同源浏览器 GET／SSE 等请求也保留。
- 无 Origin 但标明 `Sec-Fetch-Site: cross-site` 时拒绝；带浏览器 `Sec-Fetch-*` 元数据的写操作必须有可信 Origin。
- CORS 预检同样检查这些来源头，不用 `allow_origins=["*"]`。

Host、Origin、Fetch Metadata **不是身份认证**，非浏览器客户端能伪造／省略它们。来源检查是浏览器边界；已有登录／Session 仍独立执行。本次保持 CLI 兼容性，不声称能识别所有伪造的“合法”请求头。

当前学习记录仍为共享库，学习接口不是完整的多租户服务。向陌生用户公开前，须补齐学习记录、任务、导出、问答与下载的账号归属校验、限制匿名昂贵操作；在此之前用 SSH／VPN 或身份访问网关保护整个工作区。本次来源修复不能代替公开多用户服务的权限验收。

## 确认提交后的服务器更新步骤

服务器更新前，须先由用户确认将修复提交并推送至 GitHub。仅在本地执行 `git commit` 不会更新远端；下面的 `git pull` 必须等修复已推送后再执行。Git 提交或推送本身不会部署服务器。

先备份服务器配置和数据库，检查服务器工作区有无需要保留的代码改动，不使用 `reset --hard` 覆盖它们。以下路径、systemd 服务名均为示例，需替换为现有宝塔配置：

```bash
cd /www/wwwroot/videoDownloader
git status --short
git pull --ff-only origin main

# 设置上述主服务环境变量／根 .env 后，
# 在宝塔 Python 项目／进程管理器重启“主服务 8000”。
# 只有现有服务确由 systemd 管理时，才用实际 unit 名执行：
sudo systemctl restart videodownloader.service
sudo systemctl status videodownloader.service --no-pager

# 主服务命令继续形如：
# backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend \
#   --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1

curl -i -H 'Host: localhost' -H 'Origin: http://localhost:8080' http://127.0.0.1:8000/api/v1/ai/config
```

这次无新增依赖／前端修改，不必重建 Vue，也不需重启 8010。只改主服务配置无需重载 Nginx；如调整监听／访问控制／代理，先 `sudo nginx -t`，通过后在宝塔重载 Nginx。

Windows 保持 SSH 连接后验证：

```powershell
# 预期 200
curl.exe -i -H "Origin: http://localhost:8080" http://localhost:8080/api/v1/ai/config
curl.exe -i http://localhost:8080/api/v1/account/config
# 未登录预期 LOGIN_REQUIRED 401，不能是来源 403
curl.exe -i http://localhost:8080/api/v1/account/me
# 预期 ORIGIN_FORBIDDEN 403
curl.exe -i -H "Origin: https://evil.example" http://localhost:8080/api/v1/ai/config
# 预期 HOST_FORBIDDEN 403，或先被 Nginx 默认站点拒绝
curl.exe -i -H "Host: evil.example" -H "Origin: http://localhost:8080" http://localhost:8080/api/v1/ai/config
```

再用专门的测试账号在页面注册／登录，刷新确认登录保持，退出后确认会话失效；用非敏感测试视频验证解析、流式总结和下载。不要将密码写进命令历史或共享日志。未登录／额度已尽弹窗、服务端额度规则应继续生效。

若仍 403，检查错误 code、浏览器真实 Origin、代理传入 Host、进程管理器是否覆盖了配置，及是否重启了正确的 8000 进程；不要打印整份环境、密钥或 Cookie 日志。

## 正式上线还需要

使用有效 HTTPS 证书、Secure Cookie、账号资源归属校验、登录／注册／模型任务限流和必要的 CSRF 防护；保护密钥与备份，按公网账号策略启用验证／找回邮件。需要更多无 Origin 写客户端时应采用明确服务凭据或 CSRF token，不能靠请求头判定身份。

真实付费启用独立 Stripe 正式配置、签名 webhook 与既有幂等处理，不公开 Mock 付款路径。服务器端限制模型费用／资源／并发；Nginx 限制请求体并为 SSE 保留超时。数据库和后台任务多进程一致性需要另行验收，本次不改变进程模型。

## 测试与验收状态

`backend/tests/test_access_policy.py` 新增 **105 项**：覆盖四个本地来源、隧道端口剥离／保留、自定义端口、HTTPS 代理／Cookie、恶意及畸形来源、Host 和代理头伪造、重复头、无 Origin、账号／AI 共同策略、CORS 预检、配置覆盖和非法配置关闭。只使用临时数据和模拟业务，不调用外部模型或支付。

2026-10-09 完整后端回归 **410 项全部通过**（含原 305 项），耗时 108.70 秒。保留一条既有 Starlette/httpx 弃用提示。前端未改动，无需重复构建。

```powershell
Push-Location backend
.\.venv\Scripts\python.exe -m pytest tests/test_access_policy.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
```

测试结果验证了本地代码和代理头场景，**尚未在阿里云真实 Nginx／SSH 隧道执行部署验收**；代码发布和部署后，仍需用户按上述步骤完成服务器验收。

## 官方参考

- [Nginx proxy_set_header：$host 与 $http_host](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header)
- [FastAPI：Behind a Proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)
- [Starlette：CORS 与可信 Host 中间件](https://starlette.dev/middleware/)
