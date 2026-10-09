import assert from 'node:assert/strict'
import { test } from 'node:test'
import { access, mkdir, mkdtemp, readFile, readdir, writeFile } from 'node:fs/promises'
import { createServer as createHttpServer } from 'node:http'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { createServer } from 'vite'
import { buildSeoSite, optionsFromEnv, productionOrigin, renderPage, renderRobots, renderSitemap, seoPlugin } from '../seo/build.ts'
import { labels, pagePath, pages } from '../seo/content.ts'

const origin = 'https://saveany.example.test'
const options = { siteUrl: origin }
const tempRoot = fileURLToPath(new URL('../../.local/seo-build-tests/', import.meta.url))
await mkdir(tempRoot, { recursive: true })
const output = await mkdtemp(join(tempRoot, 'generated-'))
const jsonLd = html => JSON.parse(html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1])

test('production origin validation rejects local addresses and malformed canonical bases', () => {
  assert.equal(productionOrigin(''), '')
  assert.equal(productionOrigin(` ${origin}/ `), origin)
  for (const value of ['not a URL', 'http://example.test', 'https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://host.local', 'https://app.localhost', origin + '/zh/', origin + '?a=1', origin + '#x', 'https://user:password@example.test', origin + ':8443']) {
    assert.throws(() => productionOrigin(value), /SEO_SITE_URL/)
  }
})

test('eight localized pages have unique metadata and a single descriptive H1 without executable JS', () => {
  assert.equal(pages.length, 8)
  assert.equal(new Set(pages.map(page => page.title)).size, 8)
  assert.equal(new Set(pages.map(page => page.description)).size, 8)
  for (const page of pages) {
    const markup = renderPage(page, options)
    assert.equal((markup.match(/<h1>/g) ?? []).length, 1)
    assert.ok(markup.includes(`<html lang="${labels[page.locale].language}">`))
    assert.ok(markup.includes('content="index,follow,max-image-preview:large"'))
    assert.equal((markup.match(/<script/g) ?? []).length, 1)
    assert.ok(!markup.includes('type="module"'))
    assert.ok(!markup.includes('src="/assets/'))
    assert.ok(markup.includes('SRT') && markup.includes('SaveAny'))
  }
})

test('each language uses a self canonical and reciprocal alternates for the same topic', () => {
  for (const page of pages) {
    const markup = renderPage(page, options)
    const canonical = origin + pagePath(page.locale, page.topic)
    assert.ok(markup.includes(`<link rel="canonical" href="${canonical}" />`))
    for (const [language, locale] of [['zh-CN', 'zh'], ['en', 'en'], ['x-default', 'en']]) {
      assert.ok(markup.includes(`hreflang="${language}" href="${origin + pagePath(locale, page.topic)}"`))
    }
    assert.ok(markup.includes(`property="og:url" content="${canonical}"`))
    const graph = jsonLd(markup)['@graph']
    assert.equal(graph.find(item => item['@type'] === 'WebPage').url, canonical)
    assert.equal(graph.find(item => item['@type'] === 'WebPage').inLanguage, labels[page.locale].language)
    assert.ok(!JSON.stringify(graph).includes('aggregateRating'))
    assert.ok(!JSON.stringify(graph).includes('offers'))
  }
})

test('TDK stays concise, relevant and distinct in each language', () => {
  for (const page of pages) {
    assert.ok([...page.title].length <= (page.locale === 'zh' ? 30 : 60), page.title)
    assert.ok([...page.description].length <= 80, page.description)
    assert.ok(page.title.endsWith(' | SaveAny'))
    assert.ok(page.keywords.length >= 3 && page.keywords.length <= 5)
    assert.equal(new Set(page.keywords).size, page.keywords.length)
    assert.ok(renderPage(page, options).includes(`name="keywords" content="${page.keywords.join(', ')}"`))
    assert.ok(!page.title.includes('任意视频') && !page.title.includes('every video'))
  }
})

test('preview builds do not invent a production domain or publish indexable URLs', () => {
  for (const page of pages) {
    const markup = renderPage(page)
    assert.ok(markup.includes('content="noindex,follow"'))
    assert.ok(!markup.includes('rel="canonical"'))
    assert.ok(!markup.includes('property="og:url"'))
    assert.ok(!markup.includes('hreflang="x-default"'))
  }
  assert.ok(renderRobots().includes('Disallow: /\n'))
  assert.ok(!renderRobots().includes('Sitemap:'))
  assert.ok(!renderSitemap().includes('<loc>'))
})

test('sitemap contains only the eight public URLs with language annotations and truthful lastmod', () => {
  const sitemap = renderSitemap(options)
  assert.equal((sitemap.match(/<loc>/g) ?? []).length, 8)
  assert.equal((sitemap.match(/<xhtml:link/g) ?? []).length, 24)
  for (const page of pages) assert.ok(sitemap.includes(`<loc>${origin + pagePath(page.locale, page.topic)}</loc>`))
  assert.ok(!sitemap.includes('/api/') && !sitemap.includes('#learn') && !sitemap.includes('127.0.0.1'))
  assert.ok(renderRobots(options).includes('Disallow: /api/'))
  assert.ok(renderRobots(options).includes(`Sitemap: ${origin}/sitemap.xml`))
})

