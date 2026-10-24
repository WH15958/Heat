import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { RealtimeData } from '../src/composables/useWebSocket'
import { createMonitorHistory, mergeMonitorFrames, recordMonitorFrame, MONITOR_FRESHNESS_MS } from '../src/utils/monitorHistory'

function frame(): RealtimeData {
  return {
    type: 'realtime', heaters: { heater1: { pv: 28, sv: 50, mv: 100, run_status: 'RUN', alarms: [] } },
    microwaves: { microwave1: { material_temperature: 60 } }, valves: {}, syringe_pumps: {}, turntables: {},
    pumps: { pump1: { device_id: 'pump1', channels: { '1': { read_ok: true, running: true, flow_rate: 15000, flow_unit: 'UL_MIN', volume: 0, direction: 'CLOCKWISE' } } } },
  }
}

test('normal 6.4-second sweeps retain connected temperature and flow samples', () => {
  const history = createMonitorHistory()
  for (const at of [1000, 7400, 13800]) recordMonitorFrame(history, frame(), at)
  assert.deepEqual(history.heaters.heater1.pv, [[1000, 28], [7400, 28], [13800, 28]])
  assert.deepEqual(history.microwaves.microwave1.temperature, [[1000, 60], [7400, 60], [13800, 60]])
  assert.deepEqual(history.pumps.pump1.channels['1'], [[1000, 15], [7400, 15], [13800, 15]])
  assert.equal(history.lastReceivedAt, 13800)
})

test('a telemetry expiry or explicit transport interruption preserves a gap', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  recordMonitorFrame(history, frame(), 1000 + MONITOR_FRESHNESS_MS + 1)
  assert.equal(history.heaters.heater1.pv.at(-2)![1], null)
  history.interrupted = true
  recordMonitorFrame(history, frame(), 18000)
  for (const points of [history.heaters.heater1.pv, history.microwaves.microwave1.temperature, history.pumps.pump1.channels['1']]) {
    assert.deepEqual(points.slice(-2).map(point => point[1]), [null, points.at(-1)![1]])
  }
  assert.equal(history.interrupted, false)
})

test('read failures and absent devices break curves without replacing last valid temperatures', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  const invalid = frame()
  invalid.heaters.heater1.error = 'read_timeout'
  invalid.microwaves.microwave1.material_temperature = NaN
  invalid.pumps.pump1.channels['1'].read_ok = false
  recordMonitorFrame(history, invalid, 2000)
  recordMonitorFrame(history, { ...frame(), heaters: {}, microwaves: {}, pumps: {} }, 3000)
  recordMonitorFrame(history, frame(), 4000)
  assert.deepEqual(history.heaters.heater1.pv.map(point => point[1]), [28, null, 28])
  assert.deepEqual(history.microwaves.microwave1.temperature.map(point => point[1]), [60, null, 60])
  assert.deepEqual(history.pumps.pump1.channels['1'].map(point => point[1]), [15, null, 15])
  assert.equal(history.lastHeaters.heater1.pv, 28)
  assert.equal(history.lastMicrowaves.microwave1.material_temperature, 60)
})

test('unknown pump status is not interpreted as stopped and unsupported units remain gaps', () => {
  const history = createMonitorHistory()
  const data = frame()
  recordMonitorFrame(history, data, 1000)
  data.pumps.pump1.channels['1'].running = null
  recordMonitorFrame(history, data, 2000)
  data.pumps.pump1.channels['1'].running = true
  data.pumps.pump1.channels['1'].flow_unit = 'RPM'
  recordMonitorFrame(history, data, 3000)
  data.pumps.pump1.channels['1'].running = false
  recordMonitorFrame(history, data, 4000)
  assert.deepEqual(history.pumps.pump1.channels['1'].map(point => point[1]), [15, null, 0])
})

