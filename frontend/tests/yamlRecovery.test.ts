import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const source = readFileSync(new URL('../src/views/ExperimentPage.vue', import.meta.url), 'utf8')
const compiled = ts.transpileModule(compileScript(parse(source).descriptor, { id: 'yaml-recovery' }).content,
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

function page() {
  const unmounts: (() => void)[] = []
  const pending = [{ recovery_id: 'yaml_test', filename: 'deleted.yaml', run_id: 'old_run' }]
  const posts: any[] = [], errors: string[] = []
  const behavior = {
    read: async (): Promise<any> => pending,
    confirm: async () => {},
    write: async (): Promise<any> => ({ success: true }),
  }
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted() {}, onUnmounted(fn: () => void) { unmounts.push(fn) } },
    'vue-router': { useRoute: () => ({ query: {} }), useRouter: () => ({ push() {} }) },
    axios: {
      get: async () => ({ data: await behavior.read() }),
      post: async (...args: any[]) => { posts.push(args); return { data: await behavior.write() } },
    },
    'element-plus': { ElMessage: { error: (s: string) => errors.push(s) }, ElMessageBox: { confirm: () => behavior.confirm() } },
    '../components/ExperimentGuide.vue': {},
  }
  const exports: any = {}
  runInNewContext(compiled, { exports, require: (name: string) => imports[name] })
  const state = exports.default.setup({}, { expose() {} })
  return { state, pending, behavior, posts, errors, unmount: () => unmounts.forEach(fn => fn()) }
}

test('refresh loads interrupted YAML without starting, resuming or acknowledging it', async () => {
  const p = page()
  assert.equal(p.state.recoveryBlocked.value, true)
  await p.state.loadRecovery()
  assert.equal(p.state.recoveryRecords.value[0].filename, 'deleted.yaml')
  assert.equal(p.state.recoveryBlocked.value, true)
  await p.state.startExperiment()
  assert.deepEqual(p.posts, [])
})

test('failed recovery read blocks starts and is visible', async () => {
  const p = page()
  p.behavior.read = async () => { throw new Error('offline') }
  await p.state.startExperiment()
  assert.match(p.state.recoveryError.value, /offline/)
  assert.equal(p.state.recoveryBlocked.value, true)
  assert.equal(p.state.starting.value, false)
  assert.deepEqual(p.posts, [])
})

test('explicit acknowledgement is single-flight and never replays a run', async () => {
  const p = page()
  await p.state.loadRecovery()
  let confirm!: () => void
  p.behavior.confirm = () => new Promise<void>(resolve => { confirm = resolve })
  p.behavior.write = async () => { p.pending.splice(0); return { success: true } }
  const first = p.state.acknowledgeRecovery('yaml_test')
  await p.state.acknowledgeRecovery('yaml_test')
  assert.equal(p.posts.length, 0)
  confirm(); await first
  assert.equal(p.posts.length, 1)
  assert.equal(p.posts[0][0], '/api/experiments/recovery/yaml_test/acknowledge')
  assert.equal(p.posts[0][1].devices_stopped_confirmed, true)
  assert.equal(p.state.recoveryBlocked.value, false)
})

for (const failure of ['cancel', 'storage', 'false']) {
  test(`${failure} does not remove the displayed recovery lock`, async () => {
    const p = page()
    await p.state.loadRecovery()
    if (failure === 'cancel') p.behavior.confirm = async () => { throw 'cancel' }
    if (failure === 'storage') p.behavior.write = async () => { throw new Error('disk full') }
    if (failure === 'false') p.behavior.write = async () => ({ success: false })
    await p.state.acknowledgeRecovery('yaml_test')
    assert.equal(p.state.recoveryBlocked.value, true)
    assert.equal(p.state.recoveryRecords.value.length, 1)
    assert.equal(p.state.recovering.value, '')
    if (failure === 'cancel') assert.deepEqual(p.posts, [])
    else assert.equal(p.errors.length, 1)
  })
}

test('late stale refresh cannot overwrite the state after acknowledgement', async () => {
  const p = page()
  let delayed!: (value: any) => void
  p.behavior.read = () => new Promise(resolve => { delayed = resolve })
  const old = p.state.loadRecovery()
  p.behavior.read = async () => []
  await p.state.acknowledgeRecovery('yaml_test')
  delayed(p.pending); await old
  assert.equal(p.state.recoveryRecords.value.length, 0)
  assert.equal(p.state.recoveryBlocked.value, false)
})

test('leaving the page cancels an unsubmitted YAML start confirmation', async () => {
  const p = page()
  p.state.selectedFilename.value = 'test.yaml'
  p.behavior.read = async () => []
  let confirm!: () => void
  let shown!: () => void
  const opened = new Promise<void>(resolve => { shown = resolve })
  p.behavior.confirm = () => new Promise<void>(resolve => { confirm = resolve; shown() })
  const start = p.state.startExperiment()
  await opened
  p.unmount()
  confirm(); await start
  assert.deepEqual(p.posts, [])
  assert.equal(p.state.starting.value, false)
})
