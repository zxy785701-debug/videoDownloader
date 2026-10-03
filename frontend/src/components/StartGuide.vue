<script setup lang="ts">
import { ArrowDownToLine, FileSearch, Link2, LoaderCircle, SlidersHorizontal } from '@lucide/vue'

const steps = [
  { title: '粘贴链接', description: '复制视频页面地址，粘贴到上方输入框。', icon: Link2 },
  { title: '查看结果', description: '确认解析出的标题和封面是你要的视频。', icon: FileSearch },
  { title: '选择画质', description: '从源站提供的格式中，选择需要的清晰度。', icon: SlidersHorizontal },
  { title: '等待文件', description: '点击下载，等待视频文件准备完成。', icon: LoaderCircle },
  { title: '保存到设备', description: '文件准备好后，点击保存到设备。', icon: ArrowDownToLine },
]
</script>

<template>
  <section aria-labelledby="start-guide-heading">
    <div class="guide-header text-center">
      <h2 id="start-guide-heading" class="text-section font-semibold text-ink">从链接到文件</h2>
      <p class="guide-subtitle mt-2 hidden text-caption text-muted lg:block">先确认视频在源站可以播放，再回来粘贴链接。</p>
    </div>
    <ol class="guide-steps mt-4 grid grid-cols-formats-two gap-2 md:grid-cols-guide-five lg:gap-4">
      <li v-for="step in steps" :key="step.title" class="guide-step flex min-h-guide-step items-center gap-2 rounded-control border border-line bg-surface p-2 md:flex-col md:items-start md:p-4">
        <component :is="step.icon" class="size-icon text-primary md:size-indicator" aria-hidden="true" />
        <div class="min-w-0">
          <h3 class="text-caption font-medium text-ink md:text-body">{{ step.title }}</h3>
          <p class="step-description mt-2 hidden text-caption text-muted lg:block">{{ step.description }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>
