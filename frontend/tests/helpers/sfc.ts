import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as confirmations from '../../src/composables/pendingConfirmation'

const require = createRequire(import.meta.url)
export { vue }
export const plain = (value: any) => JSON.parse(JSON.stringify(value))
export function deferred<T = any>() {
  let resolve!: (value?: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((a, b) => { resolve = a as any; reject = b })
  return { promise, resolve, reject }
}

export function moduleFromSource(file: string, overrides: Record<string, any> = {}) {
  const source = readFileSync(new URL('../../src/' + file, import.meta.url), 'utf8')
  const exports = {}
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  runInNewContext(compiled, { exports, require: (name: string) => {
    if (name in overrides) return overrides[name]
    if (/\.(webp|png|svg)$/.test(name)) return ''
    assert.ok(!name.startsWith('.'), `Provide isolated import ${name}`)
    return require(name)
  } })
  return exports as any
}

// Real Vue setup/reactivity; every transport, timer and browser side effect is injected.
export function view(file: string, overrides: Record<string, any> = {}, globals: Record<string, any> = {}, props: any = {}) {
  const mounted: (() => any)[] = [], unmounted: (() => void)[] = [], messages: any[][] = []
  const notify = Object.assign(() => ({ close() {} }), Object.fromEntries(['error', 'warning', 'info', 'success'].map(kind => [kind, (text: any) => messages.push([kind, text])])))
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted: (cb: any) => mounted.push(cb), onUnmounted: (cb: any) => unmounted.push(cb), onBeforeUnmount: (cb: any) => unmounted.push(cb), provide() {} },
    'vue-router': { useRoute: () => ({ query: {} }), useRouter: () => ({ push() {}, replace() {} }), onBeforeRouteLeave() {}, onBeforeRouteUpdate() {} },
    'element-plus': { ElMessage: notify, ElMessageBox: { confirm: async () => {}, prompt: async () => ({ value: '' }) } },
    '../composables/pendingConfirmation': confirmations,
    axios: {}, ...overrides,
  }
  const source = readFileSync(new URL('../../src/' + file, import.meta.url), 'utf8')
  const compiled = ts.transpileModule(compileScript(parse(source).descriptor, { id: file }).content,
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports = {} as any
  runInNewContext(compiled, { exports, console, URL, Blob,
    setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {},
    location: { protocol: 'http:', host: 'test.invalid' },
    localStorage: { getItem: () => null, setItem() {} },
    window: { addEventListener() {}, removeEventListener() {} },
    require: (name: string) => {
      if (name in imports) return imports[name]
      if (name.endsWith('.vue') || /\.(webp|png|svg)$/.test(name)) return {}
      assert.ok(!name.startsWith('.'), `Provide isolated import ${name}`)
      return require(name)
    }, ...globals })
  const scope = vue.effectScope()
  const state = scope.run(() => exports.default.setup(props, { expose() {}, emit() {} }))
  return { state, messages, mounted, unmount() { for (const cb of unmounted) cb(); scope.stop() }, dispose() { scope.stop() } }
}
