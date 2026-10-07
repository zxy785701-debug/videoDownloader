import type { MapNode } from './types'
import { createMindMapLayout, mindMapLink, wrapMindMapTitle, MAP_PADDING, MAP_TEXT_PADDING, MIND_MAP_FONT } from './mindMapLayout'

const FONT_SIZE = 16
const LINE_HEIGHT = 24
const MAX_PNG_SIDE = 16_384
const MAX_PNG_PIXELS = 32_000_000

function xml(text: string): string {
  return text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '\uFFFD')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;')
}

export function mindMapFilename(title: string, extension: 'png' | 'svg'): string {
  let stem = Array.from(title.replace(/[<>:"/\\|?*\u0000-\u001F\u007F]/g, '_').trim()).slice(0, 100).join('').replace(/[. ]+$/g, '') || 'video'
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(stem)) stem = '_' + stem
  return stem + '-思维导图.' + extension
}

// This layout is deliberately independent of the interactive viewport and its
// collapsed branches. Every label is wrapped in full, with a measured height.
function createSvg(tree: MapNode, title: string) {
  const layout = createMindMapLayout(tree, { fontSize: FONT_SIZE })
  const { nodes, links, width } = layout
  const titleLines = wrapMindMapTitle(title || '视频思维导图', width - 2 * MAP_PADDING, FONT_SIZE)
  const headerHeight = titleLines.length * LINE_HEIGHT + 46
  const height = layout.height + headerHeight
  const text = (lines: string[], x: number, y: number) => lines.map((line, index) =>
    `<tspan x="${x}" y="${y + index * LINE_HEIGHT}" xml:space="preserve">${xml(line)}</tspan>`).join('')
  const paths = links.map(({ from, to }) => `<path d="${mindMapLink(from, to, headerHeight)}" fill="none" stroke="#b6c4d5" stroke-width="1.5"/>`).join('')
  const boxes = nodes.map(position => {
    const isRoot = position.depth === 0, isChapter = position.depth === 1
    const y = position.y + headerHeight
    return `<g data-node-id="${xml(position.node.id)}" data-node-depth="${position.depth}"><title>${xml(position.node.text)}</title>` +
      `<rect x="${position.x}" y="${y}" width="${position.width}" height="${position.height}" rx="10" fill="${isRoot ? '#eaf0ff' : isChapter ? '#f1f5fc' : '#ffffff'}" stroke="${isRoot ? '#4169b1' : '#c7d1df'}" stroke-width="1.5"/>` +
      `<text fill="#18283e" font-weight="${isRoot ? 700 : isChapter ? 600 : 400}">${text(position.lines, position.x + MAP_TEXT_PADDING, y + 12 + FONT_SIZE)}</text></g>`
  }).join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="export-title">` +
    `<title id="export-title">${xml(title)} · 完整思维导图</title>` +
    `<rect width="100%" height="100%" fill="white"/>` +
    `<g font-family="${xml(MIND_MAP_FONT)}" font-size="${FONT_SIZE}">` +
    `<text fill="#18283e" font-weight="bold">${text(titleLines, MAP_PADDING, MAP_PADDING + FONT_SIZE)}</text>` +
    `<text x="${MAP_PADDING}" y="${MAP_PADDING + titleLines.length * LINE_HEIGHT + 16}" font-size="13" fill="#52647a">完整章节与知识要点 · 根据视频字幕摘要整理</text>` +
    paths + boxes + '</g></svg>'
  return { svg, width, height, nodeCount: nodes.length }
}

export async function exportMindMap(tree: MapNode, title: string, format: 'png' | 'svg') {
  await document.fonts.ready
  const drawing = createSvg(tree, title)
  const svgBlob = new Blob([drawing.svg], { type: 'image/svg+xml;charset=utf-8' })
  if (format === 'svg') return { blob: svgBlob, ...drawing, scale: 1 }
  // Keep at least 2x resolution. Never silently clip or produce a blurry
  // thumbnail when a tree exceeds the browser's safe bitmap budget.
  const scale = [3, 2].find(value => drawing.width * value <= MAX_PNG_SIDE && drawing.height * value <= MAX_PNG_SIDE && drawing.width * drawing.height * value * value <= MAX_PNG_PIXELS)
  if (!scale) throw new Error('这份导图超出高清 PNG 的安全尺寸，请下载完整 SVG；放大查看仍清晰，所有章节和文字都会保留。')
  const sourceUrl = URL.createObjectURL(svgBlob)
  const canvas = document.createElement('canvas')
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image()
      const timeout = setTimeout(() => { image.src = ''; reject(new Error('导图图片生成超时，请重试或下载 SVG。')) }, 30_000)
      image.onload = () => { clearTimeout(timeout); resolve(image) }
      image.onerror = () => { clearTimeout(timeout); reject(new Error('导图图片生成失败，请重试或下载 SVG。')) }
      image.src = sourceUrl
    })
    canvas.width = drawing.width * scale
    canvas.height = drawing.height * scale
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器无法生成 PNG，请下载 SVG。')
    context.scale(scale, scale)
    context.drawImage(image, 0, 0, drawing.width, drawing.height)
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG 保存失败，请下载 SVG。')), 'image/png'))
    return { ...drawing, blob, scale, width: canvas.width, height: canvas.height }
  } finally {
    URL.revokeObjectURL(sourceUrl)
    canvas.width = 0; canvas.height = 0
  }
}
