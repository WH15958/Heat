import assert from 'node:assert/strict'
import { test } from 'node:test'
import { deferred, view } from './helpers/sfc'

test('REST progress requested before a WS terminal event cannot revive the old state', async () => {
  const response = deferred()
  const page = view('views/ExperimentPage.vue', { axios: { get: () => response.promise } })
  try {
    const s = page.state
    s.selectedFilename.value = 'audit.yaml'
    const polling = s.pollProgress()
    s.handleWsMessage({ data: JSON.stringify({ type: 'experiment_progress', filename: 'audit.yaml',
      state: 'completed', cleanup_pending: false, current_step: 2, total_steps: 2, elapsed: 10 }) })
    response.resolve({ data: { state: 'running', current_step: 0, total_steps: 2, elapsed: 1 } })
    await polling
    assert.equal(s.progress.value.state, 'completed')
    assert.equal(s.progress.value.current_step, 2)
  } finally { page.unmount() }
})

test('a pre-cleanup REST response cannot clear the later WS cleanup lock', async () => {
  const response = deferred()
  const page = view('views/ExperimentPage.vue', { axios: { get: () => response.promise } })
  try {
    const s = page.state
    s.selectedFilename.value = 'audit.yaml'
    const polling = s.pollProgress()
    s.handleWsMessage({ data: JSON.stringify({ type: 'experiment_progress', filename: 'audit.yaml',
      state: 'failed', cleanup_pending: true, current_step: 1, total_steps: 2, elapsed: 10 }) })
    response.resolve({ data: { state: 'running', cleanup_pending: false, elapsed: 1 } })
    await polling
    assert.equal(s.progress.value.state, 'failed')
    assert.equal(s.cleanupPending.value, true)
  } finally { page.unmount() }
})

test('failed progress reads expose unknown state and a fresh read clears the warning', async () => {
  let fails = true
  const page = view('views/ExperimentPage.vue', { axios: { get: async () => {
    if (fails) throw new Error('offline')
    return { data: { state: 'paused', current_step: 1, total_steps: 2, elapsed: 3 } }
  } } })
  try {
    const s = page.state
    s.selectedFilename.value = 'audit.yaml'
    s.progress.value = { state: 'running', cleanup_pending: false, current_step: 0, total_steps: 2, elapsed: 1 }
    await s.pollProgress()
    assert.equal(s.stateLabel.value, '状态未确认')
    assert.ok(s.progressError.value)
    assert.equal(s.isRunning.value, true) // Preserve STOP availability and the last known state.
    fails = false
    await s.pollProgress()
    assert.equal(s.progressError.value, '')
    assert.equal(s.stateLabel.value, '已暂停')
  } finally { page.unmount() }
})

test('slow progress requests survive poll ticks and release the slot after timeout', async () => {
  const response = deferred()
  let calls = 0
  const page = view('views/ExperimentPage.vue', { axios: { get: (_url: string, options: any) => {
    calls++
    assert.equal(options.timeout, 6000)
    return response.promise
  } } })
  try {
    const s = page.state
    s.selectedFilename.value = 'audit.yaml'
    const pending = s.pollProgress()
    await s.pollProgress()
    await s.pollProgress()
    assert.equal(calls, 1)
    response.reject(new Error('timeout'))
    await pending
    assert.equal(s.stateLabel.value, '状态未确认')
    await s.pollProgress()
    assert.equal(calls, 2)
  } finally { page.unmount() }
})

test('a failed stale REST request does not obscure fresh WS progress', async () => {
  const response = deferred()
  const page = view('views/ExperimentPage.vue', { axios: { get: () => response.promise } })
  try {
    const s = page.state
    s.selectedFilename.value = 'audit.yaml'
    const pending = s.pollProgress()
    s.handleWsMessage({ data: JSON.stringify({ type: 'experiment_progress', filename: 'audit.yaml',
      state: 'completed', cleanup_pending: false, current_step: 2, total_steps: 2, elapsed: 10 }) })
    response.reject(new Error('offline'))
    await pending
    assert.equal(s.progressError.value, '')
    assert.equal(s.stateLabel.value, '已完成')
  } finally { page.unmount() }
})
