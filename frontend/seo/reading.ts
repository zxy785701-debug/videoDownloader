import { contentUpdated, evidenceFor, labels, pagePath, pages, repository } from './content.ts'
import type { PublicPage, Section } from './content.ts'

export function markdownPath(page: PublicPage): string {
  return pagePath(page.locale, page.topic) + 'index.md'
}
function tableCell(text: string): string { return text.replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/\n/g, '<br>') }
function sectionMarkdown(section: Section): string {
  const blocks = [`## ${section.heading}`, ...(section.paragraphs ?? [])]
  if (section.table) {
    const row = (cells: string[]) => '| ' + cells.map(tableCell).join(' | ') + ' |'
    blocks.push([row(section.table.headers), row(section.table.headers.map(() => '---')), ...section.table.rows.map(row)].join('\n'))
  }
  if (section.items) blocks.push(section.items.map((text, index) => `${section.ordered ? `${index + 1}.` : '-'} ${text}`).join('\n'))
  if (section.code) blocks.push('```powershell\n' + section.code + '\n```')
  for (const question of section.questions ?? []) blocks.push(`### ${question.question}`, question.answer)
  return blocks.join('\n\n')
}
// Human pages and reading exports share checked-in public content only.
// No workspace API, database, environment file or model is read here.
export function renderMarkdown(page: PublicPage, origin = ''): string {
  const copy = labels[page.locale]
  return [
    `# ${page.heading}`,
    `[SaveAny](${origin + pagePath(page.locale, 'home')}) · [HTML](${origin + pagePath(page.locale, page.topic)})`,
    `${copy.maintainer}\n\n${copy.updated}: ${contentUpdated}`,
    ...(origin ? [] : [copy.preview]),
    page.lead,
    `[${copy.cta}](${origin + pagePath(page.locale, 'video-download')}#local-setup)`,
    ...page.sections.map(sectionMarkdown),
    `## ${copy.evidence}`, copy.evidenceNote,
    evidenceFor(page).map(source => `- [${source.label}](${source.url})`).join('\n'),
    copy.footer,
  ].join('\n\n') + '\n'
}
export function renderReadingIndex(origin = ''): string {
  const definitions = pages.filter(page => page.topic === 'home').map(page => page.sections.find(section => section.id === 'definition')!.paragraphs![0])
  return [
    '# SaveAny',
    '> Local video downloads and caption-based AI summaries. 本机视频下载与基于字幕的 AI 总结。',
    `Content reviewed / 内容核对: ${contentUpdated}`,
    ...(origin ? [] : ['Local preview / 本机预览：尚未配置正式域名，不参与搜索收录。']),
    ...definitions,
    ...(['zh', 'en'] as const).map(locale => [
      `## ${locale === 'zh' ? '中文介绍与教程' : 'English overview and guides'}`,
      ...pages.filter(page => page.locale === locale).map(page => `- [${page.heading}](${origin + markdownPath(page)}): ${page.description}`),
    ].join('\n')),
    '## Optional',
    `- [Complete bilingual reading export](${origin}/llms-full.txt): All public page content, from the same source as the HTML pages.`,
    `- [Source repository](${repository}): Implementation and project documentation.`,
  ].join('\n\n') + '\n'
}
export function renderFullReadingExport(origin = ''): string {
  return '# SaveAny · Public reading export / 公开阅读版本\n\n' + pages.map(page => renderMarkdown(page, origin)).join('\n---\n\n')
}
