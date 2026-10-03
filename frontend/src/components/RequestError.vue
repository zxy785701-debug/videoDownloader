<script setup lang="ts">
import { computed } from 'vue'
import { TriangleAlert, X } from '@lucide/vue'

const props = defineProps<{
  message: string
  context: 'input' | 'download'
  busy: boolean
}>()
const emit = defineEmits<{ dismiss: []; retry: [] }>()

// These explanations only affect presentation; the original response stays available.
const explanation = computed(() => {
  if (/剪贴板/.test(props.message)) {
    return { title: '无法读取剪贴板', next: '请在输入框中直接粘贴视频链接。', retry: false }
  }
  if (/无法访问 Firefox 登录配置|DPAPI|解密/i.test(props.message)) {
    return { title: '无法读取本机登录状态', next: '请查看错误详情，检查网站启动方式和浏览器配置后重试。', retry: true }
  }
  if (/要求登录验证|拒绝当前浏览器会话|LOGIN_REQUIRED|sign in to confirm/i.test(props.message)) {
    return { title: '需要在源站完成登录验证', next: '在本机 Firefox 登录 YouTube，确认该视频可以播放，再回来重试。', retry: true }
  }
  if (/无法连接|连接超时|连接抖音超时或中断|抖音暂时拒绝访问|请求过于频繁|网络访问被限制|Failed to fetch|NetworkError|timed out/i.test(props.message)) {
    return { title: '连接失败', next: '确认网站和视频页面可以访问，检查本机网络后重试。', retry: true }
  }
  if (/不支持.*(?:链接|网址|URL)|Unsupported URL/i.test(props.message)) {
    return { title: '当前无法解析这个链接', next: '请使用视频页面的完整链接；仍不支持时，可以尝试其他视频。', retry: false }
  }
  if (/没有可用的所选格式|Requested format is not available/i.test(props.message)) {
    return { title: '所选格式暂不可用', next: '重新解析链接，或选择其他格式后重试。', retry: true }
  }
  if (/下载任务.*过期/.test(props.message)) {
    return { title: '下载任务已过期', next: '请重新创建下载任务，等待文件准备好后保存。', retry: true }
  }
  return {
    title: props.context === 'download' ? '下载失败' : '解析失败',
    next: props.context === 'download' ? '可以重新尝试下载；仍失败时，重新解析链接并选择其他格式。' : '请查看错误详情，确认链接和视频在源站可以访问后重试。',
    retry: true,
  }
})

const waitingForTask = computed(() => props.busy && props.context === 'download')
const nextAction = computed(() => waitingForTask.value
  ? '任务是否完成尚未确认。检查网络，恢复后刷新页面，再重新解析链接。'
  : explanation.value.next)

function focusLink() {
  document.getElementById('video-link')?.focus()
}

function refreshPage() {
  window.location.reload()
}
</script>


<template>
  <div class="rounded-control border border-error-line bg-surface p-4" role="alert">
    <div class="flex items-start gap-2">
      <TriangleAlert class="size-indicator text-error" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h3 class="text-body font-semibold text-error">{{ waitingForTask ? '暂时无法获取下载状态' : explanation.title }}</h3>
        <p class="mt-2 text-body text-ink">{{ nextAction }}</p>
        <div v-if="waitingForTask || (!busy && context === 'input')" class="mt-2">
          <button v-if="waitingForTask" class="quiet-button border border-line text-ink" type="button" @click="refreshPage">刷新页面</button>
          <button v-else-if="explanation.retry" class="quiet-button border border-line text-ink" type="button" @click="emit('retry')">重新解析</button>
          <a v-else class="quiet-button border border-line text-ink" href="#video-link" @click="focusLink">修改链接</a>
        </div>
        <details class="mt-2"><summary class="inline-flex min-h-touch w-fit items-center rounded-control py-2 text-caption text-muted transition-colors duration-enter ease-enter hover:text-ink">查看错误详情</summary><p class="mt-2 break-all text-caption text-ink">{{ message }}</p></details>
      </div>
      <button class="quiet-button size-touch shrink-0 px-0" type="button" aria-label="关闭错误提示" @click="emit('dismiss')"><X class="size-icon" aria-hidden="true" /></button>
    </div>
  </div>
</template>