test('each series is bounded to the latest 1800 points', () => {
  const history = createMonitorHistory()
  const data = frame()
  for (let index = 0; index < 1810; index++) recordMonitorFrame(history, data, index * 1000)
  assert.equal(history.heaters.heater1.pv.length, 1800)
  assert.equal(history.heaters.heater1.pv[0]![0], 10000)
  assert.equal(history.microwaves.microwave1.temperature.length, 1800)
  assert.equal(history.pumps.pump1.channels['1'].length, 1800)
  assert.equal(history.frames.length, 1800)
})

test('first entry and full reload hydrate sorted, deduplicated server samples', () => {
  const frames = [3000, 1000, 2000, 3000].map(sampled_at_ms => {
    const data = frame()
    data.heaters.heater1.pv = sampled_at_ms / 100
    return { ...data, sampled_at_ms }
  })
  for (const history of [createMonitorHistory(), createMonitorHistory()]) {
    mergeMonitorFrames(history, frames)
    assert.deepEqual(history.heaters.heater1.pv, [[1000, 10], [2000, 20], [3000, 30]])
    assert.deepEqual(history.microwaves.microwave1.temperature.map(([at]) => at), [1000, 2000, 3000])
    assert.equal(history.lastReceivedAt, 3000)
    assert.equal(history.lastHeaters.heater1.pv, 30)
    assert.equal(history.frames.length, 3)
  }
})

test('history merges into existing SPA samples, and empty or duplicate history does not erase them', () => {
  const history = createMonitorHistory()
  const map = history.heaters
  recordMonitorFrame(history, frame(), 3000)
  recordMonitorFrame(history, frame(), 4000)
  mergeMonitorFrames(history, [1000, 2000, 3000].map(sampled_at_ms => ({ ...frame(), sampled_at_ms })))
  assert.equal(history.heaters, map)
  assert.deepEqual(history.heaters.heater1.pv.map(([at]) => at), [1000, 2000, 3000, 4000])
  assert.equal(history.lastReceivedAt, 4000)
  const revision = history.revision
  mergeMonitorFrames(history, [])
  mergeMonitorFrames(history, [{ ...frame(), sampled_at_ms: 3000 }])
  assert.equal(history.revision, revision)
  assert.equal(history.heaters.heater1.pv.length, 4)
})

test('late and repeated realtime samples stay chronological without moving the latest time backward', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 3000)
  recordMonitorFrame(history, frame(), 1000)
  recordMonitorFrame(history, frame(), 2000)
  const revision = history.revision
  recordMonitorFrame(history, frame(), 2000)
  assert.deepEqual(history.heaters.heater1.pv.map(([at]) => at), [1000, 2000, 3000])
  assert.equal(history.lastReceivedAt, 3000)
  assert.equal(history.revision, revision)
  const changed = frame()
  changed.heaters.heater1.pv = 31
  recordMonitorFrame(history, changed, 2000)
  assert.deepEqual(history.heaters.heater1.pv, [[1000, 28], [2000, 31], [3000, 28]])
  assert.equal(history.lastHeaters.heater1.pv, 28)
  assert.ok(history.revision > revision)
})

test('PV and SV validate independently and retain their own last valid temperature', () => {
  const history = createMonitorHistory()
  mergeMonitorFrames(history, [
    { sampled_at_ms: 1000, heaters: { heater1: { pv: 28, sv: NaN } } },
    { sampled_at_ms: 2000, heaters: { heater1: { pv: NaN, sv: 50 } } },
    { sampled_at_ms: 3000, heaters: { heater1: { pv: 30 } } },
  ])
  assert.deepEqual(history.heaters.heater1.pv, [[1000, 28], [2000, null], [3000, 30]])
  assert.deepEqual(history.heaters.heater1.sv, [[2000, 50], [3000, null]])
  assert.equal(history.lastHeaters.heater1.pv, 30)
  assert.equal(history.lastHeaters.heater1.sv, 50)
})

