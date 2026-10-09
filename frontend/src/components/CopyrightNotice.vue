<script setup lang="ts">
import { ShieldCheck } from '@lucide/vue'

defineEmits<{ close: [] }>()
</script>

<template>
  <section class="copyright-notice" aria-label="内容版权与使用说明">
    <p class="copyright-intro"><ShieldCheck aria-hidden="true" /><span>请仅处理你拥有版权或已获授权的视频内容。</span></p>
    <div class="copyright-points">
      <section><span aria-hidden="true">01</span><div><h3>原内容的权利归属</h3><p>视频、音频、字幕等内容的相关权利归各自权利人所有。SaveAny 提供下载与学习工具，使用工具不代表获得内容的转载、传播或商业使用授权。</p></div></section>
      <section><span aria-hidden="true">02</span><div><h3>按授权范围使用</h3><p>请遵守内容许可与来源平台的适用规则，不绕过付费、登录或其他访问限制。未经授权，请勿转载、出售或用于商业传播。</p></div></section>
      <section><span aria-hidden="true">03</span><div><h3>核对 AI 生成内容</h3><p>摘要、导图和问答根据可用字幕生成，可能出现遗漏或错误。重要内容请对照原视频与字幕核实，不将 AI 生成内容视为原作者的完整观点。</p></div></section>
    </div>
    <p class="copyright-footnote">下载或生成 AI 总结不会改变原内容的版权归属。</p>
    <button class="copyright-dismiss" type="button" @click="$emit('close')">我知道了</button>
  </section>
</template>
