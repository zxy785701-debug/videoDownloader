# SEO 配置、预览与发布

更新日期：2026-10-08。当前尚未上线，默认构建为不收录的本机预览。方案见 [SEO 审计](SEO_PLAN_AND_AUDIT.md)，初轮与本轮证据分别见 [SEO 测试报告](SEO_TEST_REPORT.md) 和 [SEO／GEO 测试报告](SEO_GEO_TEST_REPORT.md)。

## 本机预览

原启动方式不变：

```powershell
.\start-local.ps1
```

- 原工作区：`http://127.0.0.1:8000/`，原学习记录 hash 链接继续可用。
- 中文公开页面：`http://127.0.0.1:8000/zh/`。
- 英文公开页面：`http://127.0.0.1:8000/en/`。

`npm.cmd run build --prefix frontend` 同时构建工作区和静态公开页面。正文不需要 JavaScript；导航只在空闲工作区增加教程入口，不改变进行中的下载和总结布局。

前后端分开开发时，`npm.cmd run dev --prefix frontend` 也能访问 `/zh/`、`/en/` 与教程，Vite 原有工作区和 `/api` 代理保留。开发服务器始终为不收录的预览模式，即使另有正式域名配置；正式 SEO 标签只在构建中启用。

只生成独立公开站点：

```powershell
npm.cmd run build:site --prefix frontend
python -m http.server 8190 --bind 127.0.0.1 --directory frontend/site-dist
```

访问 `http://127.0.0.1:8190/zh/` 或 `/en/`。`frontend/site-dist/` 当前包含 24 个 HTML、CSS、图标、robots、sitemap 及公开内容的 Markdown／文本阅读文件，没有 Vue 工作区、后端、SQLite、视频文件、密钥或运行日志。构建使用现有 Node／Vite，不增加 npm 依赖。独立包根页是中英文语言入口，并标记 `noindex,follow`，八个语言 HTML 内容页是索引对象。阅读副本与 AI 抓取策略见 [GEO 配置](GEO_PLAN_AND_SETUP.md)。

## 正式域名配置

从 `frontend/.env.example` 复制为 `frontend/.env.production.local`，把 `SEO_SITE_URL` 填为**自己已确认的正式 HTTPS 源站地址**，如 `https://www.your-domain.com`。示例不是项目真实域名，不要把示例域名用于发布。只允许源站地址，不能附带路径、查询参数、片段、端口或登录凭据；localhost 和 IP 不接受。

该文件已被 Git 忽略。也可在构建进程设置 `SEO_SITE_URL`。Vite 的环境加载使用 `SEO_` 前缀；不会把项目根 `.env` 的 DeepSeek 密钥注入静态页面。已有 AI 配置读取方式不变。

```powershell
# 先在 frontend/.env.production.local 配置自己的 SEO_SITE_URL。
npm.cmd run build:site --prefix frontend
```

配置生效时输出“Production SEO metadata generated.”；无域名时输出“Preview mode”。无域名的页面为 `noindex,follow`、robots 为 `Disallow: /`、sitemap 无 URL，不能直接把预览包当正式 SEO 成果发布。

生成规则：

- 八个页面的 canonical 都指向各自正式 URL，中文不会统一指向英文。
- 每对页面互相声明 `zh-CN` 与 `en`，并把同主题英文页作为 `x-default`。
- sitemap 含八个可索引 URL 及对应语言关联；`lastmod` 来自内容核对日期，不是每次构建时间。
- Open Graph／Twitter 含标题、描述和语言信息；JSON-LD 只描述真实产品与页面，没有虚构评分、价格或评论。
- 本机根工作区始终 `noindex,follow`，学习记录、下载入口和文件不在 sitemap 中。

## 公网发布边界

推荐将 `frontend/site-dist/` 部署到自己的静态网站托管或 Web 服务器；网站部署、购买域名和站长账号操作尚未执行。本任务不把现有 FastAPI、本机浏览器会话和模型服务暴露到公网。

