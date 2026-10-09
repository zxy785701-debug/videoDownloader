<script setup lang="ts">
import { ArrowUpRight, ChevronDown, CircleHelp } from '@lucide/vue'

defineEmits<{ start: []; rights: [] }>()
</script>

<template>
  <section id="tutorial" class="home-section home-tutorial" aria-labelledby="tutorial-heading">
    <div class="home-section-heading">
      <p class="learning-eyebrow">使用教程</p>
      <h2 id="tutorial-heading">从视频链接到下载与笔记</h2>
      <p>第一次使用？按下面的步骤操作即可。</p>
    </div>
    <div class="home-tutorial-layout">
      <ol class="home-tutorial-steps">
        <li><span class="tutorial-step-number" aria-hidden="true">01</span><div><h3>粘贴视频页面链接</h3><p>打开想保存的视频，复制页面地址，粘贴到顶部输入框。分享短链接也可尝试解析。</p></div></li>
        <li><span class="tutorial-step-number" aria-hidden="true">02</span><div><h3>解析并选择画质</h3><p>点击<strong>“解析视频”</strong>，核对标题与封面，再在视频信息区选择清晰度和下载方式。只想下载时，可先关闭“解析后自动总结”。</p></div></li>
        <li><span class="tutorial-step-number" aria-hidden="true">03</span><div><h3>准备文件，再保存到设备</h3><p>点击<strong>“下载”</strong>并等待文件准备完成，随后点击<strong>“保存到设备”</strong>。保存进度可在浏览器的下载列表中查看。</p></div></li>
        <li><span class="tutorial-step-number" aria-hidden="true">04</span><div><h3>阅读总结，导出学习资料</h3><p>开启自动总结，有可用字幕时会生成摘要；也可手动点击“生成总结”。切换“字幕原文”“思维导图”或“视频问答”，摘要可导出 Markdown，字幕可下载为 SRT 或 TXT。</p></div></li>
      </ol>
      <aside class="home-tutorial-tips" aria-labelledby="tutorial-tips-heading">
        <h3 id="tutorial-tips-heading"><CircleHelp aria-hidden="true" />操作小贴士</h3>
        <details open><summary>只想下载视频或字幕？<ChevronDown aria-hidden="true" /></summary><p>解析前关闭“解析后自动总结”。字幕获取完成后，切到“字幕原文”，选择 SRT 或 TXT，点击“下载字幕”。</p></details>
        <details><summary>为什么没有 AI 总结？<ChevronDown aria-hidden="true" /></summary><p>总结依赖可用的平台字幕和 DeepSeek 配置。看到登录或额度提示时，按弹窗操作，再返回视频点击生成或重试；没有字幕时仍可下载视频。</p></details>
        <details><summary>链接解析失败怎么办？<ChevronDown aria-hidden="true" /></summary><p>先确认原视频页面能正常播放，检查链接后重试。遇到源站登录或访问限制时，参阅下方视频下载教程中的处理说明。</p></details>
        <div class="home-tutorial-actions"><button class="tutorial-start-button" type="button" @click="$emit('start')">开始使用<ArrowUpRight aria-hidden="true" /></button><button class="tutorial-rights-button" type="button" @click="$emit('rights')">版权声明</button></div>
        <nav class="home-tutorial-links" aria-label="完整使用教程"><a href="/zh/guides/video-download/">视频下载教程</a><a href="/zh/guides/ai-video-summary/">AI 总结教程</a><a href="/zh/guides/subtitle-download/">字幕导出教程</a></nav>
      </aside>
    </div>
  </section>
</template>
