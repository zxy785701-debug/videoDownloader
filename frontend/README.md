# SaveAny frontend

Vue 3 + TypeScript + Vite provide the local download and learning workspace. Public Chinese and English pages are generated as static HTML from `seo/content.ts`.

- `npm run dev`: workspace development with the existing `/api` proxy.
- `npm run build`: type-check and build the workspace; append public pages to `dist/`.
- `npm run build:site`: build only the public pages into `site-dist/`, without app APIs or learning data.
- `npm run test:seo`: check domain validation, localized metadata, sitemap, preview indexing rules and output boundaries.
- `npm run test:geo`: check reading parity, public-data boundaries, crawler policy and committed implementation references.

Public pages default to `noindex` until the real HTTPS origin is configured as `SEO_SITE_URL` in the build environment or `.env.production.local`. The local workspace always uses `noindex`; its existing hash routes remain available. The Vue dev server also serves `/zh/` and `/en/` as static preview pages and always disables their indexing, even when a production domain is configured.

See [setup and publishing](../docs/SEO_SETUP.md), [SEO audit](../docs/SEO_PLAN_AND_AUDIT.md), [SEO tests](../docs/SEO_TEST_REPORT.md) and [app regression instructions](../docs/TESTING.md).
The same public content also generates eight `index.md` files, `llms.txt` and `llms-full.txt`. See [SEO refinement](../docs/SEO_REFINEMENT.md), [GEO policy and setup](../docs/GEO_PLAN_AND_SETUP.md), [visibility evaluation](../docs/GEO_EVALUATION.md) and [current validation](../docs/SEO_GEO_TEST_REPORT.md). Search/user retrieval is allowed in production, GPTBot and ClaudeBot are blocked, and Google-Extended is explicitly allowed by owner choice for Gemini grounding and training.
