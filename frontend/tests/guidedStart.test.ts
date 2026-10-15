import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as batch from '../src/experiment/batch'
import * as drain from '../src/experiment/drainEstimate'
import * as priming from '../src/experiment/priming'

// Exercise the real page handlers and reactivity without hardware or a server.
const source = readFileSync(new URL('../src/views/BatchExperimentPage.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'guided-start-test' }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

function page(fill = true, fresh = false) {
  const route = { query: fresh ? {new: '1'} : {} as any }
  let getOverride: (() => Promise<any>) | undefined
  const calls: any[][] = [], dialogs: string[] = []
  let confirm = async () => {}
  let snapshot: any = { state: 'idle' }, readFailure = false
  let postResponse: any = { batch_id: 'new', state: 'running', phase: 'priming' }
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted: () => {}, onUnmounted: () => {} },
    'vue-router': { useRoute: () => route, useRouter: () => ({ push: () => {}, replace: async (value:any) => { route.query=value.query } }) },
    'element-plus': { ElMessageBox: { confirm: async (text: string) => { dialogs.push(text); await confirm() } } },
    axios: {
      post: async (url: string, body: any) => { calls.push([url, body]); return { data: postResponse } },
      get: async (url: string) => { calls.push([url]); if(readFailure)throw new Error('offline'); if(getOverride)return getOverride(); return { data: snapshot } },
    },
    '../experiment/batch': batch,
    '../experiment/drainEstimate': drain,
    '../experiment/priming': priming,
  }
  const exports = {} as any
  runInNewContext(compiled, { exports, require: (name: string) => {
    assert.ok(name in imports, name)
    return imports[name]
  } })
  const scope = vue.effectScope()
  const state = scope.run(() => exports.default.setup({}, { expose: () => {} }))
  state.registry.value = { heaters: { heater1: {}, heater2: {} }, syringe_pumps: { syringe_pump1: {}, syringe_pump2: {} }, microwaves: { microwave1: {} }, pumps: { pump1: {} }, valves: { valve1: {} } }
  if(fill) {
    state.experimentName.value='测试实验'
    state.primeHeatMinutes.value=0
    state.axes.value.forEach((a:any,i:number)=>{a.start=[30,30,0.1,0.1,30,1][i]})
    state.speedA.value=state.speedB.value=100
    state.repeats.value=1
    state.fixed.value.forEach((s:any)=>{s.value=['productTime','cleanTime'].includes(s.key)?60:1})
    state.priming.value.forEach((p:any)=>{p.value=p.key==='prime_cycles'?2:p.key==='prime_drain_seconds'?480:10})
  }
  function ready() {
    state.stage.value = 6
    state.validatedKey.value = state.requestKey.value
    state.plumbingConfirmed.value = state.primingConfirmed.value = state.initializationConfirmed.value = true
  }
  return { state, calls, dialogs, ready, route, readWith: (fn:()=>Promise<any>)=>{getOverride=fn}, confirmation: (fn: () => Promise<void>) => { confirm = fn },
    response: (value: any) => { postResponse = value },
    snapshot: (value: any) => { snapshot = value }, failRead: (value: boolean) => { readFailure = value }, dispose: () => scope.stop() }
}

