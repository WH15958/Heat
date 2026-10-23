import assert from 'node:assert/strict'
import { test } from 'node:test'
import { webcrypto } from 'node:crypto'
import { deferred, moduleFromSource, plain, view, vue } from './helpers/sfc'
import * as devices from '../src/api/devices'
import * as program from '../src/utils/microwaveProgram'
import * as connection from '../src/composables/connectionBatch'
import * as calculations from '../src/utils/pumpCalculations'
import * as batch from '../src/experiment/batch'
import * as drain from '../src/experiment/drainEstimate'
import * as priming from '../src/experiment/priming'
import * as progress from '../src/experiment/guidedProgress'
import * as document from '../src/experiment/document'
import * as confirmations from '../src/composables/pendingConfirmation'

const heaterRegistry = { heaters: { heater1: { connected: true, min_temperature: 0, max_temperature: 200 } } }
function control(api: any, globals: any = {}) {
  const prompts: ReturnType<typeof deferred>[] = []
  const page = view('views/ControlPanel.vue', {
    '../api/devices': { ...devices, devicesApi: api }, '../api/syringePumps': { syringeApi: {} }, '../api/turntables': { turntableApi: {} },
    '../utils/microwaveProgram': program, '../utils/pumpCalculations': calculations,
    '../composables/connectionBatch': connection,
    '../composables/useWebSocket': { useWebSocket: () => ({ data: vue.ref(null), fresh: vue.ref(true) }) },
    'element-plus': { ElMessage: Object.assign(() => ({ close() {} }), { error() {}, info() {}, success() {} }),
      ElMessageBox: { confirm: () => { const prompt = deferred(); prompts.push(prompt); return prompt.promise } } },
  }, { crypto: webcrypto, ...globals })
  page.state.applyDeviceData(heaterRegistry)
  return { ...page, prompts }
}

for (const invalidate of ['unmount', 'stop', 'disconnect', 'emergency', 'parameters', 'connection'] as const) {
  test(`pending heater confirmation is revoked by ${invalidate}, without replaying a start`, async () => {
    const writes: string[] = []
    const p = control({
      startHeater: async () => { writes.push('start'); return { data: { success: true } } },
      stopHeater: async () => { writes.push('stop'); return { data: { success: true } } },
      disconnectHeater: async () => { writes.push('disconnect'); return { data: { success: true } } },
      emergencyStop: async () => { writes.push('emergency'); return { data: { success: true } } },
      list: async () => ({ data: heaterRegistry }),
    })
    try {
      const start = p.state.startHeater('heater1')
      await p.state.startHeater('heater1')
      assert.equal(p.prompts.length, 1) // A second click cannot open another confirmation.
      if (invalidate === 'unmount') p.unmount()
      if (invalidate === 'stop') await p.state.stopHeater('heater1')
      if (invalidate === 'disconnect') await p.state.disconnectHeater('heater1')
      if (invalidate === 'parameters') p.state.devices.heaters.heater1.targetTemp++
      if (invalidate === 'connection') {
        p.state.devices.heaters.heater1.connected = false
        p.state.devices.heaters.heater1.connected = true
      }
      if (invalidate === 'emergency') { const stop = p.state.emergencyStop(); p.prompts[1]!.resolve(); await stop }
      p.prompts[0]!.resolve(); await start
      assert.ok(!writes.includes('start'))
      assert.deepEqual(writes, ['stop', 'disconnect', 'emergency'].includes(invalidate) ? [invalidate] : [])
    } finally { p.dispose() }
  })
}

test('current heater confirmation writes once; unmount adds no stop; temperature confirmation also expires', async () => {
  const writes: string[] = []
  const p = control({ startHeater: async () => { writes.push('start'); return { data: { success: true } } },
    setTemperature: async () => { writes.push('temperature'); return { data: { success: true } } } })
  try {
    const start = p.state.startHeater('heater1'); p.prompts[0]!.resolve(); await start
    const temperature = p.state.setTemp('heater1', 40)
    p.unmount(); p.prompts[1]!.resolve(); await temperature
    assert.deepEqual(writes, ['start'])
  } finally { p.dispose() }
})

