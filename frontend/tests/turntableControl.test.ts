import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import { renderToString } from 'vue/server-renderer'
import ts from 'typescript'
import { view, vue, deferred, plain } from './helpers/sfc'
import { turntableResult, turntableWorkState, type TurntableState } from '../src/api/turntables'

function device(): TurntableState {
  return { device_id: 'turntable1', name: '接样转盘', configured: true, connected: true,
    read_ok: true, read_at: new Date().toISOString(), busy: false, position: 0,
    speed_raw: 0, input_raw: 255, inputs: null, work_state: 0x20, state_name: 'stopped',
    stop_confirmed: true, motion_blocked: false, homed: false, home_enabled: false, position_encoding_verified: false }
}

function card() {
  const state = vue.reactive(device()), calls: any[] = []
  const api = {
    connect: async (_id: string) => ({ data: { success: true } }),
    command: async (_id: string, body: any) => { calls.push(plain(body)); return { data: { result: { result: 'accepted' }, state } } },
    read: async () => ({ data: state }),
  }
  const page = view('components/TurntableControl.vue', {
    '../api/turntables': { turntableApi: api, turntableResult, turntableWorkState },
  }, {}, { state })
  return { ...page, device: state, api, calls }
}

async function renderCard(state: TurntableState) {
  const source = readFileSync(new URL('../src/components/TurntableControl.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(source).descriptor, { id: 'turntable-acceptance', inlineTemplate: true }).content
  const code = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports: any = {}
  const imports: Record<string, any> = { vue, '../api/turntables': { turntableResult, turntableWorkState },
    './DeviceConnectionControls.vue': { default: { render: () => null } }, '../assets/theme/turntable.svg': { default: 'turntable.svg' } }
  runInNewContext(code, { exports, require: (name: string) => imports[name] ?? {} })
  const app = vue.createSSRApp(exports.default, { state })
  app.config.warnHandler = () => {}
  app.component('ElAlert', { props: ['title'], setup: props => () => vue.h('div', { role: 'alert' }, props.title) })
  for (const name of ['ElTag', 'ElSelect', 'ElOption', 'ElInputNumber', 'ElButton', 'ElDivider']) {
    app.component(name, { setup: (_, { slots }) => () => vue.h('div', {}, slots.default?.()) })
  }
  return renderToString(app)
}

test('failed connection refreshes the persistent server error and releases pending state', async () => {
  const p = card()
  let reads = 0
  try {
    p.device.connected = false
    p.device.read_ok = false
    p.api.connect = async () => { throw new Error('无法配置串口，Windows 错误 31') }
    p.api.read = async () => { reads++; return { data: { ...p.device, connection_error: '无法配置串口，Windows 错误 31' } } }
    await p.state.connect()
    assert.equal(reads, 1)
    assert.equal(p.device.connected, false)
    assert.equal(p.state.pending.value, 0)
    assert.ok(p.messages.some(message => message[0] === 'error' && message[1].includes('Windows 错误 31')))
    assert.equal(p.calls.length, 0)
  } finally { p.unmount() }
})

test('actual turntable card preserves connection failure while ordinary disconnect and read failure remain distinct', async () => {
  const state = { ...device(), connected: false, read_ok: false }
  assert.doesNotMatch(await renderCard(state), /role="alert"/)
  const failed = { ...state, connection_error: '无法配置串口，Windows 错误 31' }
  assert.match(await renderCard(failed), /role="alert"[^>]*>连接失败：无法配置串口，Windows 错误 31/)
  assert.match(await renderCard({ ...failed, binding_error: '未找到指定 USB 设备' }), /role="alert"[^>]*>未找到指定 USB 设备/)
  const readFailure = await renderCard({ ...failed, connected: true, read_error: '状态读取超时' })
  assert.match(readFailure, /role="alert"[^>]*>状态读取超时/)
  assert.doesNotMatch(readFailure, /连接失败：/)
  assert.doesNotMatch(await renderCard({ ...device(), connection_error: null }), /role="alert"/)
})

test('unverified positioning and home never dispatch; bounded directional run uses pulse speed', async () => {
  const p = card()
  try {
    assert.equal(p.state.speed.value, 400)
    assert.equal(p.state.canMove.value, true)
    assert.equal(p.state.canPosition.value, false)
    await p.state.send({ action: 'move_relative', steps: 100, speed: 400 })
    await p.state.send({ action: 'move_absolute', position: 0, speed: 400 })
    await p.state.send({ action: 'home', direction: 'negative', speed: 400 })
    await p.state.send({ action: 'run', direction: 'positive', speed: 400, duration_seconds: 61 })
    assert.equal(p.calls.length, 0)
    await p.state.send({ action: 'run', direction: 'positive', speed: 400, duration_seconds: 10 })
    assert.deepEqual(p.calls, [{ action: 'run', direction: 'positive', speed: 400, duration_seconds: 10 }])
    p.device.position_encoding_verified = true
    assert.equal(p.state.canPosition.value, true)
    await p.state.send({ action: 'move_absolute', position: 0, speed: 400 })
    assert.equal(p.calls[1].position, 0)
  } finally { p.unmount() }
})

function readyBottles(p: ReturnType<typeof card>, bottle = 1, position = 0) {
  Object.assign(p.device, { bottle_count: 12, pulses_per_bottle: 12000, current_bottle: bottle,
    next_bottle: bottle === 12 ? 1 : bottle + 1, bottle_ready: true, bottle_error: null, bottle_token: 'reference-1',
    home_enabled: true, position_encoding_verified: true, position })
}

test('bottle controls require server-established reference and do not infer bottle 1 from zero', async () => {
  const p = card()
  try {
    assert.equal(p.state.currentBottle.value, null)
    assert.equal(p.state.canNextBottle.value, false)
    assert.equal(p.state.canHomeBottle.value, false)
    await p.state.nextBottle()
    Object.assign(p.device, { bottle_count: 12, pulses_per_bottle: 12000, home_enabled: true,
      position_encoding_verified: false, current_bottle: null, bottle_ready: false })
    assert.equal(p.state.canHomeBottle.value, false)
    await p.state.send({ action: 'home_bottle' })
    assert.equal(p.calls.length, 0)
    p.device.position_encoding_verified = true
    assert.equal(p.state.canHomeBottle.value, true)
    assert.equal(p.state.currentBottle.value, null)
    await p.state.nextBottle()
    p.state.speed.value = NaN // An advanced setting cannot prevent the calibrated home command.
    await p.state.send({ action: 'home_bottle' })
    assert.deepEqual(p.calls, [{ action: 'home_bottle' }])
    assert.equal(p.state.currentBottle.value, null) // Submission does not claim completion.
  } finally { p.unmount() }
})

test('next bottle uses server coordinate precondition with no browser pulse arithmetic, including 12 to 1', async () => {
  const p = card()
  try {
    readyBottles(p, 12, 132000)
    p.state.speed.value = NaN // Simple controls use backend calibration speed.
    assert.equal(p.state.currentBottle.value, 12)
    await p.state.send({ action: 'next_bottle', expected_position: 120000, expected_bottle_token: 'reference-1' })
    await p.state.send({ action: 'next_bottle', expected_position: 132000, expected_bottle_token: 'previous-home' })
    assert.equal(p.calls.length, 0)
    await p.state.nextBottle()
    assert.deepEqual(p.calls, [{ action: 'next_bottle', expected_position: 132000, expected_bottle_token: 'reference-1' }])
    assert.equal(p.device.current_bottle, 12)
    p.device.bottle_token = null
    assert.equal(p.state.canNextBottle.value, false)
  } finally { p.unmount() }
})

test('bottle change rejects repeated clicks, stale reads and uncertain reference while stop stays usable', async () => {
  const p = card(), response = deferred<any>()
  try {
    readyBottles(p)
    p.api.command = async (_id, body) => {
      p.calls.push(plain(body))
      return body.action === 'next_bottle' ? response.promise : { data: { result: { result: 'stopped' } } }
    }
    const first = p.state.nextBottle()
    assert.equal(p.state.currentBottle.value, null) // Pending motion cannot display the old bottle as settled.
    await p.state.nextBottle()
    assert.deepEqual(p.calls, [{ action: 'next_bottle', expected_position: 0, expected_bottle_token: 'reference-1' }])
    p.device.read_ok = false
    assert.equal(p.state.currentBottle.value, null)
    await p.state.send({ action: 'home_bottle' })
    await p.state.send({ action: 'stop' })
    response.resolve({ data: { result: { result: 'accepted' } } })
    await first
    p.device.read_ok = true
    p.device.bottle_ready = false
    assert.equal(p.state.currentBottle.value, null)
    await p.state.nextBottle()
    assert.deepEqual(p.calls.map(c => c.action), ['next_bottle', 'stop'])
  } finally { p.unmount() }
})

test('simple bottle card keeps stop and bottle controls outside collapsed advanced operations', async () => {
  const state = { ...device(), bottle_count: 12, pulses_per_bottle: 12000, bottle_ready: true,
    current_bottle: 12, next_bottle: 1, home_enabled: true, position_encoding_verified: true }
  const html = await renderCard(state)
  const advanced = html.indexOf('<details class="advanced-controls"')
  assert.ok(advanced > 0)
  assert.ok(html.indexOf('回原点') < advanced)
  assert.ok(html.indexOf('下一瓶') < advanced)
  assert.ok(html.indexOf('>停止<') < advanced)
  assert.ok(html.indexOf('绝对定位') > advanced)
  assert.ok(html.indexOf('控制器坐标') > advanced)
  assert.match(html, /<details class="advanced-controls"><summary>高级操作<\/summary>/)
  assert.match(html.slice(0, advanced), /12号瓶/)
  assert.match(html.slice(0, advanced), /title="下一瓶：1号瓶"/)
  assert.doesNotMatch(await renderCard({ ...state, read_ok: false }), /<strong>12号瓶<\/strong>/)
  assert.doesNotMatch(await renderCard({ ...state, bottle_ready: false }), /<strong>12号瓶<\/strong>/)
})

test('stale and busy states block new movement while connected stop remains available during pending requests', async () => {
  const p = card(), pendingRun = deferred<any>()
  try {
    p.api.command = async (_id, body) => {
      p.calls.push(plain(body))
      return body.action === 'run' ? pendingRun.promise : { data: { result: { result: 'stopped' } } }
    }
    const run = p.state.send({ action: 'run', direction: 'negative', speed: 400, duration_seconds: 10 })
    p.device.read_ok = false
    p.device.busy = true
    assert.equal(p.state.canMove.value, false)
    await p.state.send({ action: 'run', direction: 'positive', speed: 400, duration_seconds: 10 })
    await p.state.send({ action: 'stop' })
    assert.deepEqual(p.calls.map(c => c.action), ['run', 'stop'])
    assert.equal(p.state.pending.value, 1)
    pendingRun.resolve({ data: { result: { result: 'accepted' } } })
    await run
    assert.equal(p.state.pending.value, 0)
    p.unmount()
    assert.deepEqual(p.calls.map(c => c.action), ['run', 'stop'])
  } finally { p.dispose() }
})

test('uncertain motion and failed stopping block new movement until confirmed cleanup', async () => {
  const p = card()
  try {
    for (const result of ['unknown', 'stop_unconfirmed']) {
      p.device.action = { action: 'run', result }
      assert.equal(p.state.canMove.value, false)
      await p.state.send({ action: 'run', direction: 'positive', speed: 400, duration_seconds: 10 })
      assert.equal(p.calls.length, 0)
    }
    p.device.action = { action: 'run', result: 'failed' }
    p.device.motion_blocked = true
    assert.equal(p.state.canMove.value, false)
    await p.state.send({ action: 'run', direction: 'positive', speed: 400, duration_seconds: 10 })
    await p.state.send({ action: 'stop' })
    assert.deepEqual(p.calls.map(c => c.action), ['stop'])
    p.device.motion_blocked = false
    assert.equal(p.state.canMove.value, true)
    await p.state.send({ action: 'run', direction: 'positive', speed: 400, duration_seconds: 10 })
    assert.deepEqual(p.calls.map(c => c.action), ['stop', 'run'])
  } finally { p.unmount() }
})

test('stop feedback remains pending until response and readback, with failure exposed', async () => {
  const p = card(), response = deferred<any>(), readback = deferred<any>()
  try {
    p.api.command = async (_id, body) => { p.calls.push(plain(body)); return response.promise }
    p.api.read = async () => readback.promise
    const stopping = p.state.send({ action: 'stop' })
    assert.equal(p.state.stopping.value, 1)
    assert.equal(p.device.stop_confirmed, true) // Request state does not fabricate a device result.
    response.reject({ response: { data: { detail: '停止未确认' } } })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(p.state.stopping.value, 1)
    assert.ok(p.messages.some(message => message[0] === 'error' && message[1] === '停止未确认'))
    readback.resolve({ data: { ...p.device, stop_confirmed: false, motion_blocked: true } })
    await stopping
    assert.equal(p.state.stopping.value, 0)
    assert.equal(p.state.pending.value, 0)
    assert.deepEqual(p.calls.map(call => call.action), ['stop'])
  } finally { p.unmount() }
})

test('control reads expire at six seconds without altering monitor snapshots or writing on lifecycle events', async () => {
  const source = device(), data = vue.ref<any>(null), fresh = vue.ref(true)
  const timers = new Map<number, { callback: () => void; delay: number }>()
  let nextId = 0, listReads = 0
  const group = view('components/TurntableGroup.vue', {
    '../api/turntables': { turntableApi: { list: async () => { listReads++; return { data: { turntables: { turntable1: source } } } } } },
    '../composables/useWebSocket': { useWebSocket: () => ({ data, fresh }) },
  }, { setTimeout: (callback: () => void, delay: number) => { const id = ++nextId; timers.set(id, { callback, delay }); return id }, clearTimeout: (id: number) => timers.delete(id) })
  try {
    await group.mounted[0]!()
    assert.equal(listReads, 1)
    assert.equal(group.state.states.value.turntable1.read_ok, true)
    assert.ok(timers.values().next().value!.delay <= 6000)
    const [expiredId, expired] = timers.entries().next().value!
    timers.delete(expiredId)
    expired.callback()
    assert.equal(group.state.states.value.turntable1.read_ok, false)
    assert.equal(source.read_ok, true)
    group.state.update({ ...source, read_at: new Date(Date.now() - 7000).toISOString() })
    assert.equal(group.state.states.value.turntable1.read_ok, false)
    data.value = { turntables: { turntable1: { ...source, read_at: new Date().toISOString() } } }
    await vue.nextTick()
    assert.equal(group.state.states.value.turntable1.read_ok, true)
    fresh.value = false
    await vue.nextTick()
    assert.equal(group.state.states.value.turntable1.read_ok, false)
    assert.equal(data.value.turntables.turntable1.read_ok, true)
    group.unmount()
    assert.equal(timers.size, 0)
    assert.equal(listReads, 1)
  } finally { group.dispose() }
})

function orderedGroup() {
  const list = deferred<any>(), data = vue.ref<any>(null), fresh = vue.ref(true)
  const group = view('components/TurntableGroup.vue', {
    '../api/turntables': { turntableApi: { list: () => list.promise } },
    '../composables/useWebSocket': { useWebSocket: () => ({ data, fresh }) },
  })
  const mounting = group.mounted[0]!()
  return { ...group, list, data, mounting }
}
function orderedDevice(revision: number, overrides: Partial<TurntableState> = {}): TurntableState {
  return { ...device(), state_session: '2026-10-23T08:00:00.123455+00:00', state_revision: revision, ...overrides }
}

for (const status of [
  { action: { action: 'run', result: 'accepted' }, connected: true, connection_error: null },
  { action: { action: 'run', result: 'unknown', error: '读取失败，停止未确认' }, connected: true, connection_error: null },
  { action: null, connected: false, connection_error: 'Windows 无法配置 USB 串口' },
] satisfies Partial<TurntableState>[]) test(`late list and WebSocket snapshots cannot replace ${status.action?.result || 'connection failure'} with null read_at`, async () => {
  const group = orderedGroup()
  const newer = orderedDevice(2, { ...status, read_ok: false, read_at: null, busy: null, stop_confirmed: false, motion_blocked: true })
  const old = orderedDevice(1)
  try {
    group.state.update(newer) // REST result arrives before the initial registry request.
    group.list.resolve({ data: { turntables: { turntable1: old } } })
    await group.mounting
    group.data.value = { turntables: { turntable1: old } }
    await vue.nextTick()
    const shown = group.state.states.value.turntable1
    assert.equal(shown.state_revision, 2)
    assert.equal(shown.read_ok, false)
    assert.equal(shown.stop_confirmed, false)
    assert.equal(shown.connected, status.connected)
    assert.equal(shown.connection_error, status.connection_error)
    assert.deepEqual(plain(shown.action), status.action)
    const card = view('components/TurntableControl.vue', {
      '../api/turntables': { turntableApi: {}, turntableResult, turntableWorkState },
    }, {}, { state: shown })
    try { assert.equal(card.state.canMove.value, false) } finally { card.unmount() }
  } finally { group.unmount() }
})

test('same-read-time revisions stay ordered and local invalidation cannot be revived by duplicates', async () => {
  const group = orderedGroup(), first = orderedDevice(1)
  try {
    group.list.resolve({ data: { turntables: { turntable1: first } } })
    await group.mounting
    const newer = { ...first, state_revision: 2, position: 50 }
    group.state.update(newer)
    group.state.update(first)
    assert.equal(group.state.states.value.turntable1.position, 50)
    group.state.update({ ...newer, read_ok: false }) // Failed HTTP refresh.
    group.state.update(newer)
    assert.equal(group.state.states.value.turntable1.read_ok, false)
    group.state.update({ ...newer, state_revision: 3 })
    assert.equal(group.state.states.value.turntable1.read_ok, true)
  } finally { group.unmount() }
})

test('new backend session resets revision ordering and rejects late earlier sessions including microsecond differences', async () => {
  const group = orderedGroup(), first = orderedDevice(80)
  try {
    group.list.resolve({ data: { turntables: { turntable1: first } } })
    await group.mounting
    const restarted = orderedDevice(1, {
      state_session: '2026-10-23T08:00:00.123456+00:00', connected: false, read_at: null, read_ok: false,
    })
    group.state.update(restarted)
    group.data.value = { turntables: { turntable1: { ...first, state_revision: 100 } } }
    await vue.nextTick()
    const shown = group.state.states.value.turntable1
    assert.equal(shown.state_session, restarted.state_session)
    assert.equal(shown.state_revision, 1)
    assert.equal(shown.connected, false)
    assert.equal(shown.read_ok, false)
    group.state.update(device()) // A response without order metadata cannot roll back an upgraded server.
    assert.equal(group.state.states.value.turntable1.state_session, restarted.state_session)
  } finally { group.unmount() }
})

test('legacy statuses reject older read times until versioned snapshots become available', async () => {
  const group = orderedGroup(), current = device()
  try {
    group.list.resolve({ data: { turntables: { turntable1: current } } })
    await group.mounting
    group.state.update({ ...current, read_at: new Date(Date.now() - 1000).toISOString(), position: -25 })
    assert.equal(group.state.states.value.turntable1.position, 0)
    group.state.update(orderedDevice(1, { read_ok: false, read_at: null }))
    group.state.update(current)
    assert.equal(group.state.states.value.turntable1.state_revision, 1)
    assert.equal(group.state.states.value.turntable1.read_ok, false)
  } finally { group.unmount() }
})

for (const operation of ['connect', 'disconnect'] as const) test(`${operation} applies the returned snapshot before refresh and rejects older telemetry if refresh fails`, async () => {
  const group = orderedGroup(), readback = deferred<any>()
  const first = orderedDevice(1, { connected: operation === 'disconnect' })
  const response = orderedDevice(3, { connected: operation === 'connect', read_ok: operation === 'connect',
    read_at: operation === 'connect' ? new Date().toISOString() : null, stop_confirmed: false })
  const card = view('components/TurntableControl.vue', {
    vue: { ...vue, defineComponent: (component: any) => ({ ...component,
      setup: (props: any, context: any) => component.setup(props, { ...context,
        emit: (_name: string, state: TurntableState) => group.state.update(state) }) }) },
    '../api/turntables': { turntableApi: {
      [operation]: async () => ({ data: { success: true, ...response } }),
      read: () => readback.promise,
    }, turntableResult, turntableWorkState },
  }, {}, { get state() { return group.state.states.value.turntable1 || first } })
  try {
    group.list.resolve({ data: { turntables: { turntable1: first } } })
    await group.mounting
    const request = card.state[operation]()
    await new Promise(resolve => setImmediate(resolve))
    const revisionBeforeRefresh = group.state.states.value.turntable1.state_revision
    readback.reject(new Error('refresh failed'))
    await request
    group.data.value = { turntables: { turntable1: orderedDevice(2, { connected: true, stop_confirmed: true }) } }
    await vue.nextTick()
    const shown = group.state.states.value.turntable1
    assert.equal(revisionBeforeRefresh, 3)
    assert.equal(shown.state_revision, 3)
    assert.equal(shown.connected, operation === 'connect')
    assert.equal(shown.read_ok, false)
    assert.equal(shown.stop_confirmed, false)
  } finally { card.unmount(); group.unmount() }
})