test('new experiment clears parameters but preserves the terminal record and sends no control', async () => {
  const p = page()
  try {
    await vue.nextTick()
    const request = JSON.parse(p.state.requestKey.value)
    p.snapshot({ batch_id: 'failed', state: 'failed', request, error: '设备未初始化', progress: { elapsed: 12 } })
    await p.state.refreshBatch()
    p.ready()
    p.state.returnToSetup()
    assert.equal(p.state.showProgress.value, false)
    assert.equal(p.state.stage.value, 0)
    assert.equal(p.state.experimentName.value, '')
    assert.ok(p.state.axes.value.every((a:any)=>a.start===null&&a.end===null&&a.interval===null&&a.list===''))
    assert.ok(p.state.fixed.value.every((f:any)=>f.value===null))
    assert.ok(p.state.priming.value.every((f:any)=>f.value===null))
    assert.equal(p.state.primeHeatMinutes.value, null)
    assert.equal(p.state.repeats.value, null)
    assert.equal(p.state.speedA.value, null)
    assert.equal(p.state.newDraft.value, true)
    assert.equal(p.route.query.new, '1')
    assert.equal(p.state.batch.value.error, '设备未初始化')
    assert.equal(p.state.validatedKey.value, '')
    assert.equal(p.state.initializationConfirmed.value, false)
    assert.equal(p.state.plumbingConfirmed.value, false)
    assert.equal(p.state.primingConfirmed.value, false)
    await p.state.refreshBatch()
    assert.equal(p.state.showProgress.value, false)
    assert.ok(p.calls.every(c => c.length === 1))
  } finally { p.dispose() }
})

test('return to setup cannot bypass an active run, recovery, cleanup or persistence lock', () => {
  const p = page()
  try {
    for(const state of [{ state: 'running' }, { state: 'paused', phase: 'ready' },
      { state: 'failed', recovery_required: true }, { state: 'failed', cleanup_pending: true },
      { state: 'failed', persistence_status: 'error' }]) {
      p.state.batch.value = state
      p.state.showProgress.value = true
      p.state.returnToSetup()
      assert.equal(p.state.showProgress.value, true)
    }
    assert.equal(p.calls.length, 0)
  } finally { p.dispose() }
})

test('recovery cancellation keeps the failure; successful acknowledgement keeps the result until new experiment', async () => {
  const p = page()
  try {
    const failed = { batch_id: 'failed', state: 'failed', recovery_required: true, error: '设备未初始化' }
    p.state.batch.value = failed
    p.state.showProgress.value = true
    p.confirmation(async () => { throw 'cancel' })
    await p.state.acknowledgeInterrupted()
    assert.equal(p.calls.length, 0)
    assert.equal(p.state.showProgress.value, true)
    p.confirmation(async () => {})
    p.response({ ...failed, recovery_required: false, cleanup_pending: false })
    await p.state.acknowledgeInterrupted()
    assert.equal(p.calls.length, 1)
    assert.equal(p.calls[0][0], '/api/guided/failed/acknowledge-interrupted')
    assert.equal(p.state.showProgress.value, true)
    assert.equal(p.state.batch.value.state, 'failed')
    assert.equal(p.state.batch.value.error, failed.error)
  } finally { p.dispose() }
})

test('preparation page advances without priming; one click sends a complete batch start', async () => {
  const p = page()
  try {
    await vue.nextTick()
    p.state.stage.value = 5
    p.state.nextStage()
    assert.equal(p.state.stage.value, 6)
    assert.equal(p.state.error.value, '')
    assert.equal(p.calls.length, 0)
    p.ready()
    await p.state.startBatch()
    assert.equal(p.calls.length, 1)
    assert.equal(p.calls[0][0], '/api/guided/start')
    assert.equal(p.calls[0][1].priming_batch_id, undefined)
    assert.equal(p.calls[0][1].initialization_confirmed, true)
    assert.equal(p.state.showProgress.value, true)
    assert.match(p.dialogs[0], /预充并排废液/)
    await p.state.refreshBatch()
    assert.equal(p.calls.filter(c => c[0] === '/api/guided/start').length, 1)
  } finally { p.dispose() }
})

test('cancelled confirmation and parameter edits during confirmation dispatch no hardware request', async () => {
  const p = page()
  try {
    await vue.nextTick()
    p.ready()
    p.confirmation(async () => { throw 'cancel' })
    await p.state.startBatch()
    assert.equal(p.calls.length, 0)
    assert.equal(p.state.showProgress.value, false)
    p.confirmation(async () => { p.state.priming.value[0].value++ })
    await p.state.startBatch()
    assert.equal(p.calls.length, 0)
    assert.match(p.state.error.value, /变化/)
  } finally { p.dispose() }
})

