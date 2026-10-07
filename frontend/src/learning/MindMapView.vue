<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MapNode } from './types'
import MindMapTree from './MindMapTree.vue'
import { downloadBlob } from './fileDownload'
import { exportMindMap, mindMapFilename } from './mindMapExport'
import { createMindMapLayout, mindMapLink, MIND_MAP_FONT, MAP_TEXT_PADDING } from './mindMapLayout'

const props = defineProps<{ tree: MapNode; title: string; summaryId: string }>()
const emit = defineEmits<{ locate: [id: string] }>()
const viewport = ref<SVGSVGElement | null>(null)
const fullscreenDialog = ref<HTMLDialogElement | null>(null)
const mapStage = ref<HTMLElement | null>(null)
const fullscreen = ref(false)
const exporting = ref(false)
const exportNotice = ref('')
const exportFailed = ref(false)
const collapsed = ref(new Set<string>())
const zoom = ref(1)
const pan = ref({ x: 20, y: 20 })
const listMode = ref(false)
const selected = ref<MapNode | null>(null)
let observer: ResizeObserver | undefined
let viewportVisible = false
let drag: { pointer: number; x: number; y: number; startX: number; startY: number } | null = null
let nativeFullscreen = false
let fullscreenOwner: HTMLElement | null = null
let returnFocus: HTMLElement | null = null
let exportGeneration = 0
let disposed = false

async function enterFullscreen() {
  const panel = fullscreenDialog.value
  if (!panel || fullscreen.value) return
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  panel.showModal()
  fullscreen.value = true
  await nextTick()
  if (!disposed && fullscreen.value) {
    // Dialog elements cannot request native fullscreen. Use their content;
    // the modal itself still provides a full-page fallback and focus trapping.
    const target = mapStage.value
    fullscreenOwner = target
    if (target?.requestFullscreen) void target.requestFullscreen().then(() => {
      if ((disposed || !fullscreen.value) && document.fullscreenElement === target) void document.exitFullscreen().catch(() => {})
    }).catch(() => {})
    fit()
    if (listMode.value) panel.querySelector('button')?.focus({ preventScroll: true })
    else viewport.value?.focus({ preventScroll: true })
  }
}
async function exitFullscreen() {
  const panel = fullscreenDialog.value
  if (!fullscreen.value && !panel?.open) return
  nativeFullscreen = false
  fullscreen.value = false
  panel?.close()
  if (fullscreenOwner && document.fullscreenElement === fullscreenOwner) await document.exitFullscreen().catch(() => {})
  fullscreenOwner = null
  await nextTick()
  if (disposed) return
  fit()
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
  returnFocus = null
}
function fullscreenChanged() {
  if (fullscreenOwner && document.fullscreenElement === fullscreenOwner) { nativeFullscreen = true; fit() }
  else if (nativeFullscreen) { nativeFullscreen = false; void exitFullscreen() }
}
async function locate(id: string) {
  await exitFullscreen()
  if (!disposed) emit('locate', id)
}
async function exportImage(format: 'png' | 'svg') {
  if (exporting.value) return
  const generation = exportGeneration
  const tree = props.tree, title = props.title
  exporting.value = true; exportNotice.value = ''; exportFailed.value = false
  try {
    const file = await exportMindMap(tree, title, format)
    if (disposed || generation !== exportGeneration) return
    downloadBlob(file.blob, mindMapFilename(title, format))
    exportNotice.value = format === 'png'
      ? `已生成完整高清 PNG：${file.width} × ${file.height} 像素（${file.scale} 倍），包含 ${file.nodeCount} 个节点。`
      : `已生成完整 SVG，包含 ${file.nodeCount} 个节点，放大查看仍清晰。`
  } catch (error) {
    if (disposed || generation !== exportGeneration) return
    exportFailed.value = true
    exportNotice.value = error instanceof Error ? error.message : '导图下载失败，请重试。'
  } finally { if (!disposed) exporting.value = false }
}

const layout = computed(() => createMindMapLayout(props.tree, { fontSize: 14, collapsed: collapsed.value, preview: true }))

