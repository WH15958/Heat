import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { webcrypto } from 'node:crypto'
import * as program from '../src/utils/microwaveProgram'

// Execute the real page handlers with Vue reactivity and fake transport/dialogs.
// No server, serial connection, or hardware is used.
const source = readFileSync(new URL('../src/views/ControlPanel.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'microwave-control-test' }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

function page() {
  const calls: any[][] = [], dialogs: string[] = [], errors: string[] = []
  const stopped = { status_confirmed: true, stop_confirmed: true, control_active: false,
    output_active: false, fault_code: 0, power_percent: 0, current: 0 }
  const api = {
    previewMicrowaveProgram: async (...args: any[]) => { calls.push(['preview', ...args]); return { data: { success: true } } },
    startMicrowaveProgram: async (...args: any[]) => { calls.push(['start', ...args]); return { data: { state: 'running' } } },
    readMicrowaveData: async () => ({ data: stopped }),
  }
  let confirm = async () => {}
  const exports = {} as any
  const scope = vue.effectScope()
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted: () => {}, onUnmounted: () => {} },
    '../api/devices': { devicesApi: api, FLOW_UNITS: [], PUMP_MODES: [], TUBE_MODELS: [] },
    '../utils/microwaveProgram': program,
    '../utils/pumpCalculations': {},
    '../composables/useWebSocket': { useWebSocket: () => ({ data: vue.ref(null), connected: vue.ref(false) }) },
    'element-plus': {
      ElMessage: { error: (m: string) => errors.push(m), success: () => {}, info: () => {} },
      ElMessageBox: { confirm: async (message: string) => { dialogs.push(message); await confirm() } },
    },
  }
  runInNewContext(compiled, { exports, require: (name: string) => {
    if (name.endsWith('.vue')) return {}
    if (!(name in imports)) throw new Error('Unexpected dependency: ' + name)
    return imports[name]
  }, crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
    localStorage: { getItem: () => null, setItem: () => {} } })
  const state = scope.run(() => exports.default.setup({}, { expose: () => {} }))
  state.applyDeviceData({ microwaves: { microwave1: { connected: true, connection_port: 'FAKE', binding_resolved: true } } })
  const microwave = state.devices.microwaves.microwave1
  assert.equal(microwave.usedSegments, 1)
  microwave.mode = 'auto_power'
  microwave.usedSegments = 2
  state.microwaveSnapshots.microwave1 = stopped
  return { state, microwave, calls, dialogs, errors, api, stopped,
    confirmation: (fn: () => Promise<void>) => { confirm = fn }, dispose: () => scope.stop() }
}

test('preview checks logical stages without motion; cancellation sends no start; host starts once', async () => {
  const p = page()
  try {
    await p.state.startMicrowave('microwave1')
    assert.equal(p.calls.length, 0)
    await p.state.configureMicrowave('microwave1')
    assert.deepEqual(p.calls[0]!.slice(0, 2), ['preview', 'microwave1'])
    assert.equal(p.calls[0]![2].mode, 'auto_power')
    assert.equal(p.calls[0]![2].stages.length, 2)
    assert.equal(p.calls[0]![2].hardware_confirmed, false)
    assert.equal(program.microwaveProgramConfigured(p.microwave), true)
    p.confirmation(async () => { throw 'cancel' })
    await p.state.startMicrowave('microwave1')
    assert.equal(p.calls.length, 1)
    assert.match(p.dialogs.at(-1)!, /无需在触摸屏设置执行范围/)
    p.confirmation(async () => {})
    await p.state.startMicrowave('microwave1')
    assert.equal(p.calls.filter(c => c[0] === 'start').length, 1)
    assert.equal(p.calls.at(-1)![2].request_id, p.calls[0]![2].request_id)
    assert.equal(p.calls.at(-1)![2].hardware_confirmed, true)
    assert.equal(program.microwaveProgramConfigured(p.microwave), false)
    await p.state.startMicrowave('microwave1')
    assert.equal(p.calls.filter(c => c[0] === 'start').length, 1)
  } finally { p.dispose() }
})

test('failed preview and invalid later stage never permit start', async () => {
  const p = page()
  try {
    await p.state.configureMicrowave('microwave1')
    p.api.previewMicrowaveProgram = async () => ({ data: { success: false } })
    await p.state.configureMicrowave('microwave1')
    assert.equal(program.microwaveProgramConfigured(p.microwave), false)
    await p.state.startMicrowave('microwave1')
    assert.equal(p.calls.filter(c => c[0] === 'start').length, 0)
    p.microwave.segments[2].minutes = 60
    const dialogs = p.dialogs.length
    await p.state.configureMicrowave('microwave1')
    assert.equal(p.dialogs.length, dialogs)
    assert.match(p.errors.at(-1)!, /第 2 段/)
  } finally { p.dispose() }
})

test('unused segment changes preserve configuration; used parameters, range and connection changes revoke it', async () => {
  const p = page()
  try {
    await p.state.configureMicrowave('microwave1')
    p.microwave.segments[5].temperature++
    assert.equal(program.microwaveProgramConfigured(p.microwave), true)
    p.microwave.segments[2].temperature++
    p.microwave.segments[2].temperature--
    assert.equal(p.microwave.configuredProgramKey, '')
    await p.state.configureMicrowave('microwave1')
    p.microwave.usedSegments = 1
    assert.equal(p.microwave.configuredProgramKey, '')
    await p.state.configureMicrowave('microwave1')
    p.microwave.connected = false
    p.microwave.connected = true
    assert.equal(p.microwave.configuredProgramKey, '')
  } finally { p.dispose() }
})

test('late configuration response cannot restore eligibility after disconnect and reconnect', async () => {
  const p = page()
  try {
    let finish!: (value: any) => void
    let entered!: () => void
    const requestEntered = new Promise<void>(resolve => { entered = resolve })
    p.api.previewMicrowaveProgram = async () => new Promise(resolve => { finish = resolve; entered() })
    const configuring = p.state.configureMicrowave('microwave1')
    await requestEntered
    p.microwave.connected = false
    p.microwave.connected = true
    finish({ data: { success: true } })
    await configuring
    assert.equal(p.microwave.configuredProgramKey, '')
    assert.match(p.errors.at(-1)!, /参数已变化/)
  } finally { p.dispose() }
})

test('double click is suppressed and uncertain network start retries the same request ID', async () => {
  const p = page()
  try {
    await p.state.configureMicrowave('microwave1')
    const requestId = p.microwave.programRequestId
    let release!: () => void
    let entered!: () => void
    const confirming = new Promise<void>(resolve => { entered = resolve })
    p.confirmation(async () => { entered(); await new Promise<void>(resolve => { release = resolve }) })
    const start = p.state.startMicrowave('microwave1')
    await confirming
    await p.state.startMicrowave('microwave1')
    assert.equal(p.calls.filter(c => c[0] === 'start').length, 0)
    const received: string[] = []
    p.api.startMicrowaveProgram = async (_id: string, body: any) => {
      received.push(body.request_id)
      if (received.length === 1) throw new Error('response lost')
      return { data: { state: 'running' } }
    }
    release()
    await start
    assert.equal(p.microwave.programRequestId, requestId)
    p.confirmation(async () => {})
    await p.state.startMicrowave('microwave1')
    assert.deepEqual(received, [requestId, requestId])
  } finally { p.dispose() }
})
