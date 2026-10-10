import assert from 'node:assert/strict'
import { test } from 'node:test'
import { hostedMicrowavePayload, microwaveProgramPayload, microwaveProgramKey, microwaveProgramConfigured, type MicrowaveProgram } from '../src/utils/microwaveProgram'

function program(count = 2): MicrowaveProgram {
  return {
    mode: 'auto_power', usedSegments: count, configuredProgramKey: '',
    segments: Object.fromEntries(Array.from({ length: 5 }, (_, index) => [index + 1, {
      segment: index + 1, temperature: 60 + index, powerPercent: 20,
      hours: 0, minutes: index + 1, seconds: 10,
    }])),
  }
}

test('one to five logical stages are validated without mutating the draft', () => {
  for (let count = 1; count <= 5; count++) {
    const state = program(count)
    const before = structuredClone(state.segments)
    const payload = microwaveProgramPayload(state)
    assert.deepEqual(payload.map(s => s.segment), Array.from({ length: count }, (_, i) => i + 1))
    assert.equal(payload.at(-1)!.minutes, count)
    assert.equal(payload[0]!.holding_temperature, 60)
    assert.deepEqual(state.segments, before)
    assert.ok(payload.every(s => !('end_segment' in s) && !('heating_power_percent' in s)))
  }
})

test('host request converts hold time, preserves manual power, and rejects constant rate', () => {
  const state = program()
  state.segments[1]!.hours = 1
  const body = hostedMicrowavePayload(state, 'a'.repeat(32), true)
  assert.equal(body.stages[0]!.hold_seconds, 3670)
  assert.equal(body.hardware_confirmed, true)
  assert.equal(body.stages.length, 2)
  state.mode = 'manual_power'
  assert.equal(hostedMicrowavePayload(state, 'b'.repeat(32)).stages[0]!.power_percent, 20)
  state.mode = 'constant_rate'
  assert.throws(() => hostedMicrowavePayload(state, 'c'.repeat(32)), /模式/)
})

test('manual power and constant-rate programs retain their existing parameter semantics', () => {
  const state = program()
  state.mode = 'manual_power'
  assert.ok(microwaveProgramPayload(state).every(s => s.heating_power_percent === 20 && s.holding_power_percent === 20))
  state.mode = 'constant_rate'
  assert.ok(microwaveProgramPayload(state).every(s => s.ramp_seconds === 0 && s.target_temperature === s.holding_temperature))
})

test('invalid later used segment prevents configuring the entire program; invalid unused segment is ignored', () => {
  const state = program()
  state.segments[2]!.seconds = 60
  assert.throws(() => microwaveProgramPayload(state), /第 2 段/)
  assert.equal(microwaveProgramKey(state), '')
  state.usedSegments = 1
  assert.equal(microwaveProgramPayload(state).length, 1)
  for (const count of [0, 6, 1.5, NaN]) {
    state.usedSegments = count
    assert.throws(() => microwaveProgramPayload(state), /使用段数/)
  }
})

test('changes to range, mode, later segment temperature and duration require reconfiguration', () => {
  const mutations = [
    (p: MicrowaveProgram) => { p.usedSegments = 1 },
    (p: MicrowaveProgram) => { p.mode = 'manual_power' },
    (p: MicrowaveProgram) => { p.segments[2]!.temperature++ },
    (p: MicrowaveProgram) => { p.segments[2]!.seconds++ },
  ]
  for (const change of mutations) {
    const state = program()
    assert.equal(microwaveProgramConfigured(state), false)
    state.configuredProgramKey = microwaveProgramKey(state)
    assert.equal(microwaveProgramConfigured(state), true)
    change(state)
    assert.equal(microwaveProgramConfigured(state), false)
  }
  const state = program()
  state.configuredProgramKey = microwaveProgramKey(state)
  state.segments[5]!.temperature++
  assert.equal(microwaveProgramConfigured(state), true)
  state.configuredProgramKey = '' // Connection changes, failed configuration and starts clear this session evidence.
  assert.equal(microwaveProgramConfigured(state), false)
})