test('WebSocket loss cancels a pending start while the explicit emergency stop remains usable', async () => {
  const writes: string[] = []
  const p = control({ startHeater: async () => { writes.push('start'); return { data: { success: true } } },
    emergencyStop: async () => { writes.push('emergency'); return { data: { success: true } } },
    list: async () => ({ data: heaterRegistry }) })
  try {
    const start = p.state.startHeater('heater1')
    const stop = p.state.emergencyStop()
    p.state.wsConnected.value = false
    p.prompts[1]!.resolve(); await stop
    p.prompts[0]!.resolve(); await start
    assert.deepEqual(writes, ['emergency'])
  } finally { p.dispose() }
})

test('checked microwave program cannot start after unmount', async () => {
  const writes: string[] = []
  const p = control({ previewMicrowaveProgram: async () => ({ data: { success: true } }),
    startMicrowaveProgram: async () => { writes.push('start'); return { data: { state: 'running' } } } })
  try {
    p.state.applyDeviceData({ microwaves: { microwave1: { connected: true, connection_port: 'FAKE' } } })
    p.state.microwaveSnapshots.microwave1 = { status_confirmed: true, control_active: false, fault_code: 0, power_percent: 0, current: 0 }
    await p.state.configureMicrowave('microwave1')
    const start = p.state.startMicrowave('microwave1')
    assert.equal(p.prompts.length, 1)
    p.unmount(); p.prompts[0]!.resolve(); await start
    assert.deepEqual(writes, [])
  } finally { p.dispose() }
})

for (const kind of ['valve', 'initialize', 'store'] as const) {
  for (const invalidation of ['unmount', 'global-stop'] as const) {
    test(`${kind} confirmation is revoked by ${invalidation}`, async () => {
      const prompt = deferred(), writes: any[] = [], epoch = vue.ref(0)
      const state = vue.reactive({ device_id: 'fake', name: 'fake', capacity_ml: 2.5, connected: true, read_ok: true,
        busy: false, position_trusted: true, fault_code: 0, binding_resolved: true, connection_port: 'FAKE' })
      const p = view(kind === 'valve' ? 'components/ValveControl.vue' : 'components/SyringePumpControl.vue', {
        '../composables/pendingConfirmation': { usePendingConfirmation: () => confirmations.usePendingConfirmation(epoch) },
        '../api/devices': { devicesApi: { valveOperation: async (...args: any[]) => { writes.push(args); return { data: { success: true } } } } },
        '../api/syringePumps': { syringeResult: {}, syringeApi: {
          command: async (...args: any[]) => { writes.push(args); return { data: {} } }, read: async () => ({ data: state }),
        } },
        'element-plus': { ElMessage: {}, ElMessageBox: { confirm: () => prompt.promise } },
      }, {}, { state, valveId: 'fake' })
      try {
        const action = kind === 'valve' ? p.state.switchPosition(true) : kind === 'store' ? p.state.storeProgram() : p.state.initialize()
        if (invalidation === 'unmount') p.unmount(); else epoch.value++
        prompt.resolve(); await action
        assert.deepEqual(writes, [])
      } finally { p.dispose() }
    })
  }
}

test('syringe stop revokes a pending initialization and only sends stop', async () => {
  const prompt = deferred(), writes: any[] = []
  const state = { device_id: 'fake', name: 'fake', capacity_ml: 2.5, connected: true, read_ok: true, busy: false, position_trusted: true, fault_code: 0 }
  const p = view('components/SyringePumpControl.vue', {
    '../api/syringePumps': { syringeResult: {}, syringeApi: { command: async (_: any, body: any) => { writes.push(body.action); return { data: {} } }, read: async () => ({ data: state }) } },
    'element-plus': { ElMessage: { info() {} }, ElMessageBox: { confirm: () => prompt.promise } },
  }, {}, { state })
  try {
    const start = p.state.initialize(); await p.state.send({ action: 'stop' }, true)
    prompt.resolve(); await start
    assert.deepEqual(writes, ['stop'])
  } finally { p.dispose() }
})