test('public meta configuration escapes verification codes and never forwards unrelated env values', () => {
  const settings = optionsFromEnv({ SEO_SITE_URL: origin, SEO_GOOGLE_SITE_VERIFICATION: '"><script>alert(1)</script>', SEO_BING_SITE_VERIFICATION: 'bing-public-code', SEO_BAIDU_SITE_VERIFICATION: 'baidu-public-code', DEEPSEEK_API_KEY: 'MUST_NOT_APPEAR' })
  const markup = renderPage(pages[0], settings)
  assert.ok(markup.includes('&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;'))
  assert.ok(!markup.includes('MUST_NOT_APPEAR'))
  assert.ok(markup.includes('name="msvalidate.01" content="bing-public-code"'))
  assert.ok(markup.includes('name="baidu-site-verification" content="baidu-public-code"'))
})

test('append build preserves the original workspace and static assets', async () => {
  const dist = join(output, 'app')
  await mkdir(join(dist, 'assets'), { recursive: true })
  await writeFile(join(dist, 'index.html'), 'ORIGINAL_WORKSPACE')
  await writeFile(join(dist, 'assets', 'app.js'), 'ORIGINAL_APP_ASSET')
  await buildSeoSite(dist, options)
  assert.equal(await readFile(join(dist, 'index.html'), 'utf8'), 'ORIGINAL_WORKSPACE')
  assert.equal(await readFile(join(dist, 'assets', 'app.js'), 'utf8'), 'ORIGINAL_APP_ASSET')
  for (const page of pages) assert.ok((await readFile(join(dist, pagePath(page.locale, page.topic), 'index.html'), 'utf8')).includes(page.heading))
})

test('standalone package contains only public pages and SEO assets', async () => {
  const dist = join(output, 'site')
  await buildSeoSite(dist, { ...options, googleVerification: 'root-public-code' }, true)
  async function files(root) {
    const found = []
    for (const entry of await readdir(root, { withFileTypes: true })) {
      if (entry.isDirectory()) found.push(...await files(join(root, entry.name)))
      else found.push(join(root, entry.name))
    }
    return found
  }
  const paths = await files(dist)
  assert.equal(paths.length, 24)
  assert.ok(paths.every(path => /\.(html|css|xml|txt|svg|md)$/.test(path)))
  assert.ok((await readFile(join(dist, 'index.html'), 'utf8')).includes('Choose your language'))
  assert.ok((await readFile(join(dist, 'index.html'), 'utf8')).includes('name="google-site-verification" content="root-public-code"'))
  for (const page of pages) {
    const markup = await readFile(join(dist, pagePath(page.locale, page.topic), 'index.html'), 'utf8')
    assert.ok(!markup.includes('href="/#top"'))
    assert.ok(!markup.includes('/api/v1/'))
  }
})

test('development serves preview content, preserves root and API proxy, and does not write a build on shutdown', async () => {
  const backend = createHttpServer((_request, response) => {
    response.setHeader('Content-Type', 'application/json')
    response.setHeader('Connection', 'close')
    response.end('{"status":"mock-ok"}')
  })
  await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve))
  const target = `http://127.0.0.1:${backend.address().port}`
  const outDir = join(output, 'dev-does-not-write')
  const server = await createServer({
    configFile: false, root: fileURLToPath(new URL('../', import.meta.url)),
    plugins: [seoPlugin(options)], build: { outDir },
    server: { host: '127.0.0.1', port: 0, proxy: { '/api': { target, changeOrigin: true } } },
  })
  try {
    await server.listen()
    const base = `http://127.0.0.1:${server.httpServer.address().port}`
    for (const page of pages) {
      const response = await fetch(base + pagePath(page.locale, page.topic))
      assert.equal(response.status, 200)
      const markup = await response.text()
      assert.ok(markup.includes(page.heading))
      assert.ok(markup.includes('content="noindex,follow"'))
      assert.ok(!markup.includes('rel="canonical"') && !markup.includes('type="module"'))
    }
    const redirect = await fetch(base + '/en?source=preview', { redirect: 'manual' })
    assert.equal(redirect.status, 301)
    assert.equal(redirect.headers.get('location'), '/en/?source=preview')
    assert.ok((await fetch(base + '/robots.txt').then(response => response.text())).includes('Disallow: /\n'))
    assert.ok(!(await fetch(base + '/sitemap.xml').then(response => response.text())).includes('<loc>'))
    assert.equal((await fetch(base + '/seo/site.css')).headers.get('content-type'), 'text/css; charset=utf-8')
    for (const page of pages) {
      const reading = await fetch(base + pagePath(page.locale, page.topic) + 'index.md')
      assert.equal(reading.status, 200)
      assert.equal(reading.headers.get('content-type'), 'text/markdown; charset=utf-8')
      assert.equal(reading.headers.get('x-robots-tag'), 'noindex,follow')
      assert.ok(reading.headers.get('link').includes('rel="canonical"'))
      assert.ok((await reading.text()).includes(page.heading))
    }
    for (const path of ['/llms.txt', '/llms-full.txt']) {
      const reading = await fetch(base + path)
      assert.equal(reading.status, 200)
      assert.equal(reading.headers.get('x-robots-tag'), 'noindex,follow')
      assert.ok((await reading.text()).includes('Local preview'))
    }
    assert.ok((await fetch(base + '/').then(response => response.text())).includes('id="app"'))
    assert.equal((await fetch(base + '/api/v1/health').then(response => response.json())).status, 'mock-ok')
  } finally {
    await server.close()
    await new Promise(resolve => backend.close(resolve))
  }
  await assert.rejects(access(outDir))
})
