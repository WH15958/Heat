import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const source = readFileSync(new URL('../src/views/HistoryPage.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'history-acceptance' }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

async function chart(channel: any) {
  const options: any[] = []
  const imports: Record<string, any> = {
    vue: { ...vue, onMounted() {}, onUnmounted() {} },
    'vue-router': { useRoute: () => ({ query: {} }) },
    axios: {}, 'element-plus': {}, '../experiment/guidedProgress': {},
    '../components/SyringeHistory.vue': {},
    '../lib/echarts': { init: () => ({ setOption: (option: any) => options.push(option), dispose() {} }) },
  }
  const exports: any = {}
  runInNewContext(compiled, { exports, require: (name: string) => {
    assert.ok(name in imports, name)
    return imports[name]
  } })
  const scope = vue.effectScope()
  try {
    const state = scope.run(() => exports.default.setup({}, { expose() {} }))
    state.detailData.value = { sensor_data: { heaters: {}, pumps: { pump1: { '1': channel } } } }
    state.reportFlowChartRef.value = {}
    state.reportVolumeChartRef.value = {}
    state.renderReportCharts()
    await vue.nextTick()
    return JSON.parse(JSON.stringify(options))
  } finally { scope.stop() }
}

function channel(unit = 'ML_MIN') {
  return { flow_unit: unit, flow_rate: [0, 60, 120].map(t => ({ t, v: 10 })),
    read_ok: [0, 60, 120].map(t => ({ t, v: true })),
    running: [0, 60, 120].map(t => ({ t, v: true })) }
}

test('actual history chart estimates volume only for known volumetric flow', async () => {
  const [, volume] = await chart(channel())
  assert.deepEqual(volume.series[0].data, [[0, 0], [60, 10], [120, 20]])
})

test('failed reading creates a gap and invalidates the subsequent cumulative total', async () => {
  const data = channel()
  data.read_ok[1].v = false
  const [flow, volume] = await chart(data)
  assert.deepEqual(flow.series[0].data, [[0, 10], [60, null], [120, 10]])
  assert.deepEqual(volume.series[0].data, [[0, 0], [60, null], [120, null]])
})

test('legacy samples without validity flags do not establish transport', async () => {
  const data: any = channel()
  delete data.read_ok; delete data.running
  const [flow, volume] = await chart(data)
  assert.ok(flow.series[0].data.every((p: any) => p[1] === null))
  assert.ok(volume.series[0].data.every((p: any) => p[1] === null))
})

for (const unit of ['RPM', 'UNKNOWN', 'MIXED']) {
  test(`${unit} cannot be converted to mL`, async () => {
    const [, volume] = await chart(channel(unit))
    assert.ok(volume.series[0].data.every((p: any) => p[1] === null))
    assert.doesNotMatch(volume.yAxis.name, /mL/)
  })
}

test('misaligned flags cannot validate a different sample', async () => {
  const data = channel()
  data.running[1].t = 59
  const [flow] = await chart(data)
  assert.equal(flow.series[0].data[1][1], null)
})

test('confirmed non-running samples have zero estimated transport', async () => {
  const data = channel()
  data.running.forEach(point => point.v = false)
  const [flow, volume] = await chart(data)
  assert.ok(flow.series[0].data.every((p: any) => p[1] === 0))
  assert.ok(volume.series[0].data.every((p: any) => p[1] === 0))
})
