import { test } from 'node:test'
import assert from 'node:assert/strict'
import { estimateDrainSeconds } from '../src/experiment/drainEstimate.ts'
test('each group uses its own total volume and minutes convert to seconds', () => {
  assert.equal(estimateDrainSeconds(0.2 + 0.3, 2), 15)
  assert.equal(estimateDrainSeconds(1 + 2, 2), 90)
  assert.equal(estimateDrainSeconds(1, 1), 60)
})
test('invalid flow, volume and overflow cannot produce a duration', () => {
  for (const value of [0, -1, NaN, Infinity]) {
    assert.throws(() => estimateDrainSeconds(1, value))
    assert.throws(() => estimateDrainSeconds(value, 1))
  }
  assert.throws(() => estimateDrainSeconds(Number.MAX_VALUE, Number.MIN_VALUE))
})
