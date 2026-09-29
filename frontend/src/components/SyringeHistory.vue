<template>
  <el-card v-if="Object.keys(series || {}).length" shadow="never">
    <template #header>注射泵位置 / 理论筒内体积（非实测输液量）</template>
    <div ref="chartEl" style="height: 320px; width: 100%" />
    <el-collapse>
      <el-collapse-item title="动作、故障及读取有效性记录">
        <pre>{{ JSON.stringify(series, null, 2) }}</pre>
      </el-collapse-item>
    </el-collapse>
  </el-card>
</template>
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { init, type ECharts } from '../lib/echarts'
interface Point { t: number; v: number | null }
const props = defineProps<{ series?: Record<string, { position?: Point[]; theoretical_volume_ul?: Point[]; states?: unknown[] }> }>()
const chartEl = ref<HTMLElement>()
let chart: ECharts | undefined
async function render() {
  await nextTick()
  if (!chartEl.value) return
  chart?.dispose(); chart = init(chartEl.value)
  const series = Object.entries(props.series || {}).flatMap(([id, data]) => [
    { name: id + ' 位置', type: 'line', showSymbol: false, connectNulls: false, yAxisIndex: 0, data: (data.position || []).map(p => [p.t, p.v]) },
    { name: id + ' 理论体积', type: 'line', showSymbol: false, connectNulls: false, yAxisIndex: 1, data: (data.theoretical_volume_ul || []).map(p => [p.t, p.v]) },
  ])
  chart.setOption({ tooltip: { trigger: 'axis' }, legend: {}, grid: { left: 60, right: 65, top: 55, bottom: 35 }, xAxis: { type: 'value', name: '秒' }, yAxis: [{ type: 'value', name: '步' }, { type: 'value', name: 'µL' }], series })
}
function resize() { chart?.resize() }
watch(() => props.series, render, { deep: true })
onMounted(() => { render(); window.addEventListener('resize', resize) })
onUnmounted(() => { chart?.dispose(); window.removeEventListener('resize', resize) })
</script>
<style scoped>pre { max-height: 350px; overflow: auto; white-space: pre-wrap; }</style>
