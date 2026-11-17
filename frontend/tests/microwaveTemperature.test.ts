import assert from 'node:assert/strict'
import { test } from 'node:test'
import { microwaveTemperatureDisplay as display } from '../src/utils/microwaveTemperature'

const sample = { device_id: 'mw', read_ok: true, value: 61.1, sampled_at: 100 }
const program = { state: 'running', activity: { readings: [sample] } }

test('running and paused use the executor sample despite different realtime temperature', () => {
  for (const state of ['running', 'paused']) {
    const result = display('mw', { ...program, state }, 62.4, true, 101000)
    assert.equal(result.top, '61.1℃')
    assert.equal(result.top, result.reading.text)
    assert.equal(result.reading.label, '实际')
  }
})

test('repeated snapshots expire by original sample time, including while paused', () => {
  for (const state of ['running', 'paused']) {
    assert.equal(display('mw', { ...program, state }, 62.4, true, 105999).top, '61.1℃')
    const expired = display('mw', { ...program, state }, 62.4, true, 106000)
    assert.equal(expired.top, '温度已过期')
    assert.equal(expired.top, expired.reading.text)
  }
})

test('unavailable or invalid executor readings never fall back to realtime', () => {
  for (const reading of [undefined, { ...sample, read_ok: false }, { ...sample, sampled_at: undefined },
    { ...sample, value: NaN }, { ...sample, value: -1 }, { ...sample, device_id: 'other' }]) {
    const result = display('mw', { ...program, activity: { readings: reading ? [reading] : [] } }, 62.4, true, 101000)
    assert.equal(result.top, '温度未知')
    assert.equal(result.top, result.reading.text)
  }
  assert.equal(display('mw', program, 62.4, false, 101000).top, '温度未知')
  assert.equal(display('mw', { ...program, status_error: 'failed' }, 62.4, true, 101000).top, '温度未知')
})

test('terminal samples are historical and top resumes realtime', () => {
  for (const state of ['completed', 'failed', 'stopped', 'interrupted', 'idle']) {
    const result = display('mw', { ...program, state }, 62.4, true, 200000)
    assert.equal(result.top, '62.4℃')
    assert.equal(result.reading.text, '61.1℃')
    assert.equal(result.reading.label, '最后采样温度')
  }
  assert.equal(display('mw', undefined, 62.4, true, 200000).top, '62.4℃')
})
