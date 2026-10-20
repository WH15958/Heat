import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createSSRApp, h } from 'vue'
import * as vue from 'vue'
import { renderToString } from '@vue/server-renderer'
import * as calculations from '../src/utils/pumpCalculations'
import * as history from '../src/utils/monitorHistory'

function websocket() {
  const mounts: (() => void)[] = [], unmounts: (() => void)[] = []
  const timers = new Map<number, { run: () => void; ms: number }>()
  const sockets: any[] = []
  let sequence = 0
  let now = 100000
  class TestDate extends Date { static now() { return now } }
  class Socket {
    static CLOSED = 3
    readyState = 0
    onopen: any; onclose: any; onmessage: any; onerror: any
    constructor() { sockets.push(this) }
    close() { this.readyState = 3; this.onclose?.() }
  }
  const source = readFileSync(new URL('../src/composables/useWebSocket.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports: any = {}
  runInNewContext(code, { exports, require: (name: string) => name === '../utils/monitorHistory' ? history : ({ ...vue,
    onMounted: (fn: () => void) => mounts.push(fn), onUnmounted: (fn: () => void) => unmounts.push(fn) }),
    WebSocket: Socket, Date: TestDate, location: { protocol: 'http:', host: 'localhost' }, console: { error() {} },
    setTimeout: (run: () => void, ms: number) => { timers.set(++sequence, { run, ms }); return sequence },
    clearTimeout: (id: number) => timers.delete(id),
  })
  const state = exports.useWebSocket()
  mounts.forEach(fn => fn())
  const emit = (socket = sockets.at(-1)) => socket.onmessage({ data: JSON.stringify({ type: 'realtime', pumps: {
    pump1: { channels: { '1': { running: true, read_ok: true, run_status: 'START', flow_rate: 15, flow_unit: 'ML_MIN' } } },
  } }) })
  const send = (data: any) => sockets.at(-1).onmessage({ data: JSON.stringify(data) })
  const expire = (ms: number) => {
    const entry = [...timers].find(([, timer]) => timer.ms === ms)
    assert.ok(entry, `Missing ${ms}ms timer`)
    timers.delete(entry[0]); entry[1].run()
  }
  return { state, sockets, emit, send, expire, setNow: (at: number) => { now = at }, unmount: () => unmounts.splice(0).forEach(fn => fn()), timers,
    remount: () => { const next = exports.useWebSocket(); mounts.at(-1)!(); return next } }
}

test('closed transport invalidates data; reopening cannot revive an old pump reading', () => {
  const rig = websocket()
  rig.sockets[0].onopen(); rig.emit()
  assert.equal(rig.state.data.value.pumps.pump1.channels['1'].running, true)
  rig.sockets[0].close()
  assert.equal(rig.state.data.value, null)
  rig.expire(3000)
  rig.sockets[1].onopen()
  assert.equal(rig.state.data.value, null)
  rig.emit()
  assert.equal(rig.state.data.value.pumps.pump1.channels['1'].running, true)
  rig.unmount()
})

test('an open but silent socket expires its telemetry without sending hardware commands', () => {
  const rig = websocket()
  rig.sockets[0].onopen(); rig.emit()
  assert.equal(rig.state.fresh?.value, true)
  rig.expire(6000)
  assert.equal(rig.state.connected.value, true)
  assert.equal(rig.state.fresh.value, false)
  assert.equal(rig.state.data.value, null)
  rig.emit()
  assert.equal(rig.state.fresh.value, true)
  rig.unmount()
  assert.equal(rig.timers.size, 0)
})

test('late messages after unmount cannot repopulate the next page with stale data', () => {
  const rig = websocket()
  const late = rig.sockets[0].onmessage
  rig.unmount()
  late({ data: JSON.stringify({ type: 'realtime', pumps: { old: {} } }) })
  assert.equal(rig.state.data.value, null)
})

async function renderPump(status: any) {
  const source = readFileSync(new URL('../src/components/PumpControl.vue', import.meta.url), 'utf8')
  const script = compileScript(parse(source).descriptor, { id: 'pump-acceptance', inlineTemplate: true }).content
  const code = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports: any = {}
  const imports: Record<string, any> = { vue, '../api/devices': { FLOW_UNITS: [], PUMP_MODES: [], TUBE_MODELS: [] },
    '../utils/pumpCalculations': calculations }
  runInNewContext(code, { exports, require: (name: string) => imports[name] ?? { default: {} } })
  const channel = { mode: 'FLOW_MODE', tubeModel: 11, flowRate: 15, flowUnit: 1,
    maxFlowRate: 18.75, tubeSegmentLengthsCm: [null], direction: 'CW' }
  const app = createSSRApp(exports.default, { pumpId: 'pump1', pump: {
    connected: true, channels: Object.fromEntries([1, 2, 3, 4].map(ch => [ch, { ...channel }])) }, channelStatus: () => status })
  app.config.warnHandler = () => {}
  for (const name of ['ElCard', 'ElTag', 'ElAlert', 'ElSelect', 'ElOption', 'ElInputNumber', 'ElButton', 'ElRadioGroup', 'ElRadioButton', 'ElDivider']) {
    app.component(name, { setup: (_, { slots }) => () => h('div', {}, [slots.header?.(), slots.default?.()]) })
  }
  const html = await renderToString(app)
  const headerStart = html.indexOf('class="channel-header"')
  const fieldsStart = html.indexOf('class="channel-fields"', headerStart)
  assert.ok(headerStart >= 0 && fieldsStart > headerStart, 'pump channel header and fields must render')
  return html.slice(headerStart, fieldsStart).replace(/<[^>]+>/g, '')
}

test('actual pump card renders PAUSE as paused, not stopped', async () => {
  const html = await renderPump({ read_ok: true, running: false, run_status: 'PAUSE' })
  assert.match(html, /暂停/)
  assert.doesNotMatch(html, /停止/)
})

test('actual pump card does not interpret a missing/unknown run status as STOP', async () => {
  const html = await renderPump({ read_ok: true, running: null, run_status: 'UNKNOWN' })
  assert.match(html, /状态未知/)
})


test('monitor survives a 6–7s sweep while control data still expires at 6s', () => {
  const rig = websocket()
  rig.sockets[0].onopen(); rig.emit()
  const sample = rig.state.monitorData.value
  rig.expire(6000)
  assert.equal(rig.state.fresh.value, false)
  assert.equal(rig.state.data.value, null)
  assert.equal(rig.state.monitorFresh.value, true)
  assert.equal(rig.state.monitorData.value, sample)
  rig.emit() // Next full-device sweep, after the control freshness deadline.
  assert.equal(rig.state.monitorFresh.value, true)
  rig.expire(15000)
  assert.equal(rig.state.connected.value, true)
  assert.equal(rig.state.monitorFresh.value, false)
  assert.equal(rig.state.monitorData.value, null)
  rig.emit()
  rig.sockets[0].close()
  assert.equal(rig.state.monitorData.value, null)
  assert.equal(rig.state.monitorFresh.value, false)
  rig.expire(3000)
  rig.sockets[1].onopen()
  assert.equal(rig.state.monitorData.value, null)
  rig.unmount()
  assert.equal(rig.timers.size, 0)
})

test('initial connection waits for telemetry and distinguishes silence from transport loss', () => {
  const rig = websocket()
  assert.equal(rig.state.monitorState.value, 'connecting')
  rig.sockets[0].onopen()
  assert.equal(rig.state.monitorState.value, 'waiting')
  rig.emit()
  assert.equal(rig.state.monitorState.value, 'live')
  rig.expire(15000)
  assert.equal(rig.state.monitorState.value, 'stale')
  rig.sockets[0].close()
  assert.equal(rig.state.monitorState.value, 'disconnected')
  rig.unmount()
})

test('reentering a page retains samples without reviving stale current readings or accepting late messages', () => {
  const rig = websocket()
  rig.sockets[0].onopen(); rig.emit()
  const samples = rig.state.monitorHistory.pumps.pump1.channels['1']
  assert.equal(samples.length, 1)
  const receivedAt = rig.state.monitorHistory.lastReceivedAt
  const late = rig.sockets[0].onmessage
  rig.unmount()
  const next = rig.remount()
  assert.equal(next.monitorHistory.pumps.pump1.channels['1'], samples)
  assert.equal(next.monitorHistory.lastReceivedAt, receivedAt)
  assert.equal(next.monitorData.value, null)
  assert.equal(next.monitorFresh.value, false)
  rig.sockets[1].onopen()
  assert.equal(next.monitorState.value, 'waiting')
  late({ data: JSON.stringify({ type: 'realtime', heaters: { fake: { pv: 999, sv: 999 } } }) })
  assert.equal(next.monitorHistory.heaters.fake, undefined)
  rig.setNow(101000)
  rig.emit()
  assert.equal(next.monitorState.value, 'live')
  assert.deepEqual(Array.from(samples, (point: any) => point[1]), [15, null, 15])
  rig.unmount()
  assert.equal(rig.timers.size, 0)
})

test('server history restores a chart before the next sweep without enabling current controls', () => {
  const rig = websocket()
  rig.sockets[0].onopen()
  rig.send({ type: 'monitor_history', frames: [
    { sampled_at_ms: 80000, heaters: { heater1: { pv: 20, sv: 50 } } },
    { sampled_at_ms: 90000, heaters: { heater1: { pv: 25, sv: 50 } } },
  ] })
  assert.deepEqual(Array.from(rig.state.monitorHistory.heaters.heater1.pv, (point: any) => Array.from(point)), [[80000, 20], [90000, 25]])
  assert.equal(rig.state.connected.value, true)
  assert.equal(rig.state.data.value, null)
  assert.equal(rig.state.monitorData.value, null)
  assert.equal(rig.state.fresh.value, false)
  assert.equal(rig.state.monitorState.value, 'waiting')
  rig.unmount()
})

test('replayed snapshots use their original age for both freshness deadlines', () => {
  const rig = websocket()
  rig.sockets[0].onopen()
  rig.send({ type: 'realtime', snapshot: true, sampled_at_ms: 95000, heaters: { heater1: { pv: 25, sv: 50 } } })
  assert.equal(rig.state.fresh.value, true)
  assert.equal(rig.state.monitorFresh.value, true)
  rig.expire(1000) // Only the remaining 1s of the 6s control budget.
  assert.equal(rig.state.data.value, null)
  assert.equal(rig.state.monitorFresh.value, true)
  rig.expire(10000)
  assert.equal(rig.state.monitorData.value, null)
  rig.unmount()
})

test('an expired snapshot only fills history; an older late snapshot cannot replace newer live data', () => {
  const rig = websocket()
  rig.sockets[0].onopen()
  rig.send({ type: 'realtime', snapshot: true, sampled_at_ms: 80000, heaters: { heater1: { pv: 20, sv: 50 } } })
  assert.equal(rig.state.monitorState.value, 'stale')
  assert.equal(rig.state.data.value, null)
  assert.equal(rig.state.monitorData.value, null)
  rig.send({ type: 'realtime', sampled_at_ms: 100000, heaters: { heater1: { pv: 30, sv: 50 } } })
  rig.send({ type: 'realtime', snapshot: true, sampled_at_ms: 90000, heaters: { heater1: { pv: 25, sv: 50 } } })
  assert.equal(rig.state.data.value.heaters.heater1.pv, 30)
  assert.equal(rig.state.monitorData.value.heaters.heater1.pv, 30)
  assert.equal(rig.state.monitorHistory.lastReceivedAt, 100000)
  assert.equal(rig.state.monitorState.value, 'live')
  rig.unmount()
})

test('history and snapshot share one tail sample after refresh or reconnect', () => {
  const rig = websocket()
  rig.sockets[0].onopen()
  const sample = { type: 'realtime', sampled_at_ms: 100000, heaters: { heater1: { pv: 30, sv: 50 } } }
  rig.send({ type: 'monitor_history', frames: [sample] })
  rig.send({ ...sample, snapshot: true })
  assert.equal(rig.state.monitorHistory.heaters.heater1.pv.length, 1)
  assert.equal(rig.state.fresh.value, true)
  rig.unmount()
})
