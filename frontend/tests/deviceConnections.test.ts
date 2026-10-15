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

const source = readFileSync(new URL('../src/views/ControlPanel.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'connection-test' }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

function page() {
  const calls: string[] = []
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
  for (const kind of ['Heater', 'Pump', 'Microwave']) api[`connect${kind}`] = (id: string) => request('connect', id)
  api.readHeaterData = api.readPumpStatus = api.readMicrowaveData = (id: string) => request('read', id)
  api.valveOperation = (id: string, action: string) => request(action === 'status' ? 'read' : action, id)
  const imports: Record<string, any> = {
    vue: { ...vue, provide: () => {}, onMounted: () => {}, onUnmounted: (fn: () => void) => unmount.push(fn) },
    '../api/devices': { devicesApi: api, FLOW_UNITS: [], PUMP_MODES: [], TUBE_MODELS: [] },
    '../api/syringePumps': { syringeApi: { connect: (id: string) => request('connect', id), read: (id: string) => request('read', id) } },
    '../composables/connectionBatch': connection,
    '../utils/microwaveProgram': program,
    '../utils/pumpCalculations': calculations,
    '../composables/useWebSocket': { useWebSocket: () => ({ data: vue.ref(null), connected: vue.ref(false) }) },
    'element-plus': { ElMessage: { error() {}, success() {} }, ElMessageBox: { confirm: async () => {} } },
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
  return { state, calls, registry, behavior, unmount: () => unmount.forEach(fn => fn()), dispose: () => scope.stop() }
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
