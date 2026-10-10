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

function page() {
  const calls: any[][] = [], dialogs: string[] = []
  let confirm = async () => {}
  let snapshot: any = { state: 'idle' }, readFailure = false
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted: () => {}, onUnmounted: () => {} },
    'vue-router': { useRouter: () => ({ push: () => {} }) },
    'element-plus': { ElMessageBox: { confirm: async (text: string) => { dialogs.push(text); await confirm() } } },
    axios: {
      post: async (url: string, body: any) => { calls.push([url, body]); return { data: { batch_id: 'new', state: 'running', phase: 'priming' } } },
      get: async (url: string) => { calls.push([url]); if(readFailure)throw new Error('offline'); return { data: snapshot } },
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
  state.fixed.value.filter((s: any) => ['productTime', 'cleanTime'].includes(s.key)).forEach((s: any) => { s.value = 60 })
  function ready() {
    state.validatedKey.value = state.requestKey.value
    state.plumbingConfirmed.value = state.primingConfirmed.value = state.initializationConfirmed.value = true
  }
  return { state, calls, dialogs, ready, confirmation: (fn: () => Promise<void>) => { confirm = fn },
    snapshot: (value: any) => { snapshot = value }, failRead: (value: boolean) => { readFailure = value }, dispose: () => scope.stop() }
}

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
