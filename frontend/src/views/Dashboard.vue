<template>
  <div class="dashboard">
    <el-row :gutter="20">
      <el-col :span="12" v-for="(heater, id) in realtimeData?.heaters" :key="'h-'+id">
        <el-card shadow="hover" class="device-card">
          <template #header>
            <div class="card-header">
              <span class="device-title">加热器 {{ id }}</span>
              <el-tag :type="heater.error ? 'danger' : heater.run_status === 'RUNNING' ? 'success' : 'info'" size="small">
                {{ heater.error ? '异常' : heater.run_status }}
              </el-tag>
            </div>
          </template>
          <div class="heater-info">
            <div class="temp-block">
              <span class="temp-label">当前温度</span>
              <span class="temp-value">{{ heater.pv?.toFixed(1) ?? '--' }}°C</span>
            </div>
            <div class="temp-block">
              <span class="temp-label">设定温度</span>
              <span class="temp-value target">{{ heater.sv?.toFixed(1) ?? '--' }}°C</span>
            </div>
            <div class="temp-block">
              <span class="temp-label">输出功率</span>
              <span class="temp-value">{{ heater.mv ?? 0 }}%</span>
            </div>
          </div>
          <div v-if="heater.alarms?.length" class="alarms">
            <el-tag v-for="alarm in heater.alarms" :key="alarm" type="warning" size="small" style="margin: 2px">
              {{ alarm }}
            </el-tag>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12" v-for="(pump, id) in realtimeData?.pumps" :key="'p-'+id">
        <el-card shadow="hover" class="device-card">
          <template #header>
            <div class="card-header">
              <span class="device-title">蠕动泵 {{ id }}</span>
              <el-tag :type="pump.error ? 'danger' : 'success'" size="small">
                {{ pump.error ? '异常' : '在线' }}
              </el-tag>
            </div>
          </template>
          <div class="pump-channels">
            <div v-for="(ch, chId) in pump.channels" :key="chId" class="channel-row">
              <span class="channel-label">通道 {{ chId }}</span>
              <el-tag :type="ch.running ? 'success' : 'info'" size="small">
                {{ ch.running ? '运行中' : '停止' }}
              </el-tag>
              <span v-if="ch.running" class="channel-detail">
                {{ ch.flow_rate }} mL/min
              </span>
              <span v-if="ch.running && ch.direction" class="channel-detail">
                {{ ch.direction === 'CLOCKWISE' ? '顺时针' : '逆时针' }}
              </span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="hover" style="margin-top: 20px">
      <template #header>
        <div class="card-header">
          <span>实时温度曲线</span>
          <el-tag :type="wsConnected ? 'success' : 'danger'" size="small">
            {{ wsConnected ? '数据连接正常' : '数据连接断开' }}
          </el-tag>
        </div>
      </template>
      <div ref="chartRef" style="width: 100%; height: 400px"></div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import { useWebSocket, type RealtimeData } from '../composables/useWebSocket'

const { data: realtimeData, connected: wsConnected } = useWebSocket()
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
const maxPoints = 300

interface SeriesData {
  pv: [number, number][]
  sv: [number, number][]
}
const seriesDataMap: Record<string, SeriesData> = {}

onMounted(() => {
  if (chartRef.value) {
    chart = echarts.init(chartRef.value)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: [] },
      grid: { left: 60, right: 20, top: 40, bottom: 30 },
      xAxis: { type: 'time' },
      yAxis: { type: 'value', name: '温度(°C)' },
      series: [],
    })
  }
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  chart?.dispose()
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  chart?.resize()
}

watch(realtimeData, (newData: RealtimeData | null) => {
  if (!newData || !chart) return
  const now = Date.now()

  for (const [id, heater] of Object.entries(newData.heaters)) {
    if (heater.error) continue
    if (!seriesDataMap[id]) seriesDataMap[id] = { pv: [], sv: [] }
    seriesDataMap[id].pv.push([now, heater.pv])
    seriesDataMap[id].sv.push([now, heater.sv])
    seriesDataMap[id].pv = seriesDataMap[id].pv.slice(-maxPoints)
    seriesDataMap[id].sv = seriesDataMap[id].sv.slice(-maxPoints)
  }

  const series: echarts.SeriesOption[] = []
  const legendData: string[] = []
  for (const [id, s] of Object.entries(seriesDataMap)) {
    legendData.push(`${id} PV`, `${id} SV`)
    series.push(
      { name: `${id} PV`, type: 'line', data: s.pv, smooth: true, showSymbol: false },
      { name: `${id} SV`, type: 'line', data: s.sv, lineStyle: { type: 'dashed' }, showSymbol: false },
    )
  }

  chart.setOption({ legend: { data: legendData }, series })
})
</script>

<style scoped>
.dashboard { padding: 20px; }
.device-card { margin-bottom: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.device-title { font-weight: bold; font-size: 16px; }
.heater-info { display: flex; gap: 30px; justify-content: center; padding: 10px 0; }
.temp-block { display: flex; flex-direction: column; align-items: center; }
.temp-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.temp-value { font-size: 28px; font-weight: bold; color: #303133; }
.temp-value.target { color: #409eff; }
.alarms { margin-top: 8px; text-align: center; }
.pump-channels { padding: 5px 0; }
.channel-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
.channel-row:last-child { border-bottom: none; }
.channel-label { font-weight: 500; min-width: 60px; }
.channel-detail { color: #606266; font-size: 13px; }
</style>
