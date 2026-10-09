const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { chromium } = require('playwright')
const base = process.env.SEO_TEST_URL || 'http://127.0.0.1:8189'
const origin = process.env.SEO_TEST_ORIGIN || 'https://saveany.example.test'
const output = path.resolve(process.env.SEO_TEST_OUTPUT || '.local/seo-browser-test')
const topics = ['home', 'video-download', 'ai-video-summary', 'subtitle-download']
const route = (language, topic) => topic === 'home' ? `/${language}/` : `/${language}/guides/${topic}/`
const checks = [], errors = [], apiRequests = []
let browser, failed
async function check(name, action) {
  try { await action(); checks.push(name); console.log('PASS ' + name) }
  catch (error) { failed = { name, message: error.stack }; throw error }
}
;(async () => {
  await fs.mkdir(output, { recursive: true })
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url()) })
  const linkTargets = new Set()
  for (const language of ['zh', 'en']) for (const topic of topics) {
    const pathname = route(language, topic)
    await check('rendered SEO and JSON-LD: ' + pathname, async () => {
      const response = await page.goto(base + pathname)
      assert.equal(response.status(), 200)
      const metadata = await page.evaluate(() => ({
        language: document.documentElement.lang,
        title: document.title,
        description: document.querySelector('meta[name="description"]')?.content,
        robots: document.querySelector('meta[name="robots"]')?.content,
        canonicals: [...document.querySelectorAll('link[rel="canonical"]')].map(link => link.href),
        alternate: [...document.querySelectorAll('link[rel="alternate"][hreflang]')].map(link => ({ lang: link.hreflang, url: link.href })),
        h1: document.querySelectorAll('h1').length,
        schema: [...document.querySelectorAll('script[type="application/ld+json"]')].map(script => JSON.parse(script.textContent)),
        scripts: [...document.scripts].map(script => script.type),
        links: [...document.querySelectorAll('a[href]')].map(link => link.getAttribute('href')),
      }))
      assert.equal(metadata.language, language === 'zh' ? 'zh-CN' : 'en')
      assert.equal(metadata.h1, 1)
      assert.equal(metadata.canonicals.length, 1)
      assert.equal(metadata.canonicals[0], origin + pathname)
      assert.ok(metadata.title.includes('SaveAny') && metadata.description.length >= 40 && metadata.description.length <= 80)
      assert.equal(metadata.robots, 'index,follow,max-image-preview:large')
      assert.deepEqual(metadata.alternate, [
        { lang: 'zh-CN', url: origin + route('zh', topic) },
        { lang: 'en', url: origin + route('en', topic) },
        { lang: 'x-default', url: origin + route('en', topic) },
      ])
      assert.deepEqual(metadata.scripts, ['application/ld+json'])
      assert.equal(metadata.schema.length, 1)
      const graph = metadata.schema[0]['@graph']
      assert.equal(graph.find(item => item['@type'] === 'WebPage').url, origin + pathname)
      assert.ok(graph.some(item => item['@type'] === 'SoftwareApplication'))
      for (const href of metadata.links) if (href.startsWith('/') || href.startsWith('#')) linkTargets.add(new URL(href, base + pathname).href)
      if (topic === 'home') await page.screenshot({ path: path.join(output, language + '-desktop.png'), fullPage: true })
    })
    for (const width of [390, 320]) await check(`mobile ${width}px: ${pathname}`, async () => {
      await page.setViewportSize({ width, height: 844 })
      await page.evaluate(() => document.fonts.ready)
      const sizes = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth, main: document.querySelector('main').getBoundingClientRect() }))
      assert.ok(sizes.document <= sizes.width + 1, JSON.stringify(sizes))
      const primary = page.locator('.hero-actions .primary-link')
      const box = await primary.boundingBox()
      assert.ok(box && box.height >= 44 && box.x >= 0 && box.x + box.width <= width + 1)
      if (width === 390 && topic === 'home') await page.screenshot({ path: path.join(output, language + '-mobile.png'), fullPage: true })
    })
    await page.setViewportSize({ width: 1366, height: 900 })
  }
  await check('all internal links and section anchors resolve', async () => {
    for (const target of linkTargets) {
      const url = new URL(target)
      const response = await context.request.get(url.origin + url.pathname)
      assert.equal(response.status(), 200, target)
      if (url.hash) assert.ok((await response.text()).includes(`id="${url.hash.slice(1)}"`), target)
    }
  })
  await check('sitemap is valid XML and matches the rendered language pairs', async () => {
    const response = await context.request.get(base + '/sitemap.xml')
    assert.equal(response.status(), 200)
    const xml = await response.text()
    const data = await page.evaluate(xml => {
      const doc = new DOMParser().parseFromString(xml, 'application/xml')
      return {
        errors: doc.querySelectorAll('parsererror').length,
        urls: [...doc.querySelectorAll('url')].map(node => ({ url: node.querySelector('loc').textContent, alternate: [...node.getElementsByTagNameNS('http://www.w3.org/1999/xhtml', 'link')].map(link => ({ lang: link.getAttribute('hreflang'), url: link.getAttribute('href') })) })),
      }
    }, xml)
    assert.equal(data.errors, 0)
    assert.equal(data.urls.length, 8)
    for (const item of data.urls) {
      assert.ok(item.url.startsWith(origin))
      assert.equal(item.alternate.length, 3)
      assert.ok(item.alternate.some(link => link.url === item.url))
    }
  })
  await check('robots permits public content; private endpoints are excluded', async () => {
    const response = await context.request.get(base + '/robots.txt')
    assert.equal(response.status(), 200)
    const text = await response.text()
    assert.ok(text.includes('Allow: /\n') && text.includes('Disallow: /api/'))
    assert.ok(text.includes(`Sitemap: ${origin}/sitemap.xml`))
    assert.equal((await context.request.get(base + '/api/v1/analyses')).status(), 404)
    assert.equal((await context.request.get(base + '/not-a-real-page/')).status(), 404)
  })
  const noJsContext = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } })
  const noJsPage = await noJsContext.newPage()
  for (const language of ['zh', 'en']) for (const topic of topics) {
    await check('content works without JavaScript: ' + route(language, topic), async () => {
      const response = await noJsPage.goto(base + route(language, topic))
      assert.equal(response.status(), 200)
      assert.equal(await noJsPage.locator('h1').count(), 1)
      assert.ok((await noJsPage.locator('article').textContent()).length > (language === 'zh' ? 500 : 1500))
      await noJsPage.locator('.hero-actions .primary-link').click()
      assert.ok(noJsPage.url().endsWith('/guides/video-download/#local-setup'))
      assert.equal(await noJsPage.locator('pre code').count(), 1)
    })
  }
  await check('public reading makes no app API requests and has no browser errors', async () => {
    assert.deepEqual(apiRequests, [])
    assert.deepEqual(errors, [])
  })
  await check('GEO reading links are discoverable and Markdown preserves the visible article', async () => {
    const entities = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" }
    for (const language of ['zh', 'en']) for (const topic of topics) {
      const pathname = route(language, topic)
      await page.goto(base + pathname)
      const reading = await page.evaluate(() => ({
        alternate: document.querySelector('link[rel="alternate"][type="text/markdown"]')?.getAttribute('href'),
        index: document.querySelector('link[rel="describedby"]')?.getAttribute('href'),
        passages: [...document.querySelectorAll('article h2, article h3, article p, article li, article th, article td')].map(node => node.textContent),
        review: document.querySelector('time').dateTime,
      }))
      assert.equal(reading.alternate, origin + pathname + 'index.md')
      assert.equal(reading.index, '/llms.txt')
      const response = await context.request.get(base + pathname + 'index.md')
      assert.equal(response.status(), 200)
      const markdown = (await response.text()).replace(/\\\|/g, '|').replace(/&amp;|&lt;|&gt;|&quot;|&#39;/g, value => entities[value])
      for (const passage of reading.passages) assert.ok(markdown.includes(passage), pathname + ': ' + passage)
      assert.ok(markdown.includes(reading.review))
    }
    const index = await context.request.get(base + '/llms.txt').then(response => response.text())
    for (const language of ['zh', 'en']) for (const topic of topics) assert.ok(index.includes(origin + route(language, topic) + 'index.md'))
    const full = await context.request.get(base + '/llms-full.txt').then(response => response.text())
    assert.ok(full.includes('SaveAny 是什么？') && full.includes('What is SaveAny?'))
    assert.ok(!full.includes('/api/v1/') && !full.includes('#learn/'))
  })
  await check('retrieval bots retain private exclusions; known training bots are blocked', async () => {
    const { robotsAllowed } = await import('./robots-policy.mjs')
    const text = await context.request.get(base + '/robots.txt').then(response => response.text())
    for (const agent of ['OAI-SearchBot', 'ChatGPT-User', 'Claude-SearchBot', 'Claude-User', 'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Googlebot', 'bingbot', 'Baiduspider']) {
      assert.ok(robotsAllowed(text, agent, '/zh/'), agent)
      assert.ok(robotsAllowed(text, agent, '/llms.txt'), agent)
      for (const pathname of ['/api', '/api/v1/analyses', '/docs', '/redoc', '/openapi.json']) assert.ok(!robotsAllowed(text, agent, pathname), agent + pathname)
    }
    for (const agent of ['GPTBot', 'ClaudeBot']) assert.ok(!robotsAllowed(text, agent, '/zh/'))
  })
})().catch(error => { console.error(error); process.exitCode = 1 }).finally(async () => {
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify({ base, origin, checks, failed: failed || null, apiRequests, errors }, null, 2))
  await browser?.close()
})
