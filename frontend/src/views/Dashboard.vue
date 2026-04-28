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
                {{ ch.flow_rate?.toFixed(1) ?? '0.0' }} mL/min
              </span>
              <span v-if="ch.running && ch.volume > 0" class="channel-detail">
                已泵 {{ ch.volume?.toFixed(1) ?? '0.0' }} mL
              </span>
              <span v-if="ch.running && ch.direction" class="channel-detail">
                {{ ch.direction === 'CLOCKWISE' ? '顺时针' : '逆时针' }}
              </span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>实时温度曲线</span>
              <el-tag :type="wsConnected ? 'success' : 'danger'" size="small">
                {{ wsConnected ? '数据连接正常' : '数据连接断开' }}
              </el-tag>
            </div>
          </template>
          <div ref="tempChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>实时流量曲线</span>
              <el-tag :type="wsConnected ? 'success' : 'danger'" size="small">
                {{ wsConnected ? '数据连接正常' : '数据连接断开' }}
              </el-tag>
            </div>
          </template>
          <div ref="flowChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { useWebSocket, type RealtimeData } from '../composables/useWebSocket'

const { data: realtimeData, connected: wsConnected } = useWebSocket()
const tempChartRef = ref<HTMLElement>()
const flowChartRef = ref<HTMLElement>()
let tempChart: echarts.ECharts | null = null
let flowChart: echarts.ECharts | null = null
const maxPoints = 300

interface HeaterSeriesData {
  pv: [number, number][]
  sv: [number, number][]
}
const heaterDataMap: Record<string, HeaterSeriesData> = {}

interface PumpSeriesData {
  channels: Record<string, [number, number][]>
}
const pumpDataMap: Record<string, PumpSeriesData> = {}

const channelColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c']

let resizeObserver: ResizeObserver | null = null

function initCharts() {
  try {
    if (tempChartRef.value) {
      if (tempChart) tempChart.dispose()
      tempChart = echarts.init(tempChartRef.value)
      tempChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', name: '温度(°C)' },
        series: [],
      })
    }
    if (flowChartRef.value) {
      if (flowChart) flowChart.dispose()
      flowChart = echarts.init(flowChartRef.value)
      flowChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', name: '流量(mL/min)' },
        series: [],
      })
    }
  } catch (error) {
    console.error('图表初始化失败:', error)
  }
}

onMounted(async () => {
  await nextTick()
  initCharts()

  resizeObserver = new ResizeObserver(() => {
    tempChart?.resize()
    flowChart?.resize()
  })
  if (tempChartRef.value) resizeObserver.observe(tempChartRef.value)
  if (flowChartRef.value) resizeObserver.observe(flowChartRef.value)

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  tempChart?.dispose()
  flowChart?.dispose()
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  tempChart?.resize()
  flowChart?.resize()
}

watch(realtimeData, (newData: RealtimeData | null) => {
  if (!newData) return
  const now = Date.now()

  if (tempChart) {
    for (const [id, heater] of Object.entries(newData.heaters)) {
      if (heater.error) continue
      if (!heaterDataMap[id]) heaterDataMap[id] = { pv: [], sv: [] }
      heaterDataMap[id].pv.push([now, heater.pv])
      heaterDataMap[id].sv.push([now, heater.sv])
      heaterDataMap[id].pv = heaterDataMap[id].pv.slice(-maxPoints)
      heaterDataMap[id].sv = heaterDataMap[id].sv.slice(-maxPoints)
    }

    const tempSeries: echarts.SeriesOption[] = []
    const tempLegend: string[] = []
    for (const [id, s] of Object.entries(heaterDataMap)) {
      tempLegend.push(`${id} PV`, `${id} SV`)
      tempSeries.push(
        { name: `${id} PV`, type: 'line', data: s.pv, smooth: true, showSymbol: false },
        { name: `${id} SV`, type: 'line', data: s.sv, lineStyle: { type: 'dashed' }, showSymbol: false },
      )
    }
    tempChart.setOption(
      { legend: { data: tempLegend }, series: tempSeries },
      { replaceMerge: ['series'] }
    )
  }

  if (flowChart) {
    for (const [pumpId, pump] of Object.entries(newData.pumps)) {
      if (pump.error) continue
      if (!pumpDataMap[pumpId]) pumpDataMap[pumpId] = { channels: {} }
      for (const [chId, chData] of Object.entries(pump.channels || {})) {
        if (!pumpDataMap[pumpId].channels[chId]) pumpDataMap[pumpId].channels[chId] = []
        const flowRate = chData.running ? chData.flow_rate : 0
        pumpDataMap[pumpId].channels[chId].push([now, flowRate])
        pumpDataMap[pumpId].channels[chId] = pumpDataMap[pumpId].channels[chId].slice(-maxPoints)
      }
    }

    const flowSeries: echarts.SeriesOption[] = []
    const flowLegend: string[] = []
    for (const [pumpId, pData] of Object.entries(pumpDataMap)) {
      for (const [chId, chSeries] of Object.entries(pData.channels)) {
        const name = `${pumpId} CH${chId}`
        flowLegend.push(name)
        const colorIdx = (parseInt(chId) - 1) % channelColors.length
        flowSeries.push({
          name,
          type: 'line',
          data: chSeries,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: channelColors[colorIdx] },
          itemStyle: { color: channelColors[colorIdx] },
          areaStyle: { opacity: 0.1 },
        })
      }
    }
    flowChart.setOption(
      { legend: { data: flowLegend }, series: flowSeries },
      { replaceMerge: ['series'] }
    )
  }
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