function fit() {
  if (!viewport.value) return
  const bounds = viewport.value.getBoundingClientRect()
  if (!bounds.width || !bounds.height) return
  viewportVisible = true
  zoom.value = Math.max(0.12, Math.min(1, (bounds.width - 30) / layout.value.width, (bounds.height - 30) / layout.value.height))
  pan.value = { x: (bounds.width - layout.value.width * zoom.value) / 2, y: (bounds.height - layout.value.height * zoom.value) / 2 }
}
function changeZoom(factor: number) {
  const bounds = viewport.value?.getBoundingClientRect()
  zoomAt(factor, (bounds?.width || 600) / 2, (bounds?.height || 480) / 2)
}
function zoomAt(factor: number, x: number, y: number) {
  const next = Math.max(0.12, Math.min(2.5, zoom.value * factor))
  const ratio = next / zoom.value
  pan.value = { x: x + (pan.value.x - x) * ratio, y: y + (pan.value.y - y) * ratio }
  zoom.value = next
}
function wheel(event: WheelEvent) {
  const bounds = viewport.value?.getBoundingClientRect()
  if (!bounds) return
  // Firefox can report lines or pages; trackpads also report horizontal deltas.
  const dx = event.deltaX * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.width : 1)
  const dy = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1)
  if (event.ctrlKey) zoomAt(Math.exp(-dy * 0.002), event.clientX - bounds.left, event.clientY - bounds.top)
  else if (event.shiftKey) {
    const horizontal = dx || event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.width : 1)
    pan.value = { x: pan.value.x - horizontal, y: pan.value.y }
  }
  else pan.value = { x: pan.value.x - dx, y: pan.value.y - dy }
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
function pointerDown(event: PointerEvent) {
  if ((event.target as Element).closest('[data-map-node]')) return
  drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, startX: pan.value.x, startY: pan.value.y }
  viewport.value?.setPointerCapture(event.pointerId)
}
function pointerMove(event: PointerEvent) {
  if (drag?.pointer === event.pointerId) pan.value = { x: drag.startX + event.clientX - drag.x, y: drag.startY + event.clientY - drag.y }
}
function stopDrag() { drag = null }
// Polling may fetch a new object for the same immutable summary version.
// Keep fullscreen and reading state until the version actually changes.
watch(() => props.summaryId, async () => {
  exportGeneration++; exportNotice.value = ''; exportFailed.value = false
  if (fullscreen.value) await exitFullscreen()
  collapsed.value = new Set(props.tree.children.slice(1).map(node => node.id))
  selected.value = null
  await nextTick(); fit()
}, { immediate: true })
watch(listMode, async () => { await nextTick(); fit() })
onMounted(() => {
  observer = new ResizeObserver(entries => {
    const size = entries[0]?.contentRect
    const visible = !!size && size.width > 0 && size.height > 0
    // Opening node details changes the canvas height. Preserve the reading
    // position; fit only when first shown or explicitly requested/mode changed.
    if (visible && !viewportVisible) fit()
    viewportVisible = visible
  })
  if (viewport.value) observer.observe(viewport.value)
  document.addEventListener('fullscreenchange', fullscreenChanged)
  fit()
})
onBeforeUnmount(() => {
  disposed = true; exportGeneration++
  observer?.disconnect()
  document.removeEventListener('fullscreenchange', fullscreenChanged)
  fullscreenDialog.value?.close()
  if (fullscreenOwner && document.fullscreenElement === fullscreenOwner) void document.exitFullscreen().catch(() => {})
  fullscreenOwner = null
})
</script>