test('guided confirmation after leaving sends no hardware start or stop', async () => {
  const prompt = deferred(), writes: any[] = []
  const p = view('views/BatchExperimentPage.vue', {
    '../experiment/batch': batch, '../experiment/drainEstimate': drain, '../experiment/priming': priming, '../experiment/guidedProgress': progress,
    axios: { post: async (...args: any[]) => { writes.push(args); return { data: {} } } },
    'element-plus': { ElMessageBox: { confirm: () => prompt.promise } },
  }, { document: { querySelector: () => null } })
  try {
    const s = p.state
    s.registry.value = { heaters: { heater1: {}, heater2: {} }, syringe_pumps: { syringe_pump1: {}, syringe_pump2: {} }, microwaves: { microwave1: {} }, pumps: { pump1: {} }, valves: { valve1: {} } }
    s.experimentName.value = 'isolated'; s.primeHeatMinutes.value = 0
    s.axes.value.forEach((a: any, i: number) => { a.start = [30, 30, 0.1, 0.1, 30, 1][i] })
    s.speedA.value = s.speedB.value = 100; s.repeats.value = 1
    s.fixed.value.forEach((f: any) => { f.value = ['productTime', 'cleanTime'].includes(f.key) ? 60 : 1 })
    s.priming.value.forEach((f: any) => { f.value = f.key === 'prime_cycles' ? 2 : f.key === 'prime_drain_seconds' ? 480 : 10 })
    await vue.nextTick()
    s.stage.value = 6; s.validatedKey.value = s.requestKey.value
    s.plumbingConfirmed.value = s.primingConfirmed.value = s.initializationConfirmed.value = true
    assert.equal(s.startBlockReason.value, '')
    const start = s.startBatch(); p.unmount(); prompt.resolve(); await start
    assert.deepEqual(writes, [])
  } finally { p.dispose() }
})

function experiment(get: (url: string) => Promise<any>, confirm = async () => {}) {
  const posts: string[] = []
  const p = view('views/ExperimentPage.vue', { axios: { get, post: async (url: string) => { posts.push(url); return { data: { success: true } } } },
    'element-plus': { ElMessage: { error() {}, success() {}, warning() {}, info() {} }, ElMessageBox: { confirm } } })
  return { ...p, posts }
}
const details = (name: string) => ({ name, steps: [] })

test('failed selection clears the old experiment and cannot start the failed target', async () => {
  const p = experiment(async url => {
    if (url.endsWith('/progress')) return { data: { state: 'idle' } }
    if (url.endsWith('/A.yaml')) return { data: details('A') }
    throw new Error('offline')
  })
  try {
    await p.state.selectExperiment('A.yaml'); await p.state.selectExperiment('B.yaml'); await p.state.startExperiment()
    assert.equal(p.state.selectedExp.value, null)
    assert.equal(p.state.selectedFilename.value, '')
    assert.deepEqual(p.posts, [])
  } finally { p.dispose() }
})

test('out-of-order selection and progress responses cannot replace current experiment identity', async () => {
  const a = deferred(), b = deferred(), oldProgress = deferred()
  let readOldProgress = false
  const p = experiment(async url => {
    if (url.endsWith('/A.yaml')) return a.promise
    if (url.endsWith('/B.yaml')) return b.promise
    if (readOldProgress && url.includes('A.yaml')) return oldProgress.promise
    return { data: { state: 'idle' } }
  })
  try {
    const first = p.state.selectExperiment('A.yaml'), second = p.state.selectExperiment('B.yaml')
    b.resolve({ data: details('B') }); await second; a.resolve({ data: details('A') }); await first
    assert.equal(p.state.selectedFilename.value, 'B.yaml'); assert.equal(p.state.selectedExp.value.name, 'B')
    await p.state.selectExperiment('A.yaml'); readOldProgress = true
    const poll = p.state.pollProgress(); await p.state.selectExperiment('B.yaml')
    oldProgress.resolve({ data: { state: 'running', step_id: 'old-A' } }); await poll
    assert.equal(p.state.progress.value.state, 'idle')
  } finally { p.dispose() }
})

test('changing experiment while start confirmation is pending cancels the old start', async () => {
  const prompt = deferred()
  const p = experiment(async url => ({ data: url.endsWith('/recovery/pending') ? [] : url.endsWith('/progress') ? { state: 'idle' } : details(url) }), () => prompt.promise)
  try {
    await p.state.selectExperiment('A.yaml')
    const starting = p.state.startExperiment(); await vue.nextTick()
    await p.state.selectExperiment('B.yaml'); prompt.resolve(); await starting
    assert.deepEqual(p.posts, [])
  } finally { p.dispose() }
})