test('refresh restores one progress screen and reports completed, active and pending groups from saved parameters', async () => {
  const p = page()
  try {
    const request = JSON.parse(p.state.requestKey.value)
    request.axes[0] = [30, 40]
    request.repeats = 2
    const snapshot = { batch_id: 'restored', state: 'paused', phase: 'experiments', current_group: 2, total_groups: 4, request,
      groups: [{ index: 1, state: 'completed' }, { index: 2, state: 'running', sample_id: 'S002' }],
      progress: { current_step: 9, total_steps: 24, step_id: 'hold', step_label: '反应保温', elapsed: 243 } }
    p.snapshot(snapshot)
    await p.state.refreshBatch()
    assert.equal(p.state.showProgress.value, true)
    assert.equal(p.state.completedGroups.value, 1)
    assert.equal(p.state.executionStage.value, 3)
    assert.equal(p.state.displayedStep.value, 10)
    assert.equal(p.state.elapsedLabel.value, '0:04:03')
    assert.equal(p.state.currentDevice.value, '微波反应仪')
    assert.equal(p.state.progressGroups.value[1].state, 'paused')
    assert.equal(p.state.progressGroups.value[2].state, 'pending')
    assert.equal(p.state.progressGroups.value[2].parameters[0], 40)
    p.state.showProgress.value = false
    await p.state.refreshBatch()
    assert.equal(p.state.showProgress.value, false)
    assert.ok(p.calls.every(c => c.length === 1))
    p.failRead(true)
    await p.state.refreshBatch()
    assert.match(p.state.refreshError.value, /上次收到/)
    assert.equal(p.state.completedGroups.value, 1)
    p.failRead(false)
    await p.state.refreshBatch()
    assert.equal(p.state.refreshError.value, '')
  } finally { p.dispose() }
})

test('progress highlights the executed phase and preserves failures without inventing completed groups', () => {
  const p = page()
  try {
    const snapshot = { batch_id: 'test', phase: 'priming', state: 'running', total_groups: 1, groups: [], progress: { step_id: 'prime_initialize_1', device_id: 'syringe_pump1' } } as any
    p.state.batch.value = snapshot
    assert.equal(p.state.executionStage.value, 0)
    assert.equal(p.state.completedGroups.value, 0)
    assert.equal(p.state.currentDevice.value, 'syringe_pump1')
    for(const [id, expected] of [['heat_both_stable', 1], ['feed_both', 2], ['hold', 3], ['cool_before_collection', 4], ['clean_0_out', 5]] as const) {
      p.state.batch.value = { ...snapshot, phase: 'experiments', progress: { step_id: id } }
      assert.equal(p.state.executionStage.value, expected)
    }
    p.state.batch.value = { ...snapshot, state: 'failed', phase: 'experiments', current_group: 1, groups: [{ index: 1, state: 'failed' }] }
    assert.equal(p.state.completedGroups.value, 0)
    assert.equal(p.state.progressGroups.value[0].state, 'failed')
    p.state.batch.value = { ...snapshot, state: 'completed', phase: 'experiments', groups: [{ index: 1, state: 'completed' }], progress: { current_step: 24, total_steps: 24 } }
    assert.equal(p.state.completedGroups.value, 1)
    assert.equal(p.state.displayedStep.value, 24)
    assert.equal(p.state.executionStage.value, -1)
    assert.equal(p.state.currentStepLabel.value, '全部实验组已完成')
  } finally { p.dispose() }
})

test('a matching existing ready batch starts with its ID and preserves priming', async () => {
  const p = page()
  try {
    await vue.nextTick()
    p.state.batch.value = { batch_id: 'prepared', state: 'paused', phase: 'ready', priming: { status: 'completed' }, request: JSON.parse(p.state.requestKey.value) }
    p.ready()
    assert.equal(p.state.primeReady.value, true)
    await p.state.startBatch()
    assert.equal(p.calls.length, 1)
    assert.equal(p.calls[0][1].priming_batch_id, 'prepared')
  } finally { p.dispose() }
})


