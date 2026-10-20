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

function websocket() {
  const mounts: (() => void)[] = [], unmounts: (() => void)[] = []
  const timers = new Map<number, { run: () => void; ms: number }>()
  const sockets: any[] = []
  let sequence = 0
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
  runInNewContext(code, { exports, require: () => ({ ...vue,
    onMounted: (fn: () => void) => mounts.push(fn), onUnmounted: (fn: () => void) => unmounts.push(fn) }),
    WebSocket: Socket, location: { protocol: 'http:', host: 'localhost' }, console: { error() {} },
    setTimeout: (run: () => void, ms: number) => { timers.set(++sequence, { run, ms }); return sequence },
    clearTimeout: (id: number) => timers.delete(id),
  })
  const state = exports.useWebSocket()
  mounts.forEach(fn => fn())
  const emit = (socket = sockets.at(-1)) => socket.onmessage({ data: JSON.stringify({ type: 'realtime', pumps: {
    pump1: { channels: { '1': { running: true, read_ok: true, run_status: 'START', flow_rate: 15 } } },
  } }) })
  const expire = (ms: number) => {
    const entry = [...timers].find(([, timer]) => timer.ms === ms)
    assert.ok(entry, `Missing ${ms}ms timer`)
    timers.delete(entry[0]); entry[1].run()
  }
  return { state, sockets, emit, expire, unmount: () => unmounts.forEach(fn => fn()), timers }
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
  return html.slice(html.indexOf('class="channel-header"'), html.indexOf('class="channel-row"')).replace(/<[^>]+>/g, '')
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
