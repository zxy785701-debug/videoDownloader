<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MapNode } from './types'
import MindMapTree from './MindMapTree.vue'

const props = defineProps<{ tree: MapNode }>()
const emit = defineEmits<{ locate: [id: string] }>()
const viewport = ref<SVGSVGElement | null>(null)
const collapsed = ref(new Set<string>())
const zoom = ref(1)
const pan = ref({ x: 20, y: 20 })
const listMode = ref(false)
const selected = ref<MapNode | null>(null)
let observer: ResizeObserver | undefined
let drag: { pointer: number; x: number; y: number; startX: number; startY: number } | null = null

interface Positioned { node: MapNode; x: number; y: number }
const layout = computed(() => {
  const nodes: Positioned[] = []
  const links: { from: Positioned; to: Positioned }[] = []
  let leaves = 0
  let depthMax = 0
  function place(node: MapNode, depth: number): Positioned {
    const positioned: Positioned = { node, x: 20 + depth * 270, y: 0 }
    nodes.push(positioned)
    depthMax = Math.max(depthMax, depth)
    const children = !collapsed.value.has(node.id) ? node.children : []
    if (!children.length) {
      positioned.y = 20 + leaves++ * 110
    } else {
      const placed = children.map(child => place(child, depth + 1))
      positioned.y = ((placed[0]?.y || 0) + (placed[placed.length - 1]?.y || 0)) / 2
      placed.forEach(child => links.push({ from: positioned, to: child }))
    }
    return positioned
  }
  place(props.tree, 0)
  return { nodes, links, width: depthMax * 270 + 260, height: Math.max(120, leaves * 110 + 20) }
})