test('blank defaults permit stepwise entry without coercing empty fields to zero', async () => {
  const p=page(false), s=p.state
  try {
    assert.ok(s.axes.value.every((a:any)=>a.start===null&&a.end===null&&a.interval===null&&a.list===''))
    assert.ok(s.fixed.value.every((f:any)=>f.value===null))
    assert.ok(s.priming.value.every((f:any)=>f.value===null))
    assert.equal(s.repeats.value,null)
    assert.equal(s.speedA.value,null)
    assert.equal(s.speedB.value,null)
    assert.equal(s.initialization.value[0].direction,'Z')
    assert.equal(s.initialization.value[0].initialization_code,0)
    assert.ok(Number.isNaN(s.primeTotal.value))
    s.nextStage();assert.equal(s.stage.value,0)
    s.experimentName.value='测试实验'
    s.axes.value[0].start=30;s.axes.value[1].start=30
    s.nextStage();assert.equal(s.stage.value,1)
    s.nextStage();assert.equal(s.stage.value,1)
    s.axes.value[2].start=0.1;s.axes.value[3].start=0.2
    s.speedA.value=s.speedB.value=100
    s.nextStage();assert.equal(s.stage.value,2)
    s.axes.value[4].start=80;s.axes.value[5].start=0
    s.nextStage();assert.equal(s.stage.value,3)
    s.fixed.value[0].value=10;s.fixed.value[1].value=60
    s.nextStage();assert.equal(s.stage.value,4)
    s.fixed.value.slice(2).forEach((f:any)=>{f.value=1})
    s.fixed.value.find((f:any)=>f.key==='wait').value=0
    assert.equal(s.stepError(4),'')
    s.fixed.value.find((f:any)=>f.key==='wait').value=''
    assert.ok(s.stepError(4))
    s.axes.value[0].start=''
    assert.ok(s.stepError(0))
    await s.validate();await s.startBatch()
    assert.equal(p.calls.length,0)
  } finally {p.dispose()}
})

test('range and list inputs require explicit values; clearing fields invalidates validated requests', async () => {
  const p=page(),s=p.state
  try {
    const a=s.axes.value[0]
    a.mode='range';a.start=30
    assert.ok(s.stepError(0))
    a.end=40;a.interval=5
    assert.equal(s.stepError(0),'')
    assert.deepEqual(Array.from(s.requestBody.value.axes[0]),[30,35,40])
    a.mode='list';a.list=''
    assert.ok(s.stepError(0))
    a.list='30, 35, 40'
    assert.equal(s.stepError(0),'')
    s.fixed.value.find((f:any)=>f.key==='drainFlow').value=10
    s.priming.value.find((f:any)=>f.key==='prime_drain_flow').value=2
    assert.equal(s.requestBody.value.drain_flow,10)
    assert.equal(s.requestBody.value.prime_drain_flow,2)
    assert.equal(s.requestBody.value.product_drain_seconds,60)
    assert.equal(s.requestBody.value.clean_drain_seconds,60)
    await vue.nextTick();p.ready()
    a.list='';await vue.nextTick()
    assert.equal(s.validatedKey.value,'')
    await s.startBatch();assert.equal(p.calls.length,0)
  } finally {p.dispose()}
})

test('missing capacity or repeat count blocks preview and start even with stale confirmations', async () => {
 const p=page(),s=p.state
 try {
  s.repeats.value=null
  await s.validate();assert.equal(p.calls.length,0)
  s.repeats.value=1;s.priming.value[5].value=null
  await vue.nextTick();p.ready()
  await s.validate();await s.startBatch()
  assert.equal(p.calls.length,0)
  assert.equal(s.advancedOpen.value,true)
 }finally{p.dispose()}
})


