import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'
import { contentUpdated, evidenceFor, labels, pagePath, pages, repository, topics } from './content.ts'
import type { Locale, PublicPage, Section } from './content.ts'
import { markdownPath, renderFullReadingExport, renderMarkdown, renderReadingIndex } from './reading.ts'

export interface SeoOptions {
  siteUrl?: string
  googleVerification?: string
  bingVerification?: string
  baiduVerification?: string
}
export function optionsFromEnv(env: Record<string, string>): SeoOptions {
  return {
    siteUrl: env.SEO_SITE_URL,
    googleVerification: env.SEO_GOOGLE_SITE_VERIFICATION,
    bingVerification: env.SEO_BING_SITE_VERIFICATION,
    baiduVerification: env.SEO_BAIDU_SITE_VERIFICATION,
  }
}
const sourceDir = dirname(fileURLToPath(import.meta.url))
export function productionOrigin(input = ''): string {
  const value = input.trim()
  if (!value) return ''
  let parsed: URL
  try { parsed = new URL(value) } catch { throw new Error('SEO_SITE_URL must be your HTTPS origin, without a path, query or fragment.') }
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash
    || !parsed.hostname.includes('.') || parsed.hostname.endsWith('.localhost') || parsed.hostname.endsWith('.local')
    || /^[\d.]+$/.test(parsed.hostname) || parsed.hostname.includes(':') || parsed.port) {
    throw new Error('SEO_SITE_URL must be your public HTTPS origin, without credentials, a port, path, query or fragment.')
  }
  return parsed.origin
}
export function html(value: string): string {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
}
function absolute(origin: string, path: string): string { return origin + path }
function pageFor(locale: Locale, topic: PublicPage['topic']): PublicPage {
  return pages.find(page => page.locale === locale && page.topic === topic)!
}
function alternatePaths(page: PublicPage) {
  return [
    { language: 'zh-CN', path: pagePath('zh', page.topic) },
    { language: 'en', path: pagePath('en', page.topic) },
    { language: 'x-default', path: pagePath('en', page.topic) },
  ]
}
function sectionMarkup(section: Section): string {
  const paragraphs = (section.paragraphs ?? []).map(text => `<p>${html(text)}</p>`).join('\n')
  const tag = section.ordered ? 'ol' : 'ul'
  const items = section.items ? `<${tag}>${section.items.map(text => `<li>${html(text)}</li>`).join('')}</${tag}>` : ''
  const table = section.table ? `<div class="table-scroll" role="region" aria-label="${html(section.heading)}" tabindex="0"><table><thead><tr>${section.table.headers.map(text => `<th scope="col">${html(text)}</th>`).join('')}</tr></thead><tbody>${section.table.rows.map(row => `<tr>${row.map((text, index) => index === 0 ? `<th scope="row">${html(text)}</th>` : `<td>${html(text)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''
  const questions = (section.questions ?? []).map(item => `<div class="question"><h3>${html(item.question)}</h3><p>${html(item.answer)}</p></div>`).join('\n')
  const code = section.code ? `<pre><code>${html(section.code)}</code></pre>` : ''
  return `<section id="${html(section.id)}"><h2>${html(section.heading)}</h2>${paragraphs}${table}${items}${code}${questions}</section>`
}
function structuredData(page: PublicPage, origin: string): string {
  if (!origin) return ''
  const url = absolute(origin, pagePath(page.locale, page.topic)), home = absolute(origin, pagePath(page.locale, 'home'))
  const crumbs = [{ '@type': 'ListItem', position: 1, name: labels[page.locale].home, item: home }]
  if (page.topic !== 'home') crumbs.push({ '@type': 'ListItem', position: 2, name: page.heading, item: url })
  const graph = {
    '@context': 'https://schema.org', '@graph': [
      { '@type': 'WebSite', '@id': origin + '/#website', name: 'SaveAny', url: absolute(origin, '/en/'), inLanguage: ['zh-CN', 'en'] },
      { '@type': 'SoftwareApplication', '@id': origin + '/#software', name: 'SaveAny', applicationCategory: 'MultimediaApplication', operatingSystem: 'Windows', url: home, description: pageFor(page.locale, 'home').description, sameAs: repository },
      { '@type': 'WebPage', '@id': url + '#page', url, name: page.title, description: page.description, inLanguage: labels[page.locale].language, dateModified: contentUpdated, isPartOf: { '@id': origin + '/#website' }, about: { '@id': origin + '/#software' }, breadcrumb: { '@id': url + '#breadcrumb' } },
      { '@type': 'BreadcrumbList', '@id': url + '#breadcrumb', itemListElement: crumbs },
    ],
  }
  // Escape script delimiters even though today's content is checked-in text.
  return `<script type="application/ld+json">${JSON.stringify(graph).replace(/</g, '\\u003c')}</script>`
}
function verificationMarkup(options: SeoOptions): string {
  return [
    ['google-site-verification', options.googleVerification],
    ['msvalidate.01', options.bingVerification],
    ['baidu-site-verification', options.baiduVerification],
  ].filter((pair): pair is [string, string] => !!pair[1]?.trim())
    .map(([name, value]) => `<meta name="${name}" content="${html(value.trim())}" />`).join('\n')
}
export function renderPage(page: PublicPage, options: SeoOptions = {}): string {
  const origin = productionOrigin(options.siteUrl), copy = labels[page.locale], other: Locale = page.locale === 'zh' ? 'en' : 'zh'
  const path = pagePath(page.locale, page.topic), url = absolute(origin, path)
  const canonical = origin ? `<link rel="canonical" href="${html(url)}" />\n${alternatePaths(page).map(item => `<link rel="alternate" hreflang="${item.language}" href="${html(absolute(origin, item.path))}" />`).join('\n')}` : ''
  const guides = topics.filter(topic => topic !== 'home')
  const otherLocale = labels[other].ogLocale
  return `<!doctype html>
<html lang="${copy.language}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="content-language" content="${copy.language}" />
<title>${html(page.title)}</title>
<meta name="description" content="${html(page.description)}" />
<meta name="keywords" content="${html(page.keywords.join(', '))}" />
<meta name="robots" content="${origin ? 'index,follow,max-image-preview:large' : 'noindex,follow'}" />
${canonical}
<link rel="alternate" type="text/markdown" href="${html(absolute(origin, markdownPath(page)))}" />
<link rel="describedby" href="/llms.txt" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="SaveAny" />
<meta property="og:title" content="${html(page.title)}" />
<meta property="og:description" content="${html(page.description)}" />
<meta property="og:locale" content="${copy.ogLocale}" />
<meta property="og:locale:alternate" content="${otherLocale}" />
${origin ? `<meta property="og:url" content="${html(url)}" />` : ''}
<meta name="twitter:card" content="summary" />
<meta name="twitter:title" content="${html(page.title)}" />
<meta name="twitter:description" content="${html(page.description)}" />
${verificationMarkup(options)}
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="stylesheet" href="/seo/site.css" />
${structuredData(page, origin)}
</head>
<body>
<a class="skip-link" href="#main">${copy.skip}</a>
<header class="site-header"><a class="brand" href="${pagePath(page.locale, 'home')}"><span class="brand-mark" aria-hidden="true">S</span>SaveAny</a><nav aria-label="${copy.guides}"><a href="${pagePath(page.locale, 'home')}"${page.topic === 'home' ? ' aria-current="page"' : ''}>${copy.home}</a><a href="#related">${copy.guides}</a><a href="${pagePath(other, page.topic)}" lang="${labels[other].language}" hreflang="${labels[other].language}">${copy.otherLanguage}</a></nav></header>
${origin ? '' : `<p class="preview-note">${copy.preview}</p>`}
<main id="main">
<div class="hero"><p class="eyebrow">${copy.eyebrow}</p><h1>${html(page.heading)}</h1><p class="lead">${html(page.lead)}</p><div class="hero-actions"><a class="primary-link" href="${pagePath(page.locale, 'video-download')}#local-setup">${copy.cta}</a><a class="source-link" href="${repository}">${copy.source}</a></div><p class="updated">${copy.maintainer} · ${copy.updated} <time datetime="${contentUpdated}">${contentUpdated}</time></p><a class="source-link" href="${markdownPath(page)}">${copy.markdown}</a></div>
<div class="reading-layout"><aside class="toc"><nav aria-label="${copy.toc}"><p>${copy.toc}</p><ul>${page.sections.map(section => `<li><a href="#${section.id}">${html(section.heading)}</a></li>`).join('')}<li><a href="#sources">${copy.evidence}</a></li></ul></nav></aside><article class="article">${page.sections.map(sectionMarkup).join('\n')}<section id="sources"><h2>${copy.evidence}</h2><p>${copy.evidenceNote}</p><ul>${evidenceFor(page).map(source => `<li><a href="${html(source.url)}">${html(source.label)}</a></li>`).join('')}</ul></section></article></div>
<section id="related" class="related"><h2>${copy.related}</h2><div class="guide-grid">${guides.filter(topic => topic !== page.topic).map(topic => { const guide = pageFor(page.locale, topic); return `<a class="guide-card" href="${pagePath(page.locale, topic)}"><h3>${html(guide.heading)}</h3><p>${html(guide.description)}</p><span aria-hidden="true">→</span></a>` }).join('')}</div>${page.topic === 'home' ? '' : `<a class="back-link" href="${pagePath(page.locale, 'home')}">${copy.home} · SaveAny</a>`}</section>
</main>
<footer><p>${copy.footer}</p><div><a href="${repository}">GitHub</a><a href="${repository}/tree/main/docs">${copy.source}</a>${origin ? '' : `<a href="/#top">${copy.local}</a>`}</div></footer>
</body>
</html>\n`
}
export function renderSitemap(options: SeoOptions = {}): string {
  const origin = productionOrigin(options.siteUrl)
  const urls = origin ? pages.map(page => `<url><loc>${html(absolute(origin, pagePath(page.locale, page.topic)))}</loc><lastmod>${contentUpdated}</lastmod>${alternatePaths(page).map(item => `<xhtml:link rel="alternate" hreflang="${item.language}" href="${html(absolute(origin, item.path))}" />`).join('')}</url>`).join('\n') : ''
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urls}\n</urlset>\n`
}
export function renderRobots(options: SeoOptions = {}): string {
  const origin = productionOrigin(options.siteUrl)
  if (!origin) return '# Local preview; configure SEO_SITE_URL before publishing.\nUser-agent: *\nDisallow: /\n'
  // Specific groups do not inherit the wildcard group's private-path exclusions.
  const publicRules = 'Allow: /\nDisallow: /api/\nDisallow: /api$\nDisallow: /docs\nDisallow: /redoc\nDisallow: /openapi.json\n'
  const retrievalAgents = ['OAI-SearchBot', 'ChatGPT-User', 'Claude-SearchBot', 'Claude-User', 'PerplexityBot', 'Perplexity-User', 'Google-Extended']
  const trainingAgents = ['GPTBot', 'ClaudeBot']
  return '# Public pages only. robots.txt is not access control.\n'
    + '# Google-Extended is allowed by owner choice: Gemini grounding AND training.\n'
    + `User-agent: *\n${publicRules}\n`
    + retrievalAgents.map(agent => `User-agent: ${agent}`).join('\n') + `\n${publicRules}\n`
    + trainingAgents.map(agent => `User-agent: ${agent}\nDisallow: /\n`).join('\n')
    + `\nSitemap: ${origin}/sitemap.xml\n`
}
export async function buildSeoSite(outputDir: string, options: SeoOptions = {}, standalone = false): Promise<void> {
  productionOrigin(options.siteUrl) // Validate before writing any file.
  for (const page of pages) {
    const destination = join(outputDir, pagePath(page.locale, page.topic), 'index.html')
    await mkdir(dirname(destination), { recursive: true })
    await writeFile(destination, renderPage(page, options), 'utf8')
    await writeFile(join(outputDir, markdownPath(page)), renderMarkdown(page, productionOrigin(options.siteUrl)), 'utf8')
  }
  await mkdir(join(outputDir, 'seo'), { recursive: true })
  await copyFile(join(sourceDir, 'site.css'), join(outputDir, 'seo', 'site.css'))
  await copyFile(join(sourceDir, '..', 'public', 'favicon.svg'), join(outputDir, 'favicon.svg'))
  await writeFile(join(outputDir, 'robots.txt'), renderRobots(options), 'utf8')
  await writeFile(join(outputDir, 'sitemap.xml'), renderSitemap(options), 'utf8')
  await writeFile(join(outputDir, 'llms.txt'), renderReadingIndex(productionOrigin(options.siteUrl)), 'utf8')
  await writeFile(join(outputDir, 'llms-full.txt'), renderFullReadingExport(productionOrigin(options.siteUrl)), 'utf8')
  if (standalone) {
    // No Vue app, API access, database or model credentials in the public package.
    await writeFile(join(outputDir, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,follow"><title>SaveAny · Choose your language</title>${verificationMarkup(options)}<link rel="stylesheet" href="/seo/site.css"></head><body><main class="language-picker"><h1>SaveAny</h1><p>Video downloads and AI summaries · 视频下载与 AI 总结</p><nav aria-label="Choose your language"><a class="primary-link" href="/en/" lang="en">English</a><a class="primary-link" href="/zh/" lang="zh-CN">简体中文</a></nav></main></body></html>\n`, 'utf8')
    await writeFile(join(outputDir, '404.html'), '<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,follow"><title>Page not found | SaveAny</title></head><body><h1>Page not found / 页面不存在</h1><p><a href="/en/">English</a> · <a href="/zh/">简体中文</a></p></body></html>\n', 'utf8')
  }
}
export function seoPlugin(options: SeoOptions): Plugin {
  productionOrigin(options.siteUrl)
  let outputDir = ''
  return {
    name: 'saveany-public-seo',
    configResolved(config) { if (config.command === 'build') outputDir = resolve(config.root, config.build.outDir) },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = request.url?.split('?')[0]
        const send = (body: string, type: string) => {
          response.statusCode = 200
          response.setHeader('Content-Type', type + '; charset=utf-8')
          response.setHeader('Cache-Control', 'no-cache')
          response.end(body)
        }
        const page = pages.find(candidate => [pagePath(candidate.locale, candidate.topic), pagePath(candidate.locale, candidate.topic).slice(0, -1)].includes(pathname ?? ''))
        if (page) {
          const canonicalPath = pagePath(page.locale, page.topic)
          if (pathname !== canonicalPath) {
            response.statusCode = 301
            response.setHeader('Location', canonicalPath + (request.url?.includes('?') ? request.url.slice(request.url.indexOf('?')) : ''))
            response.end()
          } else send(renderPage(page), 'text/html')
          return
        }
        if (pathname === '/robots.txt') { send(renderRobots(), 'text/plain'); return }
        if (pathname === '/sitemap.xml') { send(renderSitemap(), 'application/xml'); return }
        const markdownPage = pages.find(candidate => pathname === markdownPath(candidate))
        if (markdownPage || pathname === '/llms.txt' || pathname === '/llms-full.txt') {
          response.setHeader('X-Robots-Tag', 'noindex,follow')
          if (markdownPage) {
            response.setHeader('Link', `<${pagePath(markdownPage.locale, markdownPage.topic)}>; rel="canonical", </llms.txt>; rel="describedby"`)
            send(renderMarkdown(markdownPage), 'text/markdown')
          } else send(pathname === '/llms.txt' ? renderReadingIndex() : renderFullReadingExport(), 'text/plain')
          return
        }
        if (pathname === '/seo/site.css') {
          readFile(join(sourceDir, 'site.css'), 'utf8').then(body => send(body, 'text/css')).catch(next)
          return
        }
        next() // Preserve Vite's existing workspace, assets and API proxy.
      })
    },
    async closeBundle() { if (outputDir) await buildSeoSite(outputDir, options) },
  }
}
