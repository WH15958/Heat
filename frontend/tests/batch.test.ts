import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse } from 'yaml'
import { combinations, generateSource, valuesFor, variablesFrom, microwaveHoldSeconds, type Axis } from '../src/experiment/batch.ts'

test('microwave minutes must represent whole seconds without truncation', () => {
  assert.equal(microwaveHoldSeconds(10), 600)
  assert.equal(microwaveHoldSeconds(1 / 60), 1)
  assert.equal(microwaveHoldSeconds(60.5), 3630)
  assert.equal(microwaveHoldSeconds(0), 0)
  for (const value of [.001, -1, Infinity, NaN, 1441]) assert.throws(() => microwaveHoldSeconds(value), /整秒/)
})

const source = readFileSync(new URL('../../experiments/syringe_dual_water.yaml', import.meta.url), 'utf8')
const axes = (): Axis[] => variablesFrom(source).map(v => ({ ...v, mode: 'fixed', start: v.value, end: v.value, interval: 1, list: String(v.value) }))
test('real template round trip keeps actions and fixed parameters', () => {
  const a = axes()
  assert.equal(a.length, 4)
  a[0]!.start = 150
  const generated = parse(generateSource(source, a, combinations(a)[0]!, 'batch_test', 0))
  const original = parse(source)
  original.steps[2].params.volume = 150
  assert.deepEqual(generated.steps, original.steps)
  assert.equal(generated.metadata.batch_id, 'batch_test')
  assert.equal(generated.metadata.condition_id, 'condition_1')
  assert.equal(generated.metadata.safety_notes, original.metadata.safety_notes)
})
test('decimal ranges, list deduplication and Cartesian ordering', () => {
  const a = axes().slice(0, 2)
  Object.assign(a[0]!, { mode: 'range', start: 0.1, end: 0.3, interval: 0.1 })
  Object.assign(a[1]!, { mode: 'list', list: '1, 2, 2' })
  assert.deepEqual(combinations(a), [[0.1, 1], [0.1, 2], [0.2, 1], [0.2, 2], [0.3, 1], [0.3, 2]])
  a[0]!.end = 0.25
  assert.deepEqual(valuesFor(a[0]!), [0.1, 0.2])
})
test('reject invalid and excessive combinations before allocation', () => {
  const a = axes()
  Object.assign(a[0]!, { mode: 'range', start: 1, end: 200, interval: 0 })
  assert.throws(() => combinations(a))
  a[0]!.interval = 1
  Object.assign(a[1]!, { mode: 'list', list: '1,2' })
  assert.throws(() => combinations(a))
  Object.assign(a[0]!, { mode: 'list', list: 'NaN' })
  assert.throws(() => combinations(a))
  assert.throws(() => generateSource(source, [], [], '../bad', 0))
})
test('disabled actions remain fixed and previous sample identity is removed', () => {
  const text = '# keep this\nname: test\nmetadata: {sample_id: old}\nsteps:\n  - id: wait\n    type: wait\n    enabled: false\n    wait: {type: duration, seconds: 5}\n'
  assert.deepEqual(variablesFrom(text), [])
  const result = generateSource(text, [], [], 'new', 1)
  assert.ok(result.includes('# keep this'))
  assert.equal(parse(result).metadata.sample_id, undefined)
  assert.equal(parse(result).steps[0].wait.seconds, 5)
})
