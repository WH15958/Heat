import assert from 'node:assert/strict'
import { test } from 'node:test'
import { view, vue } from './helpers/sfc'

function panel() {
  const common = { connected: true, read_ok: true, busy: false, stop_confirmed: true,
    motion_blocked: false, homed: false, position: 0,
    ring_counts: [28, 20, 16, 8], ring_positions: [0, -147246, -297396, -444103],
    counts_per_revolution: 144000 }
  const states = vue.reactive({ r: { ...common, device_id: 'r', collection_axis: 'rotation' },
    p: { ...common, position_tolerance: 10, device_id: 'p', collection_axis: 'radial' } })
  const calls: any[] = []
  const api = { command: async (id: string, body: any) => { calls.push([id, body]); return { data: {} } },
    read: async (id: string) => ({ data: states[id as 'r' | 'p'] }) }
  return { ...view('components/CollectionControl.vue', {
    '../api/turntables': { turntableApi: api, turntableResult: {} },
  }, {}, { states }), states, calls, api }
}

test('pair readiness and calibrated positions gate bottle and ring controls', () => {
  const p = panel()
  try {
    assert.equal(p.state.currentBottle.value, 1)
    assert.equal(p.state.canRing.value, true)
    p.states.r.position = 5143
    assert.equal(p.state.currentBottle.value, 2)
    assert.equal(p.state.canRing.value, true)
    p.states.p.position = -94215
    assert.equal(p.state.canBottle.value, false)
    assert.equal(p.state.currentBottle.value, null)
    p.states.p.position = -147246
    p.states.r.position = 36000
    assert.equal(p.state.currentBottle.value, 34)
    p.states.p.read_ok = false
    assert.equal(p.state.canBottle.value, false)
    assert.equal(p.state.canHome.value, false)
    assert.equal(p.state.currentBottle.value, null)
    assert.equal(p.calls.length, 0)
  } finally { p.dispose() }
})

test('system stop reaches both axes even when one request fails', async () => {
  const p = panel()
  p.api.command = async (id, body) => {
    p.calls.push([id, body])
    if (id === 'r') throw new Error('timeout')
    return { data: {} }
  }
  try {
    await p.state.stopAll()
    assert.deepEqual(p.calls.map(c => c[0]), ['r', 'p'])
    assert.ok(p.calls.every(c => c[1].action === 'stop'))
    assert.equal(p.state.stopping.value, false)
    assert.equal(p.state.pending.value, 0)
    assert.ok(p.messages.some(m => m[0] === 'error'))
  } finally { p.dispose() }
})

test('read-back coordinates enable selection without home or manual confirmation', async () => {
  const p = panel()
  try {
    assert.equal(p.states.r.homed, false)
    assert.equal(p.state.canBottle.value, true)
    p.states.r.position = 5143
    assert.equal(p.state.currentBottle.value, 2)
    assert.equal(p.state.canRing.value, true)
    await p.state.send(p.states.p, { action: 'select_ring', ring: 2, expected_position: 0 })
    assert.equal(p.calls[0][1].action, 'select_ring')
    p.states.p.read_ok = false
    assert.equal(p.state.canBottle.value, false)
    p.states.p.read_ok = true
    assert.equal(p.state.canBottle.value, true)
  } finally { p.dispose() }
})

test('off-ring platform can return to a ring and start angle remains available', async () => {
  const p = panel()
  try {
    p.states.p.position = -94215
    assert.equal(p.state.ringLabel.value, '圈间位置')
    assert.equal(p.state.canStart.value, true)
    assert.equal(p.state.canRing.value, true)
    p.state.absolutePosition.value = -120000
    await p.state.movePlatform(p.states.p, false)
    assert.equal(p.calls[0][1].action, 'platform_absolute')
    assert.equal(p.calls[0][1].expected_position, -94215)
    p.states.p.position = -120000
    await p.state.send(p.states.p, { action: 'select_ring', ring: 2, expected_position: -120000 })
    assert.equal(p.calls[1][1].ring, 2)
    p.states.p.position = -147246
    p.states.p.busy = true
    assert.equal(p.state.ring.value, -1)
    assert.equal(p.state.ringLabel.value, '移动中')
    p.states.p.busy = false
    assert.equal(p.state.ring.value, 1)
  } finally { p.dispose() }
})

test('advanced inputs reject out-of-range and zero displacement before request', async () => {
  const p = panel()
  try {
    p.state.absolutePosition.value = 1
    await p.state.movePlatform(p.states.p, false)
    p.state.absolutePosition.value = -444104
    await p.state.movePlatform(p.states.p, false)
    p.state.relativeSteps.value = 0
    await p.state.movePlatform(p.states.p, true)
    p.states.p.position = -100
    p.state.relativeSteps.value = 101
    await p.state.movePlatform(p.states.p, true)
    assert.equal(p.calls.length, 0)
    p.state.relativeSteps.value = 100
    await p.state.movePlatform(p.states.p, true)
    assert.equal(p.calls[0][1].steps, 100)
    assert.equal(p.calls[0][1].expected_position, -100)
  } finally { p.dispose() }
})


test('ring and bottle recognition use server tolerance and keep raw position', () => {
  const p = panel()
  try {
    for (let ring = 0; ring < 4; ring++) {
      const target = p.states.p.ring_positions[ring]!
      for (const error of [-11, -10, -1, 0, 1, 10, 11]) {
        p.states.p.position = target + error
        const accepted = Math.abs(error) <= 10
        assert.equal(p.state.ring.value, accepted ? ring : -1)
        assert.equal(p.state.canBottle.value, accepted)
        assert.equal(p.states.p.position, target + error)
      }
    }
    p.states.p.position = -147245
    p.states.p.busy = true
    assert.equal(p.state.ring.value, -1)
    p.states.p.busy = false
    p.states.p.read_ok = false
    assert.equal(p.state.ring.value, -1)
    p.states.p.read_ok = true
    p.states.p.position_tolerance = 0
    assert.equal(p.state.ring.value, -1)
    assert.equal(p.calls.length, 0)
  } finally { p.dispose() }
})


test('guided ownership disables manual moves while stop remains available', async () => {
 const p=panel()
 try {
  Object.assign(p.states.r,{experiment_owned:true})
  Object.assign(p.states.p,{experiment_owned:true})
  assert.equal(p.state.canRing.value,false)
  assert.equal(p.state.canHome.value,false)
  assert.match(p.state.blockedReason(p.states.p),/引导式/)
  await p.state.send(p.states.p,{action:'select_ring',ring:2,expected_position:0})
  assert.equal(p.calls.length,0)
  await p.state.stopAll()
  assert.deepEqual(p.calls.map(c=>c[1].action),['stop','stop'])
 } finally {p.dispose()}
})