test('final-page confirmation reasons identify missing checks and parameter edits clear all three', async () => {
 const p=page(),s=p.state
 try {
  await vue.nextTick()
  s.stage.value=5
  assert.match(s.startBlockReason.value,/批次确认/)
  s.nextStage()
  assert.equal(s.stage.value,6)
  assert.match(s.startBlockReason.value,/校验/)
  s.validatedKey.value=s.requestKey.value
  assert.match(s.startBlockReason.value,/接管.*设备.*初始化/)
  s.plumbingConfirmed.value=true
  assert.match(s.startBlockReason.value,/设备.*初始化/)
  await s.startBatch();assert.equal(p.calls.length,0)
  s.primingConfirmed.value=true
  assert.equal(s.startBlockReason.value,'待确认：初始化与预充耗液')
  s.initializationConfirmed.value=true
  assert.equal(s.startBlockReason.value,'')
  s.repeats.value=2;await vue.nextTick()
  assert.equal(s.stage.value,6)
  assert.equal(s.plumbingConfirmed.value,false)
  assert.equal(s.primingConfirmed.value,false)
  assert.equal(s.initializationConfirmed.value,false)
  assert.match(s.startBlockReason.value,/校验/)
  p.ready();assert.equal(s.startBlockReason.value,'')
 }finally{p.dispose()}
})

test('batch locks explain disabled start and remain enforced across the confirmation dialog', async () => {
 const p=page(),s=p.state
 try {
  await vue.nextTick();p.ready()
  for(const [state,reason] of [
   [{state:'running'},/运行中/],
   [{state:'failed',recovery_required:true},/恢复锁定/],
   [{state:'completed',cleanup_pending:true},/清理/],
   [{state:'paused',phase:'ready'},/不匹配/]
  ] as const){
   s.batch.value=state
   assert.match(s.startBlockReason.value,reason)
   await s.startBatch();assert.equal(p.calls.length,0)
  }
  s.batch.value={state:'idle'}
  p.confirmation(async()=>{s.batch.value={state:'failed',recovery_required:true}})
  await s.startBatch();assert.equal(p.calls.length,0)
  assert.match(s.error.value,/变化/)
 }finally{p.dispose()}
})


test('precharge heating time is required, signed, reset on edits and restored without filling legacy values', async () => {
 const p=page(),s=p.state
 try {
  s.primeHeatMinutes.value=null
  assert.match(s.stepError(5),/预充前加热时间/)
  s.primeHeatMinutes.value=0
  assert.equal(s.stepError(5),'')
  s.primeHeatMinutes.value=0.001
  assert.match(s.stepError(5),/整秒/)
  s.primeHeatMinutes.value=30
  await vue.nextTick();p.ready()
  const key=s.requestKey.value
  assert.equal(s.requestBody.value.prime_heat_minutes,30)
  s.primeHeatMinutes.value=45;await vue.nextTick()
  assert.notEqual(key,s.requestKey.value)
  assert.equal(s.validatedKey.value,'')
  const request=JSON.parse(s.requestKey.value)
  p.snapshot({state:'stopped',phase:'priming',request})
  s.primeHeatMinutes.value=null
  await s.refreshBatch()
  assert.equal(s.primeHeatMinutes.value,45)
 }finally{p.dispose()}
 const legacy=page()
 try{
  const request=JSON.parse(legacy.state.requestKey.value)
  delete request.prime_heat_minutes
  legacy.snapshot({state:'paused',phase:'ready',request,priming:{status:'completed'}})
  await legacy.state.refreshBatch()
  assert.equal(legacy.state.primeHeatMinutes.value,null)
  assert.equal(legacy.state.primeReady.value,false)
 }finally{legacy.dispose()}
})