托管应支持目录 `index.html`，保证 `/zh/`、`/en/` 与所有教程直接访问返回 200。不要把不存在的 URL 回退成工作区或首页 200；配置自定义 `404.html` 时仍返回 HTTP 404。选择统一 HTTPS 与 www／非 www 形式，其他形式由服务器 301 到所选正式源站；目录 URL 统一使用尾斜杠，`/index.html` 别名可重定向至所在目录。

独立包根页保留显式语言选择。需要默认首页时，可在托管设置静态 `/` → `/en/` 或 `/zh/` 301；不要按 IP 或 Accept-Language 把搜索引擎送往不同正文。

HTML、robots、sitemap 和 `/seo/site.css` 使用短缓存或重新验证策略，内容变更后一起更新，避免新正文配上旧样式／旧域名。这里的 CSS 是固定路径，不适合一年 immutable 缓存。正文没有执行脚本、外部字体、统计像素或 API 请求；静态托管自身的访问日志仍由实际托管服务决定。

上线检查：八页 200、缺失页 404、TLS 有效、canonical／hreflang 的域名一致、robots 不再全站阻止、sitemap 仅正式公开 URL；再使用真实域名做移动性能和结构化数据检查。本机测试没有证明公网可访问、Core Web Vitals 合格或 Google 富媒体结果资格。

## 搜索引擎验证与提交

配置支持这些可选公开验证码：

```dotenv
SEO_GOOGLE_SITE_VERIFICATION=
SEO_BING_SITE_VERIFICATION=
SEO_BAIDU_SITE_VERIFICATION=
```

验证码必须来自网站所有者的实际站长账号。填写后重新构建，代码把它们作为转义后的 meta 标签加入八个公开页面及独立包根语言入口。也可采用站长平台的 DNS 验证，或在静态托管添加其指定 HTML 文件；这些验证码不注入本机 Vue 根工作区。不要把账号密码或 API 令牌填入这些字段。

- Google：在 [Search Console](https://search.google.com/search-console) 添加并验证域名属性，提交正式 `/sitemap.xml`，使用 URL 检查确认中文／英文正文与 canonical。Google 的 [域名验证说明](https://support.google.com/webmasters/answer/9008080)提供不同验证方法。
- Bing：在 [Bing Webmaster Tools](https://www.bing.com/webmasters/) 验证网站并提交 sitemap。可使用平台提供的检查报告；不要使用已下线的匿名 sitemap ping。[Bing 官方说明](https://blogs.bing.com/webmaster/2022/5/Spring-cleaning-Removed-Bing-anonymous-sitemap-submission/)
- 百度：在 [百度搜索资源平台](https://ziyuan.baidu.com/)按账号实际提供的站点验证／链接提交入口执行，并用其 [robots 检测工具](https://ziyuan.baidu.com/robots/)复核抓取权限。平台是否开放某项提交能力，以当前账号界面为准。
- 360、搜狗及其他引擎：静态 HTML、标准路径和通用 `User-agent: *` 规则可供抓取；站点提交按其当前官方渠道执行，不承诺特定引擎收录或排名。

这些账号操作还未执行，不把本机已生成 sitemap 写成已向搜索引擎提交。没有添加 IndexNow 密钥、定时推送或第三方分析服务，后续需要时再确认配置范围。

## 内容维护与复测

公开正文维护在 `frontend/seo/content.ts`，样式在 `frontend/seo/site.css`，构建规则在 `frontend/seo/build.ts`。修改相关中英文内容后更新 `contentUpdated`；同时核对语言对应关系，保持 H1、描述、正文与能力一致，不发布本机历史或问答。

```powershell
npm.cmd run test:seo --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run build:site --prefix frontend
```

SEO 浏览器脚本见 [测试报告](SEO_TEST_REPORT.md)。上线后记录搜索展示、点击、查询词、索引数和页面体验的起始值；数周后按实际数据评估，再补充有用教程。上线之前没有真实流量基线。
