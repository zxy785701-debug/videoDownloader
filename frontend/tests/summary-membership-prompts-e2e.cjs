// Separate mock billing + isolated local workspace. No Stripe or real model calls.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const base = process.env.MEMBERSHIP_TEST_APP_URL || 'http://127.0.0.1:8487'
const output = path.resolve(__dirname, '../../.local/summary-membership-prompts-20261008')
const checks = [], errors = []
let checkoutRequests = 0
const source = id => 'https://www.youtube.com/watch?v=' + id
const password = 'synthetic-prompt-password-long'
const email = 'summary-prompts@example.com'
async function check(name, action) { await action(); checks.push(name); console.log('PASS ' + name) }
async function api(page, endpoint, body) {
  return page.evaluate(async ({endpoint,body}) => {
    const response = await fetch(endpoint.startsWith('/_test/') ? endpoint : '/api/v1' + endpoint, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    return { status:response.status, data:await response.json() }
  }, {endpoint,body})
}
async function close(page) { await page.getByRole('button',{name:'关闭弹窗',exact:true}).click(); await page.waitForFunction(()=>!document.querySelector('dialog:modal')) }
async function parse(page, id, automatic=true) {
  await page.getByRole('checkbox',{name:'解析后自动总结'}).setChecked(automatic)
  await page.getByLabel('视频页面链接',{exact:true}).fill(source(id))
  await page.getByRole('button',{name:'解析视频',exact:true}).click()
  await page.getByRole('heading',{name:'【模拟验收】视频信息 ' + id,exact:true}).waitFor()
}
async function saved(page) { await page.locator('.summary-overview h3').waitFor({timeout:20000}) }
async function capture(page, name) {
  await page.waitForFunction(()=>[...document.querySelectorAll('dialog:modal')].every(dialog=>getComputedStyle(dialog).opacity==='1'))
  await page.screenshot({path:path.join(output,name),animations:'disabled'})
}
;(async()=>{
  await fs.mkdir(output,{recursive:true})
  const browser = await chromium.launch({channel:'msedge',headless:true})
  const context = await browser.newContext({viewport:{width:1280,height:900},reducedMotion:'reduce'})
  const page = await context.newPage()
  page.on('pageerror',error=>errors.push(error.message))
  page.on('request',request=>{if(request.method()==='POST' && request.url().endsWith('/account/checkout')) checkoutRequests++})
  try {
    await page.goto(base)
    let failedHash, savedHash
    await check('guest automatic summary opens the login dialog with its server error',async()=>{
      await parse(page,'promptGuest1')
      await page.getByRole('heading',{name:'登录账号',exact:true}).waitFor()
      await page.locator('dialog:modal').getByText('请先在会员窗口登录，再生成新的 AI 总结。',{exact:true}).waitFor()
      failedHash = new URL(page.url()).hash
      const detail = (await api(page,'/analyses/' + failedHash.slice(7))).data
      assert.equal(detail.subtitle_status,'ready')
      assert.equal(detail.jobs.find(job=>job.kind==='auto_summary').error_code,'LOGIN_REQUIRED')
      assert.equal((await api(page,'/_test/unified/stats')).data.summary,0)
      await capture(page,'guest-auto-login.png')
      await close(page)
    })
    await check('dismissal and restoring a failed historical record do not reopen the dialog',async()=>{
      await page.waitForTimeout(1800)
      assert.equal(await page.locator('dialog:modal').count(),0)
      await page.reload({waitUntil:'networkidle'})
      await page.getByRole('button',{name:'重试总结',exact:true}).waitFor()
      assert.equal(await page.locator('dialog:modal').count(),0)
    })
    await check('each explicit guest retry opens login and leaves downloads available',async()=>{
      for(let attempt=0;attempt<2;attempt++) {
        await page.getByRole('button',{name:'重试总结',exact:true}).click()
        await page.getByRole('heading',{name:'登录账号',exact:true}).waitFor()
        await close(page)
      }
      await page.getByRole('button',{name:'下载',exact:true}).click()
      await page.getByRole('link',{name:'保存到设备',exact:true}).waitFor()
      assert.equal((await api(page,'/_test/unified/stats')).data.summary,0)
    })
    await check('guest caption-only parsing does not request login',async()=>{
      await parse(page,'promptManual1',false)
      const generate = page.getByRole('button',{name:'生成总结',exact:true})
      await generate.waitFor()
      await page.waitForFunction(()=>!document.querySelector('.learning-toolbar button:disabled'))
      assert.equal(await page.locator('dialog:modal').count(),0)
      await generate.click()
      await page.getByRole('heading',{name:'登录账号',exact:true}).waitFor()
    })
    await check('login clears the prompt and explicit retry generates exactly one summary',async()=>{
      assert.equal((await api(page,'/account/register',{email,password})).status,200)
      await page.getByLabel('邮箱',{exact:true}).fill(email)
      await page.getByLabel('密码',{exact:true}).fill(password)
      await page.getByRole('button',{name:'登录账号',exact:true}).click()
      await page.getByRole('heading',{name:'账号与会员',exact:true}).waitFor()
      assert.equal(await page.locator('dialog:modal').getByText('请先在会员窗口登录，再生成新的 AI 总结。',{exact:true}).count(),0)
      assert.equal((await api(page,'/_test/unified/stats')).data.summary,0)
      await close(page)
      await page.getByRole('button',{name:'生成总结',exact:true}).click()
      await saved(page)
      savedHash=new URL(page.url()).hash
      assert.equal((await api(page,'/account/me')).data.quota.used,1)
    })
    await check('the original free allowance succeeds before exhaustion',async()=>{
      for(const id of ['promptFree02','promptFree03']) { await parse(page,id); await saved(page); assert.equal(await page.locator('dialog:modal').count(),0) }
      assert.equal((await api(page,'/account/me')).data.quota.used,3)
    })
    await check('manual regeneration at quota limit opens membership and preserves the summary',async()=>{
      await page.getByRole('button',{name:'重新生成',exact:true}).click()
      await page.getByRole('heading',{name:'账号与会员',exact:true}).waitFor()
      await page.locator('dialog:modal').getByText('今日 AI 总结额度已用完（3 次），请明天再试或查看会员。',{exact:true}).waitFor()
      await page.getByText('今日已用 3 / 3 次').waitFor()
      assert.equal(await page.getByRole('button',{name:'购买会员',exact:true}).isEnabled(),true)
      await capture(page,'free-quota-membership.png')
      await close(page)
      assert.equal(await page.locator('.summary-overview h3').count(),1)
    })
    await check('automatic exhaustion prompts once and only explicit reparse prompts again',async()=>{
      await parse(page,'promptQuota1')
      await page.getByRole('heading',{name:'账号与会员',exact:true}).waitFor()
      const blocked = new URL(page.url()).hash
      const detail=(await api(page,'/analyses/'+blocked.slice(7))).data
      assert.equal(detail.jobs.find(job=>job.kind==='auto_summary').error_code,'QUOTA_EXCEEDED')
      await close(page)
      await page.reload({waitUntil:'networkidle'})
      await page.getByRole('button',{name:'重试总结',exact:true}).waitFor()
      assert.equal(await page.locator('dialog:modal').count(),0)
      await parse(page,'promptQuota1')
      await page.getByRole('heading',{name:'账号与会员',exact:true}).waitFor()
      await close(page)
    })
    await check('saved summary reuse at exhausted allowance does not prompt or spend quota',async()=>{
      await parse(page,'promptManual1')
      await saved(page)
      assert.equal(new URL(page.url()).hash,savedHash)
      assert.equal(await page.locator('dialog:modal').count(),0)
      assert.equal((await api(page,'/account/me')).data.quota.used,3)
    })
    await check('expired session switches a cached signed-in header to login',async()=>{
      assert.equal(await page.getByRole('button',{name:'账号 · 普通用户',exact:true}).count(),1)
      assert.equal((await api(page,'/account/logout',{})).status,200)
      await page.getByRole('button',{name:'重新生成',exact:true}).click()
      await page.getByRole('heading',{name:'登录账号',exact:true}).waitFor()
      await page.getByRole('button',{name:'登录',exact:true}).waitFor()
      await close(page)
    })
    await check('unrelated errors with login-like wording remain inline',async()=>{
      await page.route('**/api/v1/analyses/*/summary',route=>route.request().method()==='POST' ? route.fulfill({status:503,json:{detail:{code:'PROCESSING_FAILED',message:'模拟异常：请先登录只是文字，不是账号错误。'}}}) : route.continue())
      await page.getByRole('button',{name:'重新生成',exact:true}).click()
      await page.getByText('模拟异常：请先登录只是文字，不是账号错误。',{exact:true}).waitFor()
      assert.equal(await page.locator('dialog:modal').count(),0)
      await page.unroute('**/api/v1/analyses/*/summary')
    })
    await check('VIP exhaustion opens status details and keeps active repurchase blocked',async()=>{
      const expiry=Date.now()/1000+86400
      await page.route('**/api/v1/account/me',route=>route.fulfill({json:{email,simulated:true,order:null,quota:{limit:30,used:30,reserved:0,remaining:0,member_expires:expiry,day:'2026-10-08'}}}))
      await page.route('**/api/v1/analyses/*/summary',route=>route.request().method()==='POST' ? route.fulfill({status:429,json:{detail:{code:'QUOTA_EXCEEDED',message:'今日 AI 总结额度已用完（30 次），请明天再试或查看会员。'}}}) : route.continue())
      await page.reload({waitUntil:'networkidle'})
      await saved(page)
      await page.getByRole('button',{name:'重新生成',exact:true}).click()
      await page.getByRole('heading',{name:'账号与会员',exact:true}).waitFor()
      await page.getByText('今日已用 30 / 30 次').waitFor()
      assert.equal(await page.getByRole('button',{name:'会员已开通',exact:true}).isDisabled(),true)
      await page.setViewportSize({width:320,height:844})
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false)
      await capture(page,'vip-quota-mobile.png')
    })
    await check('viewing prompts does not create checkout requests or runtime errors',async()=>{ assert.equal(checkoutRequests,0); assert.deepEqual(errors,[]) })
  } finally {
    await fs.writeFile(path.join(output,'prompts-report.json'),JSON.stringify({checks,errors,checkoutRequests,simulation:true,vipQuotaSynthetic:true,realPayments:0,realModelCalls:0},null,2))
    console.log(JSON.stringify({passed:checks.length,errors,checkoutRequests}))
    await browser.close()
  }
})().catch(error=>{console.error(error.stack);process.exitCode=1})
