import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseDocument } from 'yaml'
import { moduleFromSource, plain, view, vue } from './helpers/sfc'
import * as devices from '../src/api/devices'
import * as document from '../src/experiment/document'

const catalog = moduleFromSource('experiment/catalog.ts', { '../api/devices': devices })
const types = ['turntable.home_bottle', 'turntable.next_bottle', 'turntable.stop']

test('turntable catalog offers exactly three device-only blocks with the existing device group', () => {
  assert.equal(catalog.groups.find((g: any) => g.key === 'turntable').devices, 'turntables')
  assert.deepEqual(plain(catalog.actions.filter((a: any) => a.group === 'turntable').map((a: any) => a.type)), types)
  for (const type of types) assert.deepEqual(plain(catalog.parameterFields({ type }).map((f: any) => f.key)), ['device_id'])
})

test('editor adds, validates and saves turntable blocks without controlling devices', async () => {
  const writes: any[] = []
  const p = view('views/ExperimentEditor.vue', {
    '../api/devices': { devicesApi: { list: async () => ({ data: {} }) } },
    '../api/experimentEditor': { editorApi: {
      validate: async () => ({ data: { valid: true, errors: [], warnings: [] } }),
      save: async (...args: any[]) => { writes.push(args); return { data: { revision: 'r1' } } },
    } },
    '../experiment/catalog': catalog, '../experiment/document': document,
  })
  try {
    const s = p.state
    s.registry.value = { turntables: { turntable1: { bottle_count: 12, connected: false } } }
    s.devicesLoaded.value = true
    assert.equal(s.devicesFor('turntable')[0].value, 'turntable1')
    for (let i = 0; i < types.length; i++) {
      s.add(types[i]); await vue.nextTick()
      s.set(['steps', i, 'params', 'device_id'], 'turntable1'); await vue.nextTick()
    }
    assert.deepEqual(plain(s.steps.value.map((step: any) => step.type)), types)
    assert.deepEqual(plain(s.localErrors.value), [])
    const original = s.source.value
    s.mode.value = 'yaml'; s.mode.value = 'graph'
    assert.equal(s.source.value, original)
    await s.save('bottles.yaml')
    assert.equal(writes.length, 1)
    assert.deepEqual(parseDocument(writes[0][1]).toJS().steps.map((step: any) => step.type), types)

    for (const [path, value, error] of [
      [['steps', 0, 'enabled'], false, /本次配方中回原点/],
      [['steps', 1, 'params', 'speed'], 4000, /只接受设备参数/],
      [['steps', 1, 'wait'], { type: 'duration', seconds: 1 }, /不附加等待/],
      [['steps', 1, 'on_error'], 'skip', /失败停止/],
    ] as const) {
      s.changeSource(original); await vue.nextTick()
      s.set([...path], value); await vue.nextTick()
      assert.match(s.localErrors.value.join(' '), error)
    }
    s.changeSource(original); await vue.nextTick()
    s.add('turntable.next_bottle'); await vue.nextTick()
    s.set(['steps', 3, 'params', 'device_id'], 'turntable1'); await vue.nextTick()
    assert.match(s.localErrors.value.join(' '), /本次配方中回原点/)
    assert.equal(writes.length, 1)
  } finally { p.dispose() }
})

test('REST and WebSocket progress retain bottle observations and never send controls', async () => {
  const activity = { devices: { turntable1: { read_ok: true, bottle_ready: true, current_bottle: 2, target_bottle: 2, stop_confirmed: true } } }
  const snapshot = { state: 'running', step_id: 'next', current_step: 1, total_steps: 3, activity }
  const p = view('views/ExperimentPage.vue', { axios: { get: async () => ({ data: snapshot }) } })
  try {
    p.state.selectedFilename.value = 'bottles.yaml'
    await p.state.pollProgress()
    assert.deepEqual(plain(p.state.progress.value.activity), activity)
    assert.equal(p.state.turntableProgress.value[0].state.current_bottle, 2)
    p.state.handleWsMessage({ data: JSON.stringify({ type: 'experiment_progress', filename: 'bottles.yaml', ...snapshot,
      activity: { devices: { turntable1: { read_ok: false, bottle_ready: false, current_bottle: null, stop_confirmed: false } } },
    }) })
    assert.equal(p.state.turntableProgress.value[0].state.bottle_ready, false)
    const next = p.state.normalizeProgress({ state: 'running', step_id: 'next', activity: null })
    assert.equal(next.activity, null)
  } finally { p.unmount() }
})
