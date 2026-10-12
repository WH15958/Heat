import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const source = readFileSync(new URL('../src/views/ExperimentPage.vue', import.meta.url), 'utf8')
const compiled = ts.transpileModule(compileScript(parse(source).descriptor, { id: 'cleanup' }).content,
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

test('failed cleanup remains retryable through REST and WS until a confirmed stop', async () => {
  const timers = new Set<number>(), posts: string[] = []
  let nextTimer = 0, stopped = false
  const snapshot = () => stopped ? { state: 'idle' } : {
    state: 'failed', cleanup_pending: true, current_step: 1, total_steps: 1, elapsed: 2,
  }
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted() {}, onUnmounted() {} },
    'vue-router': { useRoute: () => ({ query: {} }), useRouter: () => ({ push() {} }) },
    axios: {
      get: async () => ({ data: snapshot() }),
      post: async (url: string) => { posts.push(url); stopped = true; return { data: { success: true } } },
    },
    'element-plus': { ElMessage: { info() {}, error() {} }, ElMessageBox: { confirm: async () => {} } },
    '../components/ExperimentGuide.vue': {},
  }
  const exports: any = {}
  runInNewContext(compiled, { exports, require: (name: string) => imports[name],
    setInterval: () => { timers.add(++nextTimer); return nextTimer },
    clearInterval: (id: number) => timers.delete(id) })
  const page = exports.default.setup({}, { expose() {} })
  page.selectedFilename.value = 'review.yaml'
  await page.pollProgress()
  assert.equal(page.cleanupPending.value, true)
  assert.equal(timers.size, 1)
  assert.match(source, /@click="stopExperiment" :disabled="!isRunning && !isPaused && !cleanupPending"/)
  page.handleWsMessage({ data: JSON.stringify({ type: 'experiment_progress', filename: 'review.yaml', ...snapshot() }) })
  assert.equal(page.cleanupPending.value, true)
  assert.equal(timers.size, 1)
  await page.stopExperiment()
  assert.deepEqual(posts, ['/api/experiments/review.yaml/stop'])
  assert.equal(page.cleanupPending.value, false)
  assert.equal(page.progress.value.state, 'failed') // Keep the original run outcome.
  assert.equal(timers.size, 0)
})
