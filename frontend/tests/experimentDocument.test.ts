import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isSeq, parseDocument } from 'yaml'
import { duplicateStep, editSource, inspectSource, moveStep, patchMap, setValue, uniqueId } from '../src/experiment/document.ts'

const original = `# experiment notes
name: example
metadata:
  custom: keep # metadata note
extra: retained
steps:
  # first step note
  - id: a
    type: log
    enabled: false
    on_error: skip
    extra: retained
    params: {message: hello}
    wait: {type: duration, seconds: 5, timeout: 10} # wait note
  - id: b
    type: wait
    wait: {type: duration, seconds: 2}
`
test('inspecting and switching does not rewrite source', () => {
  assert.equal(inspectSource(original).editable, true)
  assert.equal(original.includes('# wait note'), true)
})
test('local field edit keeps comments, unknown fields, full waits and disabled steps', () => {
  const changed = editSource(original, doc => setValue(doc, ['steps', 0, 'params', 'message'], 'changed'))
  for (const comment of ['# experiment notes', '# metadata note', '# first step note', '# wait note']) assert.ok(changed.includes(comment))
  const data = parseDocument(changed).toJS()
  assert.equal(data.steps[0].enabled, false)
  assert.equal(data.steps[0].on_error, 'skip')
  assert.equal(data.steps[0].wait.timeout, 10)
  assert.equal(data.steps[0].extra, 'retained')
  assert.equal(data.metadata.custom, 'keep')
})
test('move/duplicate preserve step nodes and assign a distinct ID', () => {
  const changed = editSource(original, doc => { moveStep(doc, 0, 1); duplicateStep(doc, 1) })
  const data = parseDocument(changed).toJS()
  assert.deepEqual(data.steps.map((s: any) => s.id), ['b', 'a', 'log_1'])
  assert.equal(data.steps[2].enabled, false)
  assert.ok(changed.includes('# first step note'))
  assert.equal(uniqueId(parseDocument(changed), 'log'), 'log_2')
})
test('advanced map editing preserves untouched nested comments', () => {
  const changed = editSource(original, doc => patchMap(doc, ['steps', 0], { ...doc.toJS().steps[0], id: 'renamed' }))
  assert.ok(changed.includes('# wait note'))
  assert.equal(parseDocument(changed).toJS().steps[0].id, 'renamed')
})
test('unsupported syntax and malformed YAML protect the original', () => {
  for (const text of ['steps: [', 'steps: []\nsteps: []', 'steps: []\n---\nsteps: []', 'steps: &s []', 'a: &a {}\nsteps: [*a]', 'steps: [{<<: {id: a}, type: log}]', 'steps: !custom []', 'steps: [{type: 8}]', 'steps: [{type: log, params: 9}]']) {
    assert.equal(inspectSource(text).editable, false, text)
    assert.throws(() => editSource(text, () => {}))
  }
  assert.equal(inspectSource('steps: []').editable, true)
})
test('deleting can be undone by restoring previous source snapshot', () => {
  const history = [original]
  history.push(editSource(original, doc => doc.deleteIn(['steps', 0])))
  assert.equal((parseDocument(history[1]!).toJS().steps).length, 1)
  assert.equal(history[0], original)
  assert.ok(isSeq(inspectSource(history[0]!).doc!.get('steps', true)))
})
