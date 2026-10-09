<script setup lang="ts">
import { Check, Sparkles } from '@lucide/vue'

defineProps<{ signedIn: boolean; isMember: boolean; busy?: boolean; checkoutPending?: boolean; preview?: boolean }>()
defineEmits<{ start: []; buy: [] }>()
</script>

<template>
  <div class="membership-plans">
    <article class="membership-plan membership-plan-free">
      <p class="membership-plan-kind">轻松开始</p>
      <h3>免费版</h3>
      <p class="membership-plan-description">下载不限量，日常学习刚刚好。</p>
      <p class="membership-price"><strong>¥0</strong><span>免费使用</span></p>
      <ul>
        <li><Check aria-hidden="true" />不限次数视频下载</li>
        <li><Check aria-hidden="true" />多种清晰度与格式选择</li>
        <li><Check aria-hidden="true" />每日 3 次 AI 视频总结</li>
        <li><Check aria-hidden="true" />字幕、思维导图与视频问答</li>
      </ul>
      <button class="membership-plan-button" type="button" :disabled="busy || (signedIn && !isMember)" @click="$emit('start')">{{ signedIn && !isMember ? '当前方案' : '免费开始' }}</button>
    </article>
    <article class="membership-plan membership-plan-vip">
      <span class="membership-plan-badge"><Sparkles aria-hidden="true" />更多总结额度</span>
      <p class="membership-plan-kind">适合经常学习</p>
      <h3>VIP 会员</h3>
      <p class="membership-plan-description">把更多视频，变成你的知识。</p>
      <p class="membership-price"><strong>¥19.90</strong><span>/ 30 天</span></p>
      <ul>
        <li><Check aria-hidden="true" />每日 30 次 AI 视频总结</li>
        <li><Check aria-hidden="true" />包含免费版全部现有功能</li>
        <li><Check aria-hidden="true" />下载同样不限次数</li>
        <li><Check aria-hidden="true" />一次付款，不自动续费</li>
      </ul>
      <button class="membership-plan-button" type="button" :disabled="busy || (!preview && isMember)" @click="$emit('buy')">{{ preview ? (isMember ? '查看会员详情' : '查看会员方案') : isMember ? '会员已开通' : !signedIn ? '登录后开通' : checkoutPending ? '继续原订单支付' : '购买会员' }}</button>
    </article>
  </div>
  <p class="membership-plan-footnote">会员只提升新总结额度；DeepSeek 模型费用仍由本机 API Key 持有人承担。额度于北京时间零点重置，失败、复用和导出不扣次数。</p>
</template>
