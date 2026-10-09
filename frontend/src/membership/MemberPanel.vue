<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronDown, Eye, EyeOff, LoaderCircle, LogOut, Mail, RefreshCw, ShieldCheck, Star } from '@lucide/vue'
import ResultDialog from '../components/ResultDialog.vue'
import MembershipPlans from './MembershipPlans.vue'
import './membership.css'

const emit = defineEmits<{ state: [value: { enabled: boolean; signedIn: boolean; isMember: boolean; busy: boolean }] }>()

interface Status {
  email: string
  simulated: boolean
  quota: { limit: number; used: number; reserved: number; remaining: number; member_expires: number | null; day: string }
  order: { id: string; status: string } | null
}
interface AccountConfig {
  enabled: boolean
  verification_required?: boolean
  mail_delivery?: 'smtp' | 'local_file' | 'unavailable'
  simulated?: boolean
}
class AccountError extends Error {
  readonly code: string
  constructor(message: string, code: string) { super(message); this.code = code }
}
const enabled = ref(false), open = ref(false), busy = ref(false)
const status = ref<Status | null>(null)
const verificationRequired = ref(false), simulated = ref(false)
const mailDelivery = ref<AccountConfig['mail_delivery']>()
const pendingStatus = ref(0)
let accountRevision = 0
let settingsRequest: Promise<void> | null = null
let backgroundStatus: Promise<void> | null = null
const page = ref<'login' | 'register' | 'verify' | 'reset'>('login')
const email = ref(''), password = ref(''), code = ref('')
const error = ref(''), notice = ref(''), checkoutUrl = ref('')
const summaryGateReason = ref('')
const menuOpen = ref(false), passwordVisible = ref(false)
const navigation = ref<HTMLElement | null>(null)
const avatar = computed(() => status.value?.email.slice(0, 1).toUpperCase() || '')
const isMember = computed(() => !!status.value?.quota.member_expires)
const label = computed(() => isMember.value ? '会员中心' : status.value ? '账号 · 普通用户' : '登录')
const expiry = computed(() => status.value?.quota.member_expires ? new Date(status.value.quota.member_expires * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '')
const title = computed(() => status.value ? '账号与会员' : page.value === 'login' ? '登录账号' : page.value === 'register' ? '创建账号' : page.value === 'verify' ? '验证邮箱' : '找回密码')
const quotaPercent = computed(() => status.value ? Math.min(100, (status.value.quota.used + status.value.quota.reserved) / status.value.quota.limit * 100) : 0)
watch([enabled, status, busy], () => emit('state', { enabled: enabled.value, signedIn: !!status.value, isMember: isMember.value, busy: busy.value }), { immediate: true })

async function api<T>(path: string, body?: object): Promise<T> {
  const response = await fetch('/api/v1/account' + path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new AccountError(result.detail?.message || '账号操作暂不可用，请稍后重试。', result.detail?.code || '')
  return result
}
async function run(action: () => Promise<void>) {
  if (busy.value) return
  accountRevision++
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (failure) {
    error.value = failure instanceof Error ? failure.message : '请求失败，请稍后重试。'
    if (failure instanceof AccountError && failure.code === 'LOGIN_REQUIRED') { status.value = null; checkoutUrl.value = '' }
  } finally { busy.value = false }
}
async function load(refresh = false) {
  const revision = accountRevision
  pendingStatus.value++
  try {
    const result = await api<Status>(refresh ? '/refresh' : '/me', refresh ? {} : undefined)
    if (revision === accountRevision) {
      status.value = result
      if (isMember.value) checkoutUrl.value = ''
    }
  } finally { pendingStatus.value-- }
}
function loadSettings(): Promise<void> {
  if (settingsRequest) return settingsRequest
  settingsRequest = (async () => {
    const config = await api<AccountConfig>('/settings')
    if (config.verification_required !== undefined) verificationRequired.value = config.verification_required
    if (config.simulated !== undefined) simulated.value = config.simulated
    mailDelivery.value = config.mail_delivery
    if (!verificationRequired.value && page.value === 'verify') change('login')
  })().finally(() => { settingsRequest = null })
  return settingsRequest
}
function displayFailure(failure: unknown, revision: number) {
  if (revision !== accountRevision || busy.value || !open.value) return
  if (failure instanceof AccountError && failure.code === 'LOGIN_REQUIRED') { status.value = null; checkoutUrl.value = ''; return }
  error.value = failure instanceof Error ? failure.message : '账号状态暂不可用，请稍后重试。'
}
function hydrate() {
  const revision = accountRevision
  void loadSettings().catch(failure => displayFailure(failure, revision))
  if (!backgroundStatus) backgroundStatus = load().catch(failure => displayFailure(failure, revision)).finally(() => { backgroundStatus = null })
}
function focusAvatar() { navigation.value?.querySelector<HTMLButtonElement>('.member-avatar-trigger')?.focus({ preventScroll: true }) }
function show(message = '') { if (menuOpen.value) focusAvatar(); menuOpen.value = false; open.value = true; passwordVisible.value = false; error.value = ''; summaryGateReason.value = message; hydrate() }
function close() { open.value = false; passwordVisible.value = false }
function showPlans(message = '') { if (!status.value) change('login'); show(message) }
function showLogin(message = '') {
  // A rejected summary may reveal an expired session while the header still
  // shows its cached account. Older status reads must not restore that cache.
  accountRevision++; enabled.value = true; status.value = null; checkoutUrl.value = ''
  change('login'); show(message)
}
function change(next: typeof page.value) { page.value = next; error.value = ''; notice.value = ''; password.value = ''; code.value = ''; passwordVisible.value = false }
function dismissMenu(event: Event) {
  if (!menuOpen.value) return
  if (event instanceof KeyboardEvent) {
    if (event.key === 'Escape') { menuOpen.value = false; focusAvatar() }
  } else if (!navigation.value?.contains(event.target as Node)) menuOpen.value = false
}
defineExpose({ showPlans, showLogin })
async function submit() {
  await run(async () => {
    if (page.value === 'login') {
      await api('/login', { email: email.value, password: password.value }); password.value = ''; await load(); summaryGateReason.value = ''
    } else if (page.value === 'register') {
      const result = await api<{ message: string; verification_required: boolean }>('/register', { email: email.value, password: password.value })
      verificationRequired.value = result.verification_required
      password.value = ''; code.value = ''; page.value = result.verification_required ? 'verify' : 'login'; notice.value = result.message
    } else if (page.value === 'verify') {
      const result = await api<{ message: string }>('/verify-email', { code: code.value })
      code.value = ''; page.value = 'login'; notice.value = result.message
    } else {
      const result = await api<{ message: string }>('/reset-password', { code: code.value, password: password.value })
      code.value = ''; password.value = ''; page.value = 'login'; notice.value = result.message
    }
  })
}
async function sendCode(kind: 'verify' | 'reset') {
  await run(async () => {
    const result = await api<{ message: string }>(kind === 'verify' ? '/resend-verification' : '/forgot-password', { email: email.value })
    notice.value = result.message
  })
}
async function buy() {
  await run(async () => {
    const result = await api<{ checkout_url: string | null; status: string }>('/checkout', {})
    checkoutUrl.value = result.checkout_url || ''
    if (checkoutUrl.value) {
      window.open(checkoutUrl.value, '_blank', 'noopener,noreferrer')
      notice.value = '支付页已准备。若新窗口没有打开，请点击下面的链接；付款后刷新会员状态。'
    } else notice.value = '订单等待确认，请刷新会员状态。'
    await load()
  })
}
async function logout() {
  await run(async () => {
    try { await api('/logout', {}) } finally { status.value = null; checkoutUrl.value = ''; password.value = ''; code.value = ''; menuOpen.value = false; passwordVisible.value = false; page.value = 'login' }
  })
}
onMounted(async () => {
  document.addEventListener('pointerdown', dismissMenu)
  document.addEventListener('keydown', dismissMenu)
  try {
    enabled.value = (await api<AccountConfig>('/config')).enabled
    if (enabled.value) hydrate()
  } catch (failure) {
    if (failure instanceof AccountError && failure.code === 'MEMBERSHIP_CONFIG_INVALID') enabled.value = true
    /* The membership window explains errors when opened; core workspace remains usable. */
  }
})
onBeforeUnmount(() => { document.removeEventListener('pointerdown', dismissMenu); document.removeEventListener('keydown', dismissMenu) })
</script>

<template>
  <div v-if="enabled" ref="navigation" class="member-navigation">
    <button class="member-vip-trigger" :class="{ 'member-vip-active': isMember }" type="button" @click="showPlans()"><Star aria-hidden="true" />{{ isMember ? 'VIP' : '开通 VIP' }}</button>
    <button v-if="!status" class="member-entry" type="button" @click="show()">{{ label }}</button>
    <button v-else class="member-entry member-avatar-trigger" type="button" :aria-label="label" :aria-expanded="menuOpen" aria-controls="member-dropdown" @click="menuOpen = !menuOpen"><span class="member-avatar">{{ avatar }}</span><ChevronDown aria-hidden="true" :class="{ 'member-chevron-open': menuOpen }" /></button>
    <div v-if="menuOpen && status" id="member-dropdown" class="member-dropdown">
      <div class="member-dropdown-profile"><strong>{{ status.email }}</strong><span>{{ isMember ? 'VIP 会员' : '免费用户' }}<template v-if="isMember"> · {{ expiry }}</template></span></div>
      <button type="button" @click="show()"><ShieldCheck aria-hidden="true" />账号与会员</button>
      <button v-if="!isMember" type="button" @click="showPlans()"><Star aria-hidden="true" />开通 VIP</button>
      <button type="button" :disabled="busy" @click="logout"><LogOut aria-hidden="true" />退出登录</button>
    </div>
  </div>
  <ResultDialog :open="open" :variant="status ? 'membership' : 'account'" @close="close">
    <template #title>{{ title }}</template>
    <template #description>{{ status ? '选择适合你的学习节奏，随时查看会员与额度。' : page === 'login' ? '登录以使用 AI 视频总结和会员功能' : page === 'register' ? '用一个账号，保存你的学习节奏。' : page === 'verify' ? '输入邮件中的验证代码。' : '通过邮件重置你的账号密码。' }}</template>
    <section class="member-panel" :class="{ 'member-panel-auth': !status }" aria-label="账号与会员" :aria-busy="busy">
      <p v-if="simulated || status?.simulated" class="member-mock">当前为本机模拟支付，不会真实扣款。</p>
      <p v-if="summaryGateReason" class="member-notice" role="status">{{ summaryGateReason }}</p>
      <p v-if="pendingStatus && !status" class="member-note" role="status">正在读取账号状态…</p>
      <template v-if="status">
        <div class="member-account-summary">
          <div class="member-account-profile"><span class="member-avatar">{{ avatar }}</span><div><p class="member-email">{{ status.email }} · {{ isMember ? '会员' : '普通用户' }}</p><p v-if="isMember" class="member-note">有效期至 {{ expiry }}（北京时间）</p><p v-else class="member-note">免费账号，下载不限量</p></div><span v-if="isMember" class="member-status-badge"><Star aria-hidden="true" />VIP</span></div>
          <div class="member-quota-header"><span>今日 AI 总结额度</span><strong>{{ status.quota.remaining }}<small> 次可用</small></strong></div>
          <div class="member-quota-track" aria-hidden="true"><span :style="{ width: quotaPercent + '%' }" /></div>
          <p class="member-note">今日已用 {{ status.quota.used }} / {{ status.quota.limit }} 次<span v-if="status.quota.reserved">，处理中或待同步 {{ status.quota.reserved }} 次</span>；剩余 {{ status.quota.remaining }} 次。</p>
        </div>
        <MembershipPlans :signed-in="true" :is-member="isMember" :busy="busy" :checkout-pending="!!checkoutUrl" @start="close" @buy="buy" />
        <div class="member-actions"><button class="member-secondary" type="button" :disabled="busy" @click="run(() => load(true))"><RefreshCw :class="{ 'member-loading': busy }" aria-hidden="true" />刷新会员状态</button><button class="member-secondary" type="button" :disabled="busy" @click="logout"><LogOut aria-hidden="true" />退出登录</button></div>
        <a v-if="checkoutUrl && !isMember" class="member-payment-link" :href="checkoutUrl" target="_blank" rel="noopener noreferrer">打开支付页</a>
        <div v-if="status.order && !isMember" class="member-order-status"><p>{{ ['creating', 'unknown', 'waiting', 'review'].includes(status.order.status) ? '结果待确认，请刷新；若已付款，请勿重复购买。' : status.order.status === 'open' ? '已有支付页，可以继续原订单。' : status.order.status === 'refunded' ? '该笔付款的会员权益已撤销。' : '订单状态已更新。' }}</p><details><summary>订单详情</summary><p>最近订单：{{ status.order.id }}</p></details></div>
        <p class="member-note">有效期内暂不重复购买。重新生成会扣一次，字幕与视频问答保持原行为。付款以服务端确认结果为准；退款请联系运营者。</p>
      </template>
      <template v-else>
        <p v-if="mailDelivery === 'local_file' && (page === 'verify' || page === 'reset')" class="member-mock">当前未接通真实邮件。邮件只保存为本机测试文件，真实邮箱收不到。</p>
        <form class="member-form" @submit.prevent="submit">
          <label class="member-field">邮箱<span class="member-input-wrap"><Mail aria-hidden="true" /><input v-model="email" type="email" autocomplete="email" placeholder="name@example.com" maxlength="254" :required="page !== 'verify'" :disabled="busy" /></span></label>
          <div v-if="page === 'login' || page === 'register' || page === 'reset'" class="member-field">
            <div class="member-field-heading"><label for="account-password">{{ page === 'reset' ? '新密码' : '密码' }}</label><button v-if="page === 'login'" class="member-text-button" type="button" :disabled="busy" @click="change('reset')">找回密码</button></div>
            <div class="member-input-wrap"><input id="account-password" v-model="password" :type="passwordVisible ? 'text' : 'password'" :autocomplete="page === 'login' ? 'current-password' : 'new-password'" placeholder="输入 12～128 个字符" minlength="12" maxlength="128" required :disabled="busy" aria-describedby="account-password-hint" /><button class="member-password-toggle" type="button" :aria-label="passwordVisible ? '隐藏密码' : '显示密码'" :aria-pressed="passwordVisible" :disabled="busy" @click="passwordVisible = !passwordVisible"><EyeOff v-if="passwordVisible" aria-hidden="true" /><Eye v-else aria-hidden="true" /></button></div>
            <small id="account-password-hint">12～128 个字符</small>
          </div>
          <label v-if="page === 'verify' || page === 'reset'" class="member-field">{{ page === 'verify' ? '邮箱验证码' : '邮件重置码' }}<span class="member-input-wrap"><input v-model="code" type="text" autocomplete="one-time-code" minlength="32" maxlength="100" required :disabled="busy" /></span></label>
          <button type="submit" class="member-submit" :disabled="busy"><LoaderCircle v-if="busy" class="member-loading" aria-hidden="true" />{{ busy ? '正在处理…' : page === 'login' ? '登录账号' : page === 'register' ? '创建账号' : page === 'verify' ? '完成验证' : '重置密码' }}</button>
          <button v-if="page === 'verify' || page === 'reset'" type="button" class="member-secondary" :disabled="busy || !email" @click="sendCode(page === 'verify' ? 'verify' : 'reset')">{{ mailDelivery === 'local_file' ? '生成本机测试' : '发送' }}{{ page === 'verify' ? '验证' : '重置' }}邮件</button>
        </form>
        <div class="member-auth-switch"><template v-if="page === 'login'">还没有账号？<button class="member-text-button" type="button" :disabled="busy" @click="change('register')">注册</button></template><template v-else>已有账号？<button class="member-text-button" type="button" :disabled="busy" @click="change('login')">登录</button></template><button v-if="verificationRequired && page !== 'verify'" class="member-text-button" type="button" :disabled="busy" @click="change('verify')">验证邮箱</button></div>
        <p v-if="!verificationRequired" class="member-note member-auth-note">当前无需邮箱验证，注册后即可使用邮箱和密码登录。</p>
      </template>
      <p v-if="error" class="member-error" role="alert">{{ error }}</p><p v-if="notice" class="member-notice" role="status">{{ notice }}</p>
    </section>
  </ResultDialog>
</template>
