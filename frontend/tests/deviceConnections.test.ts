import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as connection from '../src/composables/connectionBatch'
import * as program from '../src/utils/microwaveProgram'
import * as calculations from '../src/utils/pumpCalculations'
import * as confirmations from '../src/composables/pendingConfirmation'
import { view } from './helpers/sfc'

const source = readFileSync(new URL('../src/views/ControlPanel.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'connection-test' }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

function page() {
  const calls: string[] = []
  const starts: any[][] = []
  const unmount: (() => void)[] = []
  const registry: any = {
    heaters: { heater2: {}, heater1: {} }, pumps: { pump1: {} }, microwaves: { microwave1: {} },
    syringe_pumps: { syringe_pump1: { configured: true, name: '泵 A' } }, valves: { valve1: {} },
  }
  for (const group of Object.values(registry) as any[]) for (const item of Object.values(group) as any[]) Object.assign(item, { connected: false, binding_resolved: true })
  const behavior: Record<string, () => Promise<any>> = {}
  async function request(operation: string, id = '') {
    const key = id ? `${operation}:${id}` : operation
    calls.push(key)
    if (behavior[key]) return { data: await behavior[key]() }
    if (operation === 'list') return { data: registry }
    if (operation === 'read') return { data: { connected: true, read_ok: true, device_id: id, pv: 30, material_temperature: 30, channels: Object.fromEntries([1, 2, 3, 4].map(ch => [ch, { read_ok: true }])) } }
    return { data: { success: true } }
  }
  const api: any = { list: () => request('list'), emergencyStop: () => request('emergencyStop') }
  api.startPump = (...args: any[]) => { starts.push(args); return request('start', 'pump1') }
  api.stopPump = () => request('stop', 'pump1')
  api.setTemperature = (id: string) => request('setTemperature', id)
  for (const kind of ['Heater', 'Pump', 'Microwave']) api[`connect${kind}`] = (id: string) => request('connect', id)
  api.readHeaterData = api.readPumpStatus = api.readMicrowaveData = (id: string) => request('read', id)
  api.valveOperation = (id: string, action: string) => request(action === 'status' ? 'read' : action, id)
  const imports: Record<string, any> = {
    vue: { ...vue, provide: () => {}, onMounted: () => {}, onUnmounted: (fn: () => void) => unmount.push(fn) },
    '../api/devices': { devicesApi: api, FLOW_UNITS: [], PUMP_MODES: [], TUBE_MODELS: [] },
    '../api/syringePumps': { syringeApi: { connect: (id: string) => request('connect', id), read: (id: string) => request('read', id) } },
    '../api/turntables': { turntableApi: { connect: (id: string) => request('connect', id), read: (id: string) => request('read', id) } },
    '../composables/connectionBatch': connection,
    '../composables/pendingConfirmation': confirmations,
    '../utils/microwaveProgram': program,
    '../utils/pumpCalculations': calculations,
    '../composables/useWebSocket': { useWebSocket: () => ({ data: vue.ref(null), connected: vue.ref(false), fresh: vue.ref(false) }) },
    'element-plus': { ElMessage: { error() {}, success() {}, info() {} }, ElMessageBox: { confirm: async () => { await behavior.confirm?.() } } },
  }
  const exports = {} as any
  runInNewContext(compiled, { exports, require: (name: string) => {
    if (name.endsWith('.vue')) return {}
    assert.ok(name in imports, name)
    return imports[name]
  }, localStorage: { getItem: () => null, setItem() {} }, clearInterval })
  const scope = vue.effectScope()
  const state = scope.run(() => exports.default.setup({}, { expose() {} }))
  state.syringeGroup.value = { update: (item: any) => { state.syringeDevices.value[item.device_id] = item } }
  // Real registry entries always include their ID in syringe status.
  registry.syringe_pumps.syringe_pump1.device_id = 'syringe_pump1'
  return { state, calls, starts, registry, behavior, unmount: () => unmount.forEach(fn => fn()), dispose: () => scope.stop() }
}

test('connects all five device types serially in stable order using only connection/read APIs', async () => {
  const p = page()
  try {
    await p.state.connectAll()
    assert.deepEqual(p.calls, ['list', ...['heater1', 'heater2', 'pump1', 'microwave1', 'syringe_pump1', 'valve1'].flatMap(id => [`connect:${id}`, `read:${id}`])])
    assert.equal(p.state.connectionBatch.results.value.length, 6)
    assert.ok(p.state.connectionBatch.results.value.every((r: any) => r.status === 'success'))
    assert.equal(p.state.syringeDevices.value.syringe_pump1.connected, true)
    assert.equal(p.state.valves.valve1.connected, true)
  } finally { p.dispose() }
})

test('registered turntable joins batch connect with status read and no movement', async () => {
  const p = page()
  try {
    p.registry.turntables = { turntable1: { device_id: 'turntable1', name: '接样转盘', configured: true, connected: false, binding_resolved: true } }
    p.state.turntableGroup.value = { update: (item: any) => { p.state.turntableDevices.value[item.device_id] = item } }
    await p.state.connectAll()
    assert.deepEqual(p.calls.filter(call => call.includes('turntable')), ['connect:turntable1', 'read:turntable1'])
    assert.equal(p.state.turntableDevices.value.turntable1.connected, true)
    assert.equal(p.state.connectionBatch.results.value.find((item: any) => item.key === 'turntable:turntable1').status, 'success')
    assert.equal(p.starts.length, 0)
  } finally { p.dispose() }
})

test('batch connection readback cannot bypass the turntable group ordering through its shared device map', async () => {
  const p = page()
  const old = { device_id: 'turntable1', name: '接样转盘', configured: true, connected: false,
    binding_resolved: true, read_ok: false, read_at: null, busy: null, stop_confirmed: false,
    state_session: '2026-10-23T08:00:00.123455+00:00', state_revision: 1 }
  for (const key of Object.keys(p.registry)) delete p.registry[key]
  p.registry.turntables = { turntable1: old }
  const group = view('components/TurntableGroup.vue', {
    '../api/turntables': { turntableApi: { list: async () => ({ data: { turntables: { turntable1: old } } }) } },
    '../composables/useWebSocket': { useWebSocket: () => ({ data: vue.ref(null), fresh: vue.ref(true) }) },
  })
  try {
    await group.mounted[0]!()
    p.state.turntableDevices.value = group.state.states.value // The real @devices binding shares this map.
    p.state.turntableGroup.value = { update: group.state.update }
    p.behavior['read:turntable1'] = async () => {
      group.state.update({ ...old, state_revision: 3, connected: true, read_ok: true,
        read_at: new Date().toISOString(), busy: true, action: { action: 'run', result: 'running' } })
      return { ...old, state_revision: 2, connected: true, read_ok: true,
        read_at: new Date().toISOString(), busy: false, stop_confirmed: true, action: null }
    }
    await p.state.connectAll()
    assert.equal(group.state.states.value.turntable1.state_revision, 3)
    assert.equal(p.state.turntableDevices.value.turntable1.state_revision, 3)
    assert.equal(p.state.turntableDevices.value.turntable1.action.result, 'running')
    assert.equal(p.state.turntableDevices.value.turntable1.stop_confirmed, false)
    assert.deepEqual(p.calls, ['list', 'connect:turntable1', 'read:turntable1'])
  } finally { group.unmount(); p.dispose() }
})

test('batch connection preserves full connect and failed readback revisions against late healthy telemetry', async () => {
  const p = page()
  const old = { device_id: 'turntable1', name: '接样转盘', configured: true, connected: false,
    binding_resolved: true, read_ok: false, read_at: null, busy: null, stop_confirmed: false,
    state_session: '2026-10-23T08:00:00.123455+00:00', state_revision: 1 }
  for (const key of Object.keys(p.registry)) delete p.registry[key]
  p.registry.turntables = { turntable1: old }
  const data = vue.ref<any>(null)
  const group = view('components/TurntableGroup.vue', {
    '../api/turntables': { turntableApi: { list: async () => ({ data: { turntables: { turntable1: old } } }) } },
    '../composables/useWebSocket': { useWebSocket: () => ({ data, fresh: vue.ref(true) }) },
  })
  try {
    await group.mounted[0]!()
    p.state.turntableDevices.value = group.state.states.value
    p.state.turntableGroup.value = { update: group.state.update }
    p.behavior['connect:turntable1'] = async () => ({ ...old, success: true, connected: true,
      state_revision: 3, read_ok: true, read_at: new Date().toISOString(), busy: false })
    let revisionBeforeRead = 0
    p.behavior['read:turntable1'] = async () => {
      revisionBeforeRead = group.state.states.value.turntable1.state_revision
      return { ...old, connected: true, state_revision: 5, read_error: '最新状态读取超时', motion_blocked: true }
    }
    await p.state.connectAll()
    data.value = { turntables: { turntable1: { ...old, state_revision: 4, connected: true,
      read_ok: true, read_at: new Date().toISOString(), busy: false, stop_confirmed: true } } }
    await vue.nextTick()
    assert.equal(group.state.states.value.turntable1.state_revision, 5)
    assert.equal(revisionBeforeRead, 3)
    assert.equal(group.state.states.value.turntable1.read_ok, false)
    assert.equal(group.state.states.value.turntable1.stop_confirmed, false)
    assert.equal(group.state.states.value.turntable1.read_error, '最新状态读取超时')
    assert.equal(p.state.connectionBatch.results.value[0].status, 'unknown')
  } finally { group.unmount(); p.dispose() }
})

test('skips connected, unconfigured and unmatched devices; false and network failures remain failures', async () => {
  const p = page()
  try {
    p.registry.heaters.heater1.connected = true
    p.registry.heaters.heater2.binding_resolved = false
    p.registry.syringe_pumps.syringe_pump1.configured = false
    p.behavior['connect:pump1'] = async () => ({ success: false })
    p.behavior['connect:microwave1'] = async () => { throw new Error('offline') }
    await p.state.connectAll()
    assert.deepEqual(p.calls, ['list', 'connect:pump1', 'connect:microwave1', 'connect:valve1', 'read:valve1'])
    assert.equal(p.state.connectionBatch.results.value.filter((r: any) => r.status === 'failed').length, 2)
    assert.equal(p.state.devices.pumps.pump1.connected, false)
  } finally { p.dispose() }
})

test('failed status read preserves connection and reports unknown, including false read_ok', async () => {
  const p = page()
  try {
    p.behavior['read:heater1'] = async () => { throw new Error('timeout') }
    p.behavior['read:syringe_pump1'] = async () => ({ connected: true, read_ok: false })
    p.behavior['read:pump1'] = async () => ({ channels: {} })
    await p.state.connectAll()
    assert.equal(p.state.devices.heaters.heater1.connected, true)
    assert.equal(p.state.syringeDevices.value.syringe_pump1.read_ok, false)
    assert.equal(p.state.connectionBatch.results.value.filter((r: any) => r.status === 'unknown').length, 3)
    assert.match(p.state.connectionBatch.results.value[0].detail, /已连接，状态未知/)
  } finally { p.dispose() }
})

test('409 stops the remaining connection requests', async () => {
  const p = page()
  try {
    p.behavior['connect:heater1'] = async () => { throw { response: { status: 409, data: { detail: '实验占用' } } } }
    await p.state.connectAll()
    assert.deepEqual(p.calls, ['list', 'connect:heater1'])
    assert.match(p.state.connectionBatch.message.value, /停止后续/)
  } finally { p.dispose() }
})

test('invalid read payloads never become confirmed status; a retry only connects remaining devices', async () => {
  const p = page()
  try {
    p.behavior['read:microwave1'] = async () => ({ material_temperature: null })
    p.behavior['read:valve1'] = async () => ({ connected: true })
    await p.state.connectAll()
    assert.equal(p.state.microwaveSnapshots.microwave1.error, 'read_failed')
    assert.equal(p.state.valves.valve1.read_ok, false)
    p.calls.length = 0
    for (const group of Object.values(p.registry) as any[]) for (const state of Object.values(group) as any[]) state.connected = true
    p.registry.heaters.heater2.connected = false
    await p.state.connectAll()
    assert.deepEqual(p.calls, ['list', 'connect:heater2', 'read:heater2'])
    assert.equal(p.state.connectionBatch.results.value.filter((r: any) => r.status === 'skipped').length, 5)
  } finally { p.dispose() }
})

for (const action of ['leave', 'emergency'] as const) test(`${action} cancels pending connections and duplicate clicks do not enqueue another batch`, async () => {
  const p = page()
  let resolve!: () => void
  try {
    p.behavior['connect:heater1'] = async () => { await new Promise<void>(r => { resolve = r }); return { success: true } }
    const run = p.state.connectAll()
    while (!resolve) await Promise.resolve()
    await p.state.connectAll()
    if (action === 'leave') p.unmount()
    else await p.state.emergencyStop()
    resolve()
    await run
    assert.deepEqual(p.calls.filter(c => c.startsWith('connect:')), ['connect:heater1'])
    assert.equal(p.state.connectionBatch.running.value, false)
    assert.match(p.state.connectionBatch.message.value, /取消/)
  } finally { p.dispose() }
})

test('an ongoing individual device operation blocks the bulk action', async () => {
  const p = page()
  try {
    const token = Symbol()
    p.state.connectionBatch.pending.add(token)
    await p.state.connectAll()
    assert.deepEqual(p.calls, [])
    p.state.connectionBatch.pending.delete(token)
    await p.state.connectAll()
    assert.equal(p.state.connectionBatch.results.value.length, 6)
  } finally { p.dispose() }
})

test('a pending pump confirmation blocks duplicate starts and sends the confirmed parameter snapshot', async () => {
  const p = page()
  try {
    p.registry.pumps.pump1.connected = true
    await p.state.refreshDevices()
    const ch = p.state.devices.pumps.pump1.channels[1]
    Object.assign(ch, { flowRate: 15, mode: 'TIME_SPEED', runTime: 5, timeUnit: 1 })
    const confirmations: (() => void)[] = []
    p.behavior.confirm = () => new Promise<void>(resolve => confirmations.push(resolve))
    const first = p.state.startPumpChannel('pump1', 1)
    const second = p.state.startPumpChannel('pump1', 1)
    ch.runTime = 50
    ch.flowUnit = 3
    confirmations.forEach(resolve => resolve())
    await Promise.all([first, second])
    assert.equal(confirmations.length, 1)
    assert.equal(p.starts.length, 1)
    assert.equal(p.starts[0][5], 5)
    assert.equal(p.starts[0][8], 1)
  } finally { p.dispose() }
})

test('heater setpoint follows backend bounds and rejects unknown or out-of-range values', async () => {
  const p = page()
  try {
    Object.assign(p.registry.heaters.heater1, { connected: true, min_temperature: 10, max_temperature: 70 })
    await p.state.refreshDevices()
    assert.equal(p.state.devices.heaters.heater1.maxTemperature, 70)
    await p.state.setTemp('heater1', 71)
    await p.state.setTemp('heater1', 9)
    assert.ok(!p.calls.includes('setTemperature:heater1'))
    await p.state.setTemp('heater1', 70)
    assert.equal(p.calls.filter(call => call === 'setTemperature:heater1').length, 1)
    p.state.devices.heaters.heater1.maxTemperature = undefined
    await p.state.setTemp('heater1', 50)
    assert.equal(p.calls.filter(call => call === 'setTemperature:heater1').length, 1)
  } finally { p.dispose() }
})

for (const action of ['stop', 'stopAll', 'leave'] as const) test(`${action} while a pump confirmation is open cancels that unissued start`, async () => {
  const p = page()
  try {
    p.registry.pumps.pump1.connected = true
    await p.state.refreshDevices()
    let confirm!: () => void
    p.behavior.confirm = () => new Promise<void>(resolve => { confirm = resolve })
    const pending = p.state.startPumpChannel('pump1', 1)
    p.behavior.confirm = async () => {}
    if (action === 'stop') await p.state.stopPumpChannel('pump1', 1)
    if (action === 'stopAll') await p.state.stopPumpAll('pump1')
    if (action === 'leave') p.unmount()
    confirm()
    await pending
    assert.equal(p.starts.length, 0)
    assert.equal(p.state.devices.pumps.pump1.channels[1].starting, false)
  } finally { p.dispose() }
})