for (const filename of ['中文 空间.yaml', 'test#1.yaml', 'batch%20a.yaml']) {
  test(`every experiment operation encodes filename ${filename}`, async () => {
    const reads: string[] = []
    const p = experiment(async url => { reads.push(url); return { data: url.endsWith('/recovery/pending') ? [] : url.endsWith('/progress') ? { state: 'idle' } : details(filename) } })
    try {
      await p.state.previewExperiment(filename); await p.state.selectExperiment(filename)
      await p.state.startExperiment(); await p.state.pauseExperiment(); await p.state.resumeExperiment(); await p.state.stopExperiment()
      const base = `/api/experiments/${encodeURIComponent(filename)}`
      assert.deepEqual(p.posts, ['start', 'pause', 'resume', 'stop'].map(action => `${base}/${action}`))
      assert.ok(reads.includes(base)); assert.ok(reads.includes(`${base}/progress`))
      assert.equal(decodeURIComponent(new URL(base, 'http://test.invalid').pathname.split('/').at(-1)!), filename)
    } finally { p.dispose() }
  })
}

test('Campaign late success, late failure and unmounted reads cannot contaminate current records', async () => {
  for (const staleFailure of [false, true]) {
    const responses = { A: deferred(), B: deferred(), C: deferred() }
    const p = view('views/CampaignPage.vue', { '../api/campaigns': { campaignsApi: {
      listTrials: (id: keyof typeof responses) => responses[id].promise.then(() => ({ data: [{ campaign_id: id }] })),
      listCharacterizations: (id: keyof typeof responses) => responses[id].promise.then(() => ({ data: [{ campaign_id: id }] })),
    } } })
    try {
      const a = p.state.selectCampaign({ campaign_id: 'A' }), b = p.state.selectCampaign({ campaign_id: 'B' })
      assert.deepEqual(plain(p.state.trials.value), [])
      responses.B.resolve(); await b
      if (staleFailure) responses.A.reject(new Error('late failure')); else responses.A.resolve()
      await a
      assert.equal(p.state.trials.value[0].campaign_id, 'B'); assert.equal(p.state.characterizations.value[0].campaign_id, 'B')
      assert.deepEqual(p.messages, [])
      const c = p.state.selectCampaign({ campaign_id: 'C' }); p.unmount(); responses.C.resolve(); await c
      assert.deepEqual(plain(p.state.trials.value), [])
    } finally { p.dispose() }
  }
})

test('Campaign independent link patches preserve both edits when applied in reverse order', async () => {
  const requests: any[] = [], stored = { run_id: 'old-run', sample_id: 'old-sample' }
  const p = view('views/CampaignPage.vue', { '../api/campaigns': { campaignsApi: {
    updateTrial: async (_: string, __: string, patch: any) => { const done = deferred(); requests.push({ patch: plain(patch), done }); await done.promise; Object.assign(stored, patch); return { data: stored } },
  } } })
  try {
    p.state.selectedCampaign.value = { campaign_id: 'A' }
    const row = { campaign_id: 'A', trial_id: 'trial', run_id: 'new-run', sample_id: 'old-sample' }
    const run = p.state.updateTrialLinks(row, 'run_id'); row.sample_id = 'new-sample'
    const sample = p.state.updateTrialLinks(row, 'sample_id')
    assert.deepEqual(requests.map(r => r.patch), [{ run_id: 'new-run' }, { sample_id: 'new-sample' }])
    requests[1].done.resolve(); await sample; requests[0].done.resolve(); await run
    assert.deepEqual(stored, { run_id: 'new-run', sample_id: 'new-sample' })
  } finally { p.dispose() }
})

