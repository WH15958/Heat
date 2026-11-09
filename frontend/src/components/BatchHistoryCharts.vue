<template>
  <div class="batch-charts" aria-label="批次实际执行图表">
    <div class="chart-heading"><h4>执行概览</h4><span v-if="savedAt" class="saved-state" :title="`保存于 ${time(savedAt)}`">✓ 图表已保存</span></div>
    <p v-if="loading">正在加载批次图表…</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <p v-if="!loading && !models.length">暂无可绘制的正式组执行记录。</p>
    <template v-if="models.length">
      <details class="chart-notes"><summary>图表说明</summary><p>按实际执行日志绘制，不含预充及组间换瓶。耗时含暂停；缺失记录不补造，未结束步骤不计入阶段耗时。</p><p>温度横轴为每组开始后的分钟数，背景为执行阶段，虚线为反应目标。离散采样可能遗漏短暂峰值；超过 15 秒的记录间隔断线显示。</p><p v-if="savedAt">保存时间：{{ time(savedAt) }}</p></details>
      <h4>各组耗时分解</h4>
      <div ref="durationEl" class="duration-chart" :style="{height: `${Math.max(300, models.length * 55 + 140)}px`}" />
      <details class="chart-notes"><summary>各组起止时间</summary><div class="times"><div v-for="m in models" :key="m.runId">第 {{ m.index }} 组：{{ time(m.start) }} — {{ time(m.end) }} · {{ m.total === null ? '总时长未记录' : `${(m.total / 60).toFixed(2)} 分钟` }}</div></div></details>
      <h4>微波反应液温度</h4>
      <p>按组对比 · 拖动下方缩放条查看局部</p>
      <div v-for="m in models" :key="m.runId">
        <h5>第 {{ m.index }} 组 · {{ m.target === null ? '目标未记录' : `目标 ${m.target}℃` }}</h5>
        <p v-if="!m.temperature.some(s => s.points.some(p => p[1] !== null))">未保存有效微波温度采样。</p>
        <div v-else :ref="el => setTemperatureEl(m.runId, el)" class="temperature-chart" />
      </div>
    </template>
  </div>
</template>
<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { init, type ECharts } from '../lib/echarts'
import { type BatchChartRun, phaseNames, phaseColors } from '../experiment/batchCharts'
const props = defineProps<{ batchId: string; groups: { index: number; run_id?: string }[] }>()
const models = ref<BatchChartRun[]>([]), savedAt = ref('')
const loading = ref(false), error = ref(''), durationEl = ref<HTMLElement>()
const temperatureEls = new Map<string, HTMLElement>()
let charts: ECharts[] = [], sequence = 0, observer: ResizeObserver | undefined
const time = (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '未记录'
function setTemperatureEl(id: string, el: unknown) { if (el instanceof HTMLElement) temperatureEls.set(id, el); else temperatureEls.delete(id) }
function dispose() { observer?.disconnect(); charts.forEach(c => c.dispose()); charts = [] }
async function render() {
  await nextTick(); dispose()
  if (!durationEl.value || !models.value.length) return
  const chart = init(durationEl.value); charts.push(chart)
  chart.setOption({ color: phaseColors, tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => `${Number(v).toFixed(2)} 分钟` },
    legend: { type: 'scroll', top: 0 }, grid: { left: 80, right: 25, top: 65, bottom: 45 },
    xAxis: { type: 'value', name: '分钟' }, yAxis: { type: 'category', inverse: true, data: models.value.map(m => `第 ${m.index} 组`) },
    series: phaseNames.map((name, i) => ({ name, type: 'bar', stack: 'duration', data: models.value.map(m => m.phases[i]! / 60) })) })
  observer?.observe(durationEl.value)
  for (const m of models.value) {
    const el = temperatureEls.get(m.runId); if (!el) continue
    const c = init(el); charts.push(c); observer?.observe(el)
    c.setOption({ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 55, right: 25, top: 45, bottom: 65 },
      xAxis: { type: 'value', name: '分钟' }, yAxis: { type: 'value', name: '℃', scale: true }, dataZoom: [{ type: 'slider', bottom: 5 }, { type: 'inside' }],
      series: m.temperature.map((s, i) => ({ name: s.id + ' 实测温度', type: 'line', showSymbol: false, connectNulls: false, data: s.points,
        markLine: i === 0 && m.target !== null ? { symbol: 'none', data: [{ yAxis: m.target, name: '反应目标', label: { formatter: `目标 ${m.target}℃`, position: 'insideEndTop' } }] } : undefined,
        markArea: i === 0 ? { silent: true, label: { show: false }, data: m.intervals.map(p => [{ name: phaseNames[p.phase], xAxis: p.start, itemStyle: { color: phaseColors[p.phase], opacity: .12 } }, { xAxis: p.end }]) } : undefined })) })
  }
}
async function load() {
  const token = ++sequence; dispose(); models.value = []; error.value = ''; savedAt.value = ''; loading.value = true
  try {
    const { data } = await axios.get(`/api/guided/${encodeURIComponent(props.batchId)}/charts`)
    if (token !== sequence) return
    models.value = data.models
    savedAt.value = data.saved ? data.generated_at : ''
    if (data.missing.length) error.value = `第 ${data.missing.join('、')} 组日志缺失，图表尚未完整保存，请检查日志后重试。`
  } catch {
    if (token === sequence) error.value = '批次图表读取或保存失败，请刷新重试；旧版后台需重启加载图表功能。'
  } finally {
    if (token === sequence) { loading.value = false; await render() }
  }
}
watch(() => [props.batchId, props.groups], load, { deep: true })
onMounted(() => { observer = new ResizeObserver(() => charts.forEach(c => c.resize())); void load() })
onUnmounted(() => { sequence++; dispose() })
</script>
<style scoped>
.batch-charts{margin-top:24px;min-width:0}.batch-charts p,.times{font-size:13px;color:#607a91;line-height:1.8}.duration-chart,.temperature-chart{width:100%;min-width:0}.temperature-chart{height:300px}.times{overflow-wrap:anywhere}h5{font-size:14px;margin:20px 0 8px}
.chart-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.chart-heading h4{margin:0}.saved-state{font-size:12px;color:#357361}.chart-notes{margin:12px 0;color:#607a91;font-size:12px;line-height:1.8}.chart-notes summary{cursor:pointer}.batch-charts>h4{margin:24px 0 14px}.batch-charts{border-top:1px solid #e7edf3;padding-top:20px}
</style>
