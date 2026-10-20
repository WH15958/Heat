import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

const source = readFileSync(new URL('../src/components/MicrowaveHoldProgress.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'hold-progress', inlineTemplate: true }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const exports = {} as any
runInNewContext(compiled, { exports, require: () => vue })
const component = exports.default
const activity = { state: 'waiting', qualified_seconds: 12, duration_seconds: 60, hold_in_band: false,
  elapsed_seconds: 30, hold_timeout_seconds: 660,
  readings: [{ device_id: 'microwave1', read_ok: true, value: 65.625, target: 60, tolerance: 3 }] }

test('renders actual qualified time, excursion and limits without a browser timer', async () => {
  const html = await renderToString(vue.createSSRApp(component, { activity }))
  assert.match(html, /温度越界，暂停累计/)
  assert.match(html, /有效保温 12 \/ 60 秒/)
  assert.match(html, /65.6℃/)
  assert.match(html, /60 ±3℃/)
  assert.match(html, /已等待 30 秒 · 上限 660 秒/)
})

test('legacy activities do not invent a qualified time', async () => {
  const html = await renderToString(vue.createSSRApp(component, { activity: { state: 'waiting' } }))
  assert.doesNotMatch(html, /有效保温/)
})

test('actual pause is shown without claiming that qualified time is accumulating', async () => {
  const html = await renderToString(vue.createSSRApp(component, { activity: {
    ...activity, hold_in_band: true, paused: true,
  } }))
  assert.match(html, /已暂停，保温计时暂停/)
  assert.doesNotMatch(html, /正在累计/)
})

test('terminal and unknown readings do not claim temperature or running status', async () => {
  const html = await renderToString(vue.createSSRApp(component, { activity: {
    ...activity, state: 'failed', readings: [{ ...activity.readings[0], read_ok: false }],
  } }))
  assert.match(html, /保温未完成/)
  assert.match(html, /温度未知/)
  assert.doesNotMatch(html, /正在累计/)
})
