import assert from 'node:assert/strict'
import { test } from 'node:test'
import { execFileSync } from 'node:child_process'
import { contentUpdated, evidenceFor, evidenceRevision, labels, pagePath, pages } from '../seo/content.ts'
import { renderPage, renderRobots, renderSitemap, buildSeoSite } from '../seo/build.ts'
import { markdownPath, renderMarkdown, renderReadingIndex, renderFullReadingExport } from '../seo/reading.ts'
import { robotsAllowed } from './robots-policy.mjs'
import { mkdir, mkdtemp, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
const origin = 'https://saveany.example.test'
const root = fileURLToPath(new URL('../../', import.meta.url))

test('HTML and Markdown preserve all public facts, tables, questions, steps and sources', () => {
  for (const page of pages) {
    const text = renderMarkdown(page, origin), markup = renderPage(page, { siteUrl: origin })
    assert.ok(text.includes(page.lead) && text.includes(contentUpdated))
    assert.ok(text.includes(labels[page.locale].maintainer))
    for (const section of page.sections) {
      const passages = [section.heading, ...(section.paragraphs ?? []), ...(section.items ?? []),
        ...(section.questions ?? []).flatMap(item => [item.question, item.answer]),
        ...(section.table ? [...section.table.headers, ...section.table.rows.flat()] : [])]
      for (const passage of passages) assert.ok(text.includes(passage.replace(/\|/g, '\\|')), passage)
      if (section.code) assert.ok(text.includes(section.code))
    }
    for (const source of evidenceFor(page)) assert.ok(text.includes(source.url) && markup.includes(source.url))
    assert.ok(markup.includes(`type="text/markdown" href="${origin + markdownPath(page)}"`))
    assert.ok(markup.includes('rel="describedby" href="/llms.txt"'))
  }
})
test('reading index and full export are complete and contain no local learning URLs', () => {
  const index = renderReadingIndex(origin), full = renderFullReadingExport(origin)
  for (const page of pages) {
    assert.ok(index.includes(origin + markdownPath(page)))
    assert.ok(full.includes(renderMarkdown(page, origin)))
  }
  for (const text of [index, full]) {
    assert.ok(!text.includes('#learn/') && !text.includes('/api/v1/') && !text.includes('backend/data/'))
  }
  assert.ok(!index.includes('127.0.0.1')) // The full guide retains its public local-install instructions.
  assert.ok(!renderSitemap({ siteUrl: origin }).includes('.md'))
})
test('retrieval groups allow public content and retain private exclusions', () => {
  const robots = renderRobots({ siteUrl: origin })
  for (const agent of ['OAI-SearchBot', 'ChatGPT-User', 'Claude-SearchBot', 'Claude-User', 'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Googlebot', 'bingbot', 'Baiduspider', 'Sogou web spider', '360Spider', 'UnspecifiedFetcher']) {
    for (const path of ['/zh/', '/en/guides/ai-video-summary/', '/zh/index.md', '/llms.txt', '/llms-full.txt', '/seo/site.css']) assert.ok(robotsAllowed(robots, agent, path), agent + path)
    for (const path of ['/api', '/api/v1/analyses', '/api/v1/download/abc/file', '/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json']) assert.ok(!robotsAllowed(robots, agent, path), agent + path)
  }
})
test('known training bots are blocked and local preview stays closed for every agent', () => {
  for (const agent of ['GPTBot', 'ClaudeBot']) for (const path of ['/', '/zh/', '/llms.txt']) assert.ok(!robotsAllowed(renderRobots({ siteUrl: origin }), agent, path))
  for (const agent of ['OAI-SearchBot', 'ChatGPT-User', 'Claude-SearchBot', 'PerplexityBot', 'GPTBot', 'ClaudeBot', 'Google-Extended', 'Baiduspider']) assert.ok(!robotsAllowed(renderRobots(), agent, '/zh/'))
  assert.ok(renderReadingIndex().includes('Local preview'))
  assert.ok(renderMarkdown(pages[0]).includes(labels.zh.preview))
  assert.ok(!renderReadingIndex().includes(origin))
})
test('all evidence references point to files in the published implementation snapshot', () => {
  for (const page of pages) for (const source of evidenceFor(page)) {
    const path = source.url.split(`/${evidenceRevision}/`)[1]
    assert.ok(path)
    execFileSync('git', ['cat-file', '-e', `${evidenceRevision}:${path}`], { cwd: root, stdio: 'pipe' })
  }
})
test('reading files are built from public content without forwarding unrelated secrets', async () => {
  const tempRoot = join(root, '.local', 'geo-build-tests')
  await mkdir(tempRoot, { recursive: true })
  const out = await mkdtemp(join(tempRoot, 'generated-'))
  await buildSeoSite(out, { siteUrl: origin, DEEPSEEK_API_KEY: 'SECRET_TEST_MARKER', localRecord: 'PRIVATE_TEST_MARKER' }, true)
  for (const path of ['/llms.txt', '/llms-full.txt', ...pages.map(markdownPath)]) {
    const content = await readFile(join(out, path), 'utf8')
    assert.ok(!content.includes('SECRET_TEST_MARKER') && !content.includes('PRIVATE_TEST_MARKER'))
  }
})