test('reuse copies saved parameters into a named new batch, without reusing priming', async () => {
 const p=page(),s=p.state
 try{
  const request=JSON.parse(s.requestKey.value)
  p.snapshot({batch_id:'old',state:'stopped',phase:'experiments',request,priming:{status:'completed'}})
  await s.refreshBatch()
  s.axes.value[0].start=99
  s.returnToSetup(true)
  assert.equal(s.axes.value[0].start,30)
  assert.equal(s.experimentName.value,'')
  assert.equal(s.primeReady.value,false)
  assert.equal(s.requestBody.value.priming_batch_id,undefined)
  assert.match(s.stepError(0),/实验名称/)
  s.experimentName.value='另一次实验'
  await vue.nextTick();p.ready()
  await s.startBatch()
  const start=p.calls.find(c=>c[0]==='/api/guided/start')!
  assert.equal(start[1].experiment_name,'另一次实验')
  assert.equal(start[1].priming_batch_id,undefined)
  assert.equal(s.newDraft.value,false)
  assert.equal(p.route.query.new,undefined)
 }finally{p.dispose()}
})

test('fresh URL ignores terminal records on reload but restores active and recovery batches', async () => {
 for(const snapshot of [{state:'completed'},{state:'running'}, {state:'paused',phase:'ready'},
  {state:'failed',recovery_required:true},{state:'failed',cleanup_pending:true},{state:'failed',persistence_status:'error'}]){
  const original=page(),p=page(false,true),s=p.state
  try{
   p.snapshot({batch_id:'saved',request:JSON.parse(original.state.requestKey.value),...snapshot})
   await s.refreshBatch()
   const blocked=snapshot.state!=='completed'
   assert.equal(s.showProgress.value,blocked)
   assert.equal(s.newDraft.value,!blocked)
   assert.equal(s.experimentName.value,blocked?'测试实验':'')
   assert.equal(s.axes.value[0].start,blocked?30:null)
  }finally{p.dispose();original.dispose()}
 }
})

test('a stale poll cannot restore parameters after new or overwrite a newer response', async () => {
 const p=page(),s=p.state
 try{
  const old={batch_id:'old',state:'stopped',request:JSON.parse(s.requestKey.value)}
  p.snapshot(old);await s.refreshBatch()
  let resolve!:(value:any)=>void
  p.readWith(()=>new Promise(done=>{resolve=done}))
  const pending=s.refreshBatch()
  s.returnToSetup()
  resolve({data:old});await pending
  assert.equal(s.experimentName.value,'');assert.equal(s.axes.value[0].start,null)
  const stale=s.refreshBatch(),finishOld=resolve
  const recent=s.refreshBatch()
  resolve({data:{...old,batch_id:'newer',state:'running'}});await recent
  finishOld({data:old});await stale
  assert.equal(s.batch.value.batch_id,'newer')
  assert.equal(s.showProgress.value,true)
 }finally{p.dispose()}
})

test('names validate, invalidate confirmation, trim requests and leave legacy records unnamed', async () => {
 const p=page(),s=p.state
 try{
  for(const name of ['', '   ', '字'.repeat(81),'a\nb','a\tb','a\u0000b','a\u2028b']){
   s.experimentName.value=name
   assert.match(s.stepError(0),/实验名称/)
  }
  s.experimentName.value='  脱气对比 🧪  '
  assert.equal(s.stepError(0),'')
  assert.equal(s.requestBody.value.experiment_name,'脱气对比 🧪')
  await vue.nextTick();p.ready()
  s.experimentName.value='另一名称';await vue.nextTick()
  assert.equal(s.validatedKey.value,'');assert.equal(s.plumbingConfirmed.value,false)
  const request=JSON.parse(s.requestKey.value);delete request.experiment_name
  p.snapshot({batch_id:'legacy',state:'completed',request})
  await s.refreshBatch()
  assert.equal(s.experimentName.value,'');assert.equal(s.primeReady.value,false)
 }finally{p.dispose()}
})
