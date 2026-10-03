<script setup lang="ts">
import { FileSearch } from '@lucide/vue'
</script>

<template>
  <div class="flex min-h-parse-status items-center gap-4 py-2" role="status" aria-live="polite" aria-busy="true">
    <FileSearch class="size-icon text-muted" aria-hidden="true" />
    <div class="min-w-0">
      <p class="text-body font-medium text-ink">正在获取视频信息</p>
      <p class="text-caption text-muted">等待视频来源返回标题和可下载格式</p>
    </div>
  </div>
</template>
