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

test('timed hold renders backend elapsed and remaining and continues through temperature excursion', async () => {
  const html = await renderToString(vue.createSSRApp(component, { activity: {
    ...activity, hold_mode: 'timed', qualified_seconds: null, elapsed_seconds: 30.2, remaining_seconds: 29.8,
  } }))
  assert.match(html, /温度偏离目标，计时继续/)
  assert.match(html, /定时保温 30.2 \/ 60 秒/)
  assert.match(html, /剩余 29.8 秒/)
  assert.doesNotMatch(html, /有效保温|暂停累计|上限 660/)
})

test('timed hold only announces completion from confirmed activity state', async () => {
  const pending = { ...activity, hold_mode: 'timed', qualified_seconds: null, elapsed_seconds: 60, remaining_seconds: 0 }
  const html = await renderToString(vue.createSSRApp(component, { activity: pending }))
  assert.match(html, /等待设备状态确认/)
  assert.doesNotMatch(html, /定时保温完成/)
  const completed = await renderToString(vue.createSSRApp(component, { activity: { ...pending, state: 'completed' } }))
  assert.match(completed, /定时保温完成/)
})

test('timed hold actual pause takes precedence over excursion and unavailable times remain unknown', async () => {
  const html = await renderToString(vue.createSSRApp(component, { activity: {
    ...activity, hold_mode: 'timed', paused: true, qualified_seconds: null, elapsed_seconds: null, remaining_seconds: null,
  } }))
  assert.match(html, /已暂停，保温计时暂停/)
  assert.match(html, /定时保温 未知 \/ 60 秒/)
  assert.match(html, /剩余 未知 秒/)
  assert.doesNotMatch(html, /计时继续/)
})

test('microwave stable phase uses backend thirty-second progress without claiming hold has started', async () => {
  const stable = { state: 'waiting', wait_type: 'microwave_temperature_reached', stable_seconds: 12.4,
    stable_required_seconds: 30, readings: activity.readings }
  const html = await renderToString(vue.createSSRApp(component, { activity: stable }))
  assert.match(html, /等待反应液连续稳定/)
  assert.match(html, /连续稳定 12.4 \/ 30 秒/)
  assert.match(html, /目标 60 ±3℃/)
  assert.doesNotMatch(html, /正在定时保温|双路/)
  const paused = await renderToString(vue.createSSRApp(component, { activity: { ...stable, paused: true } }))
  assert.match(paused, /恢复后重新稳定计时/)
  const unknown = await renderToString(vue.createSSRApp(component, { activity: { ...stable, stable_seconds: null } }))
  assert.match(unknown, /连续稳定 未知 \/ 30 秒/)
})