function fit() {
  if (!viewport.value) return
  const bounds = viewport.value.getBoundingClientRect()
  zoom.value = Math.max(0.12, Math.min(1, (bounds.width - 30) / layout.value.width, (bounds.height - 30) / layout.value.height))
  pan.value = { x: (bounds.width - layout.value.width * zoom.value) / 2, y: (bounds.height - layout.value.height * zoom.value) / 2 }
}
function changeZoom(factor: number) {
  const bounds = viewport.value?.getBoundingClientRect()
  const next = Math.max(0.12, Math.min(2.5, zoom.value * factor))
  const ratio = next / zoom.value
  const x = (bounds?.width || 600) / 2, y = (bounds?.height || 480) / 2
  pan.value = { x: x + (pan.value.x - x) * ratio, y: y + (pan.value.y - y) * ratio }
  zoom.value = next
}
function toggle(node: MapNode) {
  selected.value = node
  if (!node.children.length) return
  const updated = new Set(collapsed.value)
  if (updated.has(node.id)) {
    updated.delete(node.id)
    // Keep every chapter visible. Fold other branches before exceeding 100 nodes.
    let visible = 1 + props.tree.children.length + props.tree.children.reduce((n, chapter) => n + (updated.has(chapter.id) ? 0 : chapter.children.length), 0)
    for (const chapter of props.tree.children) {
      if (visible <= 100) break
      if (chapter.id !== node.id && !updated.has(chapter.id)) {
        updated.add(chapter.id)
        visible -= chapter.children.length
      }
    }
  } else updated.add(node.id)
  collapsed.value = updated
}
function lines(text: string): string[] {
  const result: string[] = []
  let current = '', width = 0
  for (const character of text) {
    const units = (character.codePointAt(0) || 0) > 255 ? 2 : 1
    if (width + units > 27) {
      result.push(current)
      current = ''; width = 0
      if (result.length === 3) break
    }
    current += character; width += units
  }
  if (result.length < 3 && current) result.push(current)
  if (result.join('').length < text.length && result.length) result[result.length - 1] += '…'
  return result
}
function pointerDown(event: PointerEvent) {
  if ((event.target as Element).closest('[data-map-node]')) return
  drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, startX: pan.value.x, startY: pan.value.y }
  viewport.value?.setPointerCapture(event.pointerId)
}
function pointerMove(event: PointerEvent) {
  if (drag?.pointer === event.pointerId) pan.value = { x: drag.startX + event.clientX - drag.x, y: drag.startY + event.clientY - drag.y }
}
function stopDrag() { drag = null }
watch(() => props.tree, async () => {
  collapsed.value = new Set(props.tree.children.slice(1).map(node => node.id))
  selected.value = null
  await nextTick(); fit()
}, { immediate: true })
onMounted(() => {
  observer = new ResizeObserver(fit)
  if (viewport.value) observer.observe(viewport.value)
  fit()
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section aria-label="视频思维导图">
    <div class="learning-toolbar">
      <p class="learning-muted">主题 → 章节 → 知识要点，与摘要共用同一份内容。</p>
      <button class="learning-button" type="button" @click="listMode = !listMode">{{ listMode ? '查看导图' : '树形列表' }}</button>
    </div>
    <div v-show="!listMode" class="map-visual">
      <div class="map-controls" aria-label="导图操作">
        <button class="learning-button" aria-label="缩小导图" type="button" @click="changeZoom(1 / 1.25)">−</button>
        <span aria-live="polite">{{ Math.round(zoom * 100) }}%</span>
        <button class="learning-button" aria-label="放大导图" type="button" @click="changeZoom(1.25)">＋</button>
        <button class="learning-button" type="button" @click="fit">适配视图</button>
      </div>
      <svg ref="viewport" class="map-canvas" tabindex="0" role="group" aria-label="可拖动的思维导图，方向键移动，点击章节可折叠"
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="stopDrag" @pointercancel="stopDrag"
        @keydown.up.prevent="pan.y += 40" @keydown.down.prevent="pan.y -= 40"
        @keydown.left.prevent="pan.x += 40" @keydown.right.prevent="pan.x -= 40">
        <g :transform="'translate(' + pan.x + ',' + pan.y + ') scale(' + zoom + ')'">
          <path v-for="(link, index) in layout.links" :key="index" class="map-edge"
            :d="'M' + (link.from.x + 220) + ',' + (link.from.y + 40) + ' C' + (link.from.x + 245) + ',' + (link.from.y + 40) + ' ' + (link.to.x - 25) + ',' + (link.to.y + 40) + ' ' + link.to.x + ',' + (link.to.y + 40)" />
          <g v-for="position in layout.nodes" :key="position.node.id" data-map-node tabindex="0" role="button"
            :aria-label="position.node.text" :aria-expanded="position.node.children.length ? !collapsed.has(position.node.id) : undefined"
            :transform="'translate(' + position.x + ',' + position.y + ')'" class="map-node"
            :class="{ 'map-node-root': position.node.id === 'root', 'map-node-selected': selected?.id === position.node.id }"
            @click="toggle(position.node)" @keydown.enter.stop.prevent="toggle(position.node)" @keydown.space.stop.prevent="toggle(position.node)">
            <title>{{ position.node.text }}</title>
            <rect width="220" height="80" rx="12" />
            <text x="14" y="22"><tspan v-for="(line, index) in lines(position.node.text)" :key="index" x="14" :dy="index ? 19 : 0">{{ line }}</tspan></text>
            <text v-if="position.node.children.length" x="207" y="74" text-anchor="end" class="map-node-toggle">{{ collapsed.has(position.node.id) ? '＋' : '−' }}</text>
          </g>
        </g>
      </svg>
      <p class="learning-muted map-hint">拖动空白处移动；点击节点查看完整文字或展开章节。</p>
      <div v-if="selected" class="map-selection">
        <p>{{ selected.text }}</p>
        <button v-if="selected.cue_ids[0]" class="learning-reference" type="button" @click="emit('locate', selected.cue_ids[0])">查看对应字幕</button>
      </div>
    </div>
    <div :class="listMode ? 'map-list' : 'map-mobile-list'">
      <MindMapTree :nodes="[tree]" @locate="emit('locate', $event)" />
    </div>
  </section>
</template>
