<template>
  <el-card v-if="Object.keys(series || {}).length" shadow="never">
    <template #header>注射泵位置 / 理论筒内体积（非实测输液量）</template>
    <p class="chart-note">位置与理论体积分开显示；两图可缩放时间范围。断线表示无有效读数。</p>
    <h4>柱塞位置 · 步</h4>
    <div ref="positionEl" class="syringe-chart" />
    <h4>理论筒内体积 · µL</h4>
    <div ref="volumeEl" class="syringe-chart" />
    <el-collapse v-model="expanded">
      <el-collapse-item name="states" title="动作、故障及读取有效性记录">
        <pre v-if="expanded.includes('states')">{{ JSON.stringify(Object.fromEntries(Object.entries(series || {}).map(([id, data]) => [id, data.states || []])), null, 2) }}</pre>
      </el-collapse-item>
    </el-collapse>
  </el-card>
</template>
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { init, type ECharts } from '../lib/echarts'
interface Point { t: number; v: number | null }
const props = defineProps<{ series?: Record<string, { position?: Point[]; theoretical_volume_ul?: Point[]; states?: unknown[] }> }>()
const positionEl = ref<HTMLElement>(), volumeEl = ref<HTMLElement>()
const expanded = ref<string[]>([])
let charts: ECharts[] = [], observer: ResizeObserver | undefined
async function render() {
  await nextTick()
  charts.forEach(chart => chart.dispose()); charts = []; observer?.disconnect()
  const ids = Object.keys(props.series || {}).sort()
  for (const [el, field, unit] of [[positionEl.value, 'position', '步'], [volumeEl.value, 'theoretical_volume_ul', 'µL']] as const) {
    if (!el) continue
    const chart = init(el); charts.push(chart); observer?.observe(el)
    chart.setOption({
      color: ['#2878d0', '#e58a32', '#728c45'],
      tooltip: { trigger: 'axis', confine: true, valueFormatter: (value: number | null) => value == null ? '无有效读数' : `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${unit}` },
      legend: { type: 'scroll', top: 0, bottom: 'auto', left: 'center' },
      grid: { left: 16, right: 24, top: 48, bottom: 88, containLabel: true },
      xAxis: { type: 'value', min: 0, name: '实验经过时间（分钟）', nameLocation: 'middle', nameGap: 28,
        axisLabel: { hideOverlap: true }, axisPointer: { label: { formatter: ({ value }: { value: number }) => `${Number(value).toFixed(2)} 分钟` } } },
      yAxis: { type: 'value', min: 0, axisLabel: { hideOverlap: true }, splitLine: { lineStyle: { color: '#edf1f5' } } },
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 8, height: 22, showDetail: false }],
      series: ids.map(id => ({ name: id === 'syringe_pump1' ? '注射泵 1' : id === 'syringe_pump2' ? '注射泵 2' : id,
        type: 'line', showSymbol: false, connectNulls: false, lineStyle: { width: 2 },
        data: (props.series?.[id]?.[field] || []).map(p => [p.t / 60, p.v]) })),
    })
  }
}
function resize() { charts.forEach(chart => chart.resize()) }
watch(() => props.series, render, { deep: true })
onMounted(() => { observer = new ResizeObserver(resize); void render(); window.addEventListener('resize', resize) })
onUnmounted(() => { observer?.disconnect(); charts.forEach(chart => chart.dispose()); window.removeEventListener('resize', resize) })
</script>
<style scoped>
pre { max-height: 350px; overflow: auto; white-space: pre-wrap; }
.syringe-chart { height: 290px; width: 100%; }
.chart-note { color: #607a91; font-size: 12px; line-height: 1.8; }
h4 { margin: 18px 0 12px; font-size: 14px; color: #294763; }
</style>