test('actual server samples covering a transport interruption restore that part of the curve', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  history.interrupted = true
  recordMonitorFrame(history, frame(), 7400)
  assert.deepEqual(history.heaters.heater1.pv.map(point => point[1]), [28, null, 28])
  const revision = history.revision
  mergeMonitorFrames(history, [{ ...frame(), sampled_at_ms: 4200 }])
  assert.deepEqual(history.heaters.heater1.pv, [[1000, 28], [4200, 28], [7400, 28]])
  assert.equal(history.lastReceivedAt, 7400)
  assert.ok(history.revision > revision)

  history.interrupted = true
  mergeMonitorFrames(history, [{ ...frame(), sampled_at_ms: 9000 }])
  recordMonitorFrame(history, frame(), 10000)
  assert.ok(history.heaters.heater1.pv.every(([, value]) => value !== null))
})

test('a repeated historical timestamp can confirm continuity without changing the latest timestamp', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  history.interrupted = true
  recordMonitorFrame(history, frame(), 7400)
  recordMonitorFrame(history, frame(), 4200)
  assert.ok(history.heaters.heater1.pv.some(([, value]) => value === null))
  const revision = history.revision
  mergeMonitorFrames(history, [{ ...frame(), sampled_at_ms: 4200 }])
  assert.deepEqual(history.heaters.heater1.pv, [[1000, 28], [4200, 28], [7400, 28]])
  assert.equal(history.lastReceivedAt, 7400)
  assert.ok(history.revision > revision)
})

test('complete backfill fills a long gap using actual timestamps without fabricated points', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  recordMonitorFrame(history, frame(), 30000)
  mergeMonitorFrames(history, [10000, 20000].map(sampled_at_ms => ({ ...frame(), sampled_at_ms })))
  assert.deepEqual(history.heaters.heater1.pv, [[1000, 28], [10000, 28], [20000, 28], [30000, 28]])
})

test('history backfill preserves real read failures, missing devices and remaining long gaps', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  recordMonitorFrame(history, frame(), 30000)
  const invalid = frame()
  invalid.heaters.heater1.error = 'read_timeout'
  invalid.microwaves.microwave1.error = 'read_timeout'
  mergeMonitorFrames(history, [
    { ...frame(), sampled_at_ms: 5000 },
    { ...invalid, sampled_at_ms: 6000 },
    { sampled_at_ms: 7000 },
    { ...frame(), sampled_at_ms: 8000 },
  ])
  assert.deepEqual(history.heaters.heater1.pv, [
    [1000, 28], [5000, 28], [6000, null], [8000, 28], [29999, null], [30000, 28],
  ])
  assert.deepEqual(history.microwaves.microwave1.temperature.map(point => point[1]), [60, 60, null, 60, null, 60])
  assert.ok(history.pumps.pump1.channels['1'].some(([at, value]) => at === 7000 && value === null))
})

test('hydration keeps only bounded trend fields and copies inputs before later mutation', () => {
  const history = createMonitorHistory()
  const data = frame()
  mergeMonitorFrames(history, Array.from({ length: 1810 }, (_, index) => ({ ...data, sampled_at_ms: index * 1000 })))
  assert.equal(history.frames.length, 1800)
  assert.equal(history.heaters.heater1.pv.length, 1800)
  assert.equal(history.heaters.heater1.pv[0]![0], 10000)
  assert.equal('valves' in history.frames[0]!, false)
  assert.equal('syringe_pumps' in history.frames[0]!, false)
  assert.deepEqual(Object.keys(history.frames[0]!.heaters.heater1), ['pv', 'sv'])
  data.heaters.heater1.pv = 100
  data.pumps.pump1.channels['1'].flow_rate = 900000
  assert.equal(history.heaters.heater1.pv.at(-1)![1], 28)
  assert.equal(history.pumps.pump1.channels['1'].at(-1)![1], 15)
})

test('invalid timestamps and empty history leave the existing history unchanged', () => {
  const history = createMonitorHistory()
  recordMonitorFrame(history, frame(), 1000)
  history.interrupted = true
  const revision = history.revision
  recordMonitorFrame(history, frame(), NaN)
  mergeMonitorFrames(history, [{ ...frame(), sampled_at_ms: NaN }, { sampled_at_ms: -1 }])
  assert.equal(history.lastReceivedAt, 1000)
  assert.equal(history.revision, revision)
  assert.equal(history.interrupted, true)
})
