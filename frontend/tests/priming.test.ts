import { test } from 'node:test'
import assert from 'node:assert/strict'
import { primingDrainForDisplay } from '../src/experiment/priming.ts'
import { estimateDrainSeconds } from '../src/experiment/drainEstimate.ts'

test('new records retain explicit time and independent priming flow', () => {
  assert.deepEqual(primingDrainForDisplay({ prime_drain_seconds: 123, prime_drain_flow: 2, drain_flow: 3 }),
    { prime_drain_seconds: 123, prime_drain_flow: 2 })
})

test('legacy display uses the original factor, extra seconds and collection flow', () => {
  const legacy = { prime_volume_a: 1.5, prime_volume_b: 2, prime_cycles: 3,
    prime_drain_factor: 1.5, prime_extra_seconds: 12, drain_flow: 2 }
  assert.deepEqual(primingDrainForDisplay(legacy), { prime_drain_seconds: 484.5, prime_drain_flow: 2 })
  assert.equal('prime_drain_seconds' in legacy, false)
})

test('theoretical estimate has no implicit safety margin', () => {
  assert.equal(estimateDrainSeconds((2 + 2) * 2, 1), 480)
  assert.equal(estimateDrainSeconds((1.5 + 2) * 3, 2), 315)
})
