import type { MapNode } from './types'

export const MIND_MAP_FONT = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif'
export const MAP_PADDING = 28
export const MAP_COLUMN_GAP = 48
export const MAP_TEXT_PADDING = 16

export interface PositionedMapNode {
  node: MapNode
  depth: number
  x: number
  y: number
  width: number
  height: number
  lines: string[]
  subtreeHeight: number
  children: PositionedMapNode[]
}

function textMeasurer(fontSize: number, weight = 400) {
  const canvas = document.createElement('canvas').getContext('2d')
  if (!canvas) throw new Error('浏览器无法绘制导图，请换用支持 Canvas 的浏览器。')
  canvas.font = `${weight} ${fontSize}px ${MIND_MAP_FONT}`
  return canvas
}

function wrap(text: string, width: number, measure: CanvasRenderingContext2D) {
  const lines: string[] = []
  const segmenter = new Intl.Segmenter('zh', { granularity: 'grapheme' })
  for (const paragraph of text.replace(/\r\n?/g, '\n').split('\n')) {
    let line = ''
    for (const { segment } of segmenter.segment(paragraph)) {
      if (line && measure.measureText(line + segment).width > width) {
        lines.push(line); line = ''
      }
      line += segment
    }
    lines.push(line)
  }
  return lines
}

export function wrapMindMapTitle(text: string, width: number, fontSize: number) {
  return wrap(text, width, textMeasurer(fontSize, 700))
}

// A right-facing tree with content-sized cards. Each depth has enough space for
// its widest visible card; subtree heights keep every branch free of overlap.
// Export calls this without a collapsed set or a preview limit.
export function createMindMapLayout(tree: MapNode, options: { fontSize: number; collapsed?: ReadonlySet<string>; preview?: boolean }) {
  const lineHeight = Math.round(options.fontSize * 1.5)
  const columnWidths: number[] = []
  const measure = textMeasurer(options.fontSize)
  function size(node: MapNode, depth: number): PositionedMapNode {
    measure.font = `${depth === 0 ? 700 : depth === 1 ? 600 : 400} ${options.fontSize}px ${MIND_MAP_FONT}`
    const minimum = depth === 0 ? 220 : depth === 1 ? 210 : 240
    const maximum = depth === 0 ? 360 : depth === 1 ? 380 : options.preview ? 620 : 880
    const paragraphs = node.text.replace(/\r\n?/g, '\n').split('\n')
    const naturalWidth = Math.max(...paragraphs.map(text => measure.measureText(text).width))
    const targetLines = depth < 2 ? 2 : 1
    const width = Math.max(minimum, Math.min(maximum, Math.ceil((naturalWidth / targetLines + MAP_TEXT_PADDING * 2) / 8) * 8))
    let lines = wrap(node.text, width - MAP_TEXT_PADDING * 2, measure)
    const limit = depth < 2 ? 3 : 4
    if (options.preview && lines.length > limit) {
      lines = lines.slice(0, limit)
      const characters = [...new Intl.Segmenter('zh', { granularity: 'grapheme' }).segment(lines[limit - 1]!)].map(item => item.segment)
      while (characters.length && measure.measureText(characters.join('') + '…').width > width - MAP_TEXT_PADDING * 2) characters.pop()
      lines[limit - 1] = characters.join('') + '…'
    }
    const height = Math.max(48, lines.length * lineHeight + 24) + (options.preview && node.children.length ? 12 : 0)
    columnWidths[depth] = Math.max(columnWidths[depth] || 0, width)
    const children = options.collapsed?.has(node.id) ? [] : node.children.map(child => size(child, depth + 1))
    const gap = depth === 0 ? 24 : 12
    const childrenHeight = children.reduce((sum, child) => sum + child.subtreeHeight, 0) + Math.max(0, children.length - 1) * gap
    return { node, depth, width, height, lines, subtreeHeight: Math.max(height, childrenHeight), children, x: 0, y: 0 }
  }
  const root = size(tree, 0)
  const columns: number[] = []
  let width = MAP_PADDING
  columnWidths.forEach((column, depth) => {
    columns[depth] = width
    width += column + (depth < columnWidths.length - 1 ? MAP_COLUMN_GAP : MAP_PADDING)
  })
  const nodes: PositionedMapNode[] = []
  const links: { from: PositionedMapNode; to: PositionedMapNode }[] = []
  function place(node: PositionedMapNode, top: number) {
    node.x = columns[node.depth]!
    node.y = top + (node.subtreeHeight - node.height) / 2
    nodes.push(node)
    const gap = node.depth === 0 ? 24 : 12
    const childrenHeight = node.children.reduce((sum, child) => sum + child.subtreeHeight, 0) + Math.max(0, node.children.length - 1) * gap
    let childTop = top + (node.subtreeHeight - childrenHeight) / 2
    for (const child of node.children) {
      place(child, childTop)
      links.push({ from: node, to: child })
      childTop += child.subtreeHeight + gap
    }
  }
  place(root, MAP_PADDING)
  return { nodes, links, width, height: root.subtreeHeight + MAP_PADDING * 2, lineHeight }
}

export function mindMapLink(from: PositionedMapNode, to: PositionedMapNode, offsetY = 0) {
  const x1 = from.x + from.width, y1 = from.y + from.height / 2 + offsetY
  const x2 = to.x, y2 = to.y + to.height / 2 + offsetY
  const bend = (x2 - x1) / 2
  return `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`
}