function editor(api: any) {
  return view('views/ExperimentEditor.vue', { '../experiment/document': document,
    '../experiment/catalog': moduleFromSource('experiment/catalog.ts', { '../api/devices': devices }),
    '../api/devices': { devicesApi: {} }, '../api/experimentEditor': { editorApi: api } })
}
test('dual-heater reach is editable without stability fields and retains two required targets', async () => {
  const catalog = moduleFromSource('experiment/catalog.ts', { '../api/devices': devices })
  assert.ok(catalog.waitOptions.some((option:any) => option.value === 'heater_pair_reached'))
  assert.deepEqual(plain(catalog.waitFields('heater_pair_reached')).map((field:any) => field.key), ['timeout'])
  assert.deepEqual(plain(catalog.waitFields('heater_pair_stable')).map((field:any) => field.key), ['seconds', 'tolerance', 'timeout'])
  const p = editor({})
  try {
    const s = p.state
    s.source.value = 'name: reach\nsteps:\n  - id: preheat\n    type: wait\n    wait:\n      type: heater_pair_stable\n      seconds: 30\n      tolerance: 3\n      timeout: 3600\n      targets:\n        - {device_id: heater1, target_temperature: 50}\n        - {device_id: heater2, target_temperature: 60}\n'
    await vue.nextTick()
    s.changeWaitType('heater_pair_reached')
    await vue.nextTick()
    assert.equal(s.step.value.wait.type, 'heater_pair_reached')
    assert.equal(s.step.value.wait.seconds, undefined)
    assert.equal(s.step.value.wait.tolerance, undefined)
    assert.equal(s.step.value.wait.timeout, 3600)
    assert.deepEqual(plain(s.step.value.wait.targets), [{device_id:'heater1',target_temperature:50}, {device_id:'heater2',target_temperature:60}])
    assert.deepEqual(plain(s.localErrors.value), [])
    s.set(['steps', 0, 'wait', 'targets', 1, 'target_temperature'], undefined)
    await vue.nextTick()
    assert.ok(s.localErrors.value.some((error:string) => error.includes('目标温度')))
  } finally { p.dispose() }
})

test('late save cannot bind imported B to A; next save targets B without A revision', async () => {
  const pending = deferred(), writes: any[] = []
  const p = editor({ save: async (...args: any[]) => { writes.push(args); return writes.length === 1 ? pending.promise : { data: { revision: 'rev-B' } } } })
  try {
    const s = p.state
    s.source.value = s.baseline.value = 'name: A\nsteps: []\n'; s.filename.value = s.loadedFilename.value = 'A.yaml'; s.revision.value = 'rev-A'
    const save = s.save('A.yaml')
    await s.importFile({ target: { files: [{ name: 'B.yaml', size: 20, text: async () => 'name: B\nsteps: []\n' }], value: '' } })
    pending.resolve({ data: { revision: 'rev-A2' } }); await save
    assert.equal(s.filename.value, 'B.yaml'); assert.equal(s.loadedFilename.value, ''); assert.equal(s.revision.value, null)
    await s.save('B.yaml')
    assert.deepEqual(writes[1], ['B.yaml', 'name: B\nsteps: []\n', null])
  } finally { p.dispose() }
})
test('same-document save keeps later edits dirty and old load cannot replace new document', async () => {
  const saved = deferred(), old = deferred()
  const p = editor({ save: () => saved.promise, read: async (name: string) => name === 'old.yaml' ? old.promise : { data: { content: 'name: New\nsteps: []\n', revision: 'rev-new' } } })
  try {
    const s = p.state
    s.source.value = 'name: A\nsteps: []\n'; s.filename.value = 'A.yaml'
    const save = s.save('A.yaml'); s.changeSource('name: changed\nsteps: []\n')
    saved.resolve({ data: { revision: 'rev-A' } }); await save
    assert.equal(s.source.value, 'name: changed\nsteps: []\n'); assert.equal(s.dirty.value, true)
    const first = s.load('old.yaml'); await s.load('new.yaml')
    old.resolve({ data: { content: 'name: Old\nsteps: []\n', revision: 'rev-old' } }); await first
    assert.equal(s.loadedFilename.value, 'new.yaml'); assert.equal(s.source.value, 'name: New\nsteps: []\n')
  } finally { p.dispose() }
})

for (const name of ['QuotaExceededError', 'SecurityError']) {
  test(`${name} stays contained in control parameter watcher and clears after a successful write`, async () => {
    let fail = true, saved = ''
    const p = control({ list: async () => ({ data: heaterRegistry }) }, {
      localStorage: { getItem: () => null, setItem: (_: string, value: string) => { if (fail) throw new Error(name); saved = value } },
    })
    try {
      await p.state.refreshDevices(false); await vue.nextTick()
      p.state.devices.heaters.heater1.targetTemp = 45; await vue.nextTick()
      assert.match(p.state.paramsStorageError.value, /未保存/)
      assert.equal(p.state.devices.heaters.heater1.targetTemp, 45)
      fail = false; p.state.devices.heaters.heater1.targetTemp = 46; await vue.nextTick()
      assert.equal(p.state.paramsStorageError.value, '')
      assert.equal(JSON.parse(saved).heater1.targetTemp, 46)
    } finally { p.dispose() }
  })
}
