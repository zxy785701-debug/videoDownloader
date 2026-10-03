<script setup lang="ts">
import { X } from '@lucide/vue'
defineProps<{ busy: boolean }>()
const emit = defineEmits<{ close: []; example: [] }>()
</script>

<template>
  <section id="guide" class="help-card rounded-panel border border-line bg-surface p-6 md:p-6" aria-labelledby="guide-heading">
    <div class="help-header mb-2 flex items-center justify-between gap-2">
      <h2 id="guide-heading" class="whitespace-nowrap text-section font-medium">使用帮助</h2>
      <div class="flex items-center gap-2">
        <button class="quiet-button whitespace-nowrap border border-line px-2" type="button" :disabled="busy" @click="emit('example')">填入示例链接</button>
        <button class="quiet-button size-touch shrink-0 px-0" type="button" aria-label="关闭使用帮助" @click="emit('close')"><X class="size-icon" aria-hidden="true" /></button>
      </div>
    </div>
    <div class="help-body grid gap-4 md:grid-cols-help-two">
      <div>
        <h3 class="help-guide-title hidden text-body font-medium md:block">从链接到文件</h3>
        <ol class="help-full-steps list-inside list-decimal space-y-2 text-caption text-muted md:mt-2"><li>粘贴视频页面的完整链接，点击解析。</li><li>确认视频，选择清晰度和下载方式。</li><li>点击下载，文件就绪后保存到设备。</li></ol>
        <ol class="help-short-steps hidden list-inside list-decimal space-y-2 text-caption text-muted"><li>粘贴并解析链接。</li><li>选择画质和方式。</li><li>文件就绪后保存。</li></ol>
      </div>
      <div>
        <h3 class="text-body font-medium">登录验证</h3>
        <p class="help-login-normal mt-2 text-caption text-muted">先在 Firefox 登录源站，确认视频可以播放后重新解析。无需导出或填写 Cookie。</p>
        <p class="help-login-compact mt-2 hidden text-caption text-muted">先在 Firefox 登录源站，再解析。无需填写 Cookie。</p>
        <p class="help-context mt-2 hidden text-caption text-muted md:block">支持 YouTube、哔哩哔哩和抖音，其他链接以实际解析结果为准。</p>
        <p class="help-context mt-2 hidden text-caption text-muted md:block">下载进度表示文件准备过程，保存进度可在浏览器下载列表中查看。</p>
      </div>
    </div>
  </section>
</template>