<template>
  <div class="mindmap-view">
    <dialog ref="fullscreenDialog" class="map-fullscreen-dialog" aria-label="视频思维导图全屏阅读" @cancel.prevent="exitFullscreen" @close="exitFullscreen" />
    <Teleport :to="fullscreenDialog || 'body'" :disabled="!fullscreen">
  <section ref="mapStage" class="map-stage" :class="{ 'map-stage-fullscreen': fullscreen }" aria-label="视频思维导图" @keydown.esc.stop.prevent="exitFullscreen">
    <div class="learning-toolbar">
      <p class="learning-muted map-description" :title="title">{{ fullscreen ? title : '主题 → 章节 → 知识要点，与摘要共用同一份内容。' }}</p>
      <div class="map-actions">
        <button class="learning-button" type="button" @click="listMode = !listMode">{{ listMode ? '查看导图' : '树形列表' }}</button>
        <button class="learning-button" type="button" @click="fullscreen ? exitFullscreen() : enterFullscreen()">{{ fullscreen ? '退出全屏' : '全屏阅读' }}</button>
        <button class="learning-button" type="button" :disabled="exporting" @click="exportImage('png')">{{ exporting ? '正在生成图片…' : '下载高清 PNG' }}</button>
        <button class="learning-button" type="button" :disabled="exporting" @click="exportImage('svg')">下载 SVG</button>
      </div>
    </div>
    <p v-if="exportNotice" class="map-export-notice" :class="{ 'learning-alert': exportFailed, 'learning-muted': !exportFailed }" :role="exportFailed ? 'alert' : 'status'">{{ exportNotice }}</p>
    <div v-show="!listMode" class="map-visual">
      <div class="map-controls" aria-label="导图操作">
        <button class="learning-button" aria-label="缩小导图" type="button" @click="changeZoom(1 / 1.25)">−</button>
        <span aria-live="polite">{{ Math.round(zoom * 100) }}%</span>
        <button class="learning-button" aria-label="放大导图" type="button" @click="changeZoom(1.25)">＋</button>
        <button class="learning-button" type="button" @click="fit">适配视图</button>
      </div>
      <svg ref="viewport" class="map-canvas" tabindex="0" role="group" aria-label="可拖动的思维导图，滚轮或方向键移动，Shift加滚轮横向移动，Ctrl加滚轮缩放，点击章节可折叠"
        @wheel.prevent="wheel"
        @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="stopDrag" @pointercancel="stopDrag"
        @keydown.up.prevent="pan.y += 40" @keydown.down.prevent="pan.y -= 40"
        @keydown.left.prevent="pan.x += 40" @keydown.right.prevent="pan.x -= 40">
        <g :transform="'translate(' + pan.x + ',' + pan.y + ') scale(' + zoom + ')'">
          <path v-for="(link, index) in layout.links" :key="index" class="map-edge"
            :d="mindMapLink(link.from, link.to)" />
          <g v-for="position in layout.nodes" :key="position.node.id" :data-map-node="position.node.id" :data-map-depth="position.depth" tabindex="0" role="button"
            :aria-label="position.node.text" :aria-expanded="position.node.children.length ? !collapsed.has(position.node.id) : undefined"
            :transform="'translate(' + position.x + ',' + position.y + ')'" class="map-node"
            :class="{ 'map-node-root': position.depth === 0, 'map-node-chapter': position.depth === 1, 'map-node-selected': selected?.id === position.node.id }"
            @click="toggle(position.node)" @keydown.enter.stop.prevent="toggle(position.node)" @keydown.space.stop.prevent="toggle(position.node)">
            <title>{{ position.node.text }}</title>
            <rect :width="position.width" :height="position.height" rx="10" />
            <text :font-family="MIND_MAP_FONT" :font-weight="position.depth === 0 ? 700 : position.depth === 1 ? 600 : 400">
              <tspan v-for="(line, index) in position.lines" :key="index" :x="MAP_TEXT_PADDING" :y="26 + index * layout.lineHeight" xml:space="preserve">{{ line }}</tspan>
            </text>
            <text v-if="position.node.children.length" :x="position.width - 7" :y="position.height - 5" text-anchor="end" class="map-node-toggle">{{ collapsed.has(position.node.id) ? '＋' : '−' }}</text>
          </g>
        </g>
      </svg>
      <p class="learning-muted map-hint">滚轮上下移动；Shift＋滚轮横向移动；Ctrl＋滚轮缩放；也可拖动空白处，点击节点查看详情或展开章节。</p>
      <div v-if="selected" class="map-selection">
        <p>{{ selected.text }}</p>
        <button v-if="selected.cue_ids[0]" class="learning-reference" type="button" @click="locate(selected.cue_ids[0])">查看对应字幕</button>
      </div>
    </div>
    <div :class="listMode ? 'map-list' : 'map-mobile-list'">
      <MindMapTree :nodes="[tree]" @locate="locate" />
    </div>
  </section>
    </Teleport>
  </div>
</template>
