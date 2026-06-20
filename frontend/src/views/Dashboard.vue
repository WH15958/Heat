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
          <div class="alarms">
            <el-tag type="info" size="small">串口 {{ heater.connection_port ?? '--' }}</el-tag>
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
            <div class="channel-row">
              <span class="channel-label">串口</span>
              <el-tag type="info" size="small">{{ pump.connection_port ?? '--' }}</el-tag>
            </div>
            <div v-for="(ch, chId) in pump.channels" :key="chId" class="channel-row">
              <span class="channel-label">通道 {{ chId }}</span>
              <el-tag :type="ch.running ? 'success' : 'info'" size="small">
                {{ ch.running ? '运行中' : '停止' }}
              </el-tag>
              <span v-if="ch.running" class="channel-detail">
                {{ ch.flow_rate?.toFixed(1) ?? '0.0' }} {{ flowUnitLabel(ch.flow_unit) }}
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

      <el-col :span="12" v-for="(microwave, id) in dashboardMicrowaves" :key="'m-'+id">
        <el-card shadow="hover" class="device-card">
          <template #header>
            <div class="card-header">
              <span class="device-title">微波仪 {{ id }}</span>
              <el-tag :type="microwaveStatusType(microwave)" size="small">
                {{ microwaveStatusText(microwave) }}
              </el-tag>
            </div>
          </template>
          <div class="microwave-info">
            <div class="metric-block">
              <span class="metric-label">物料温度</span>
              <span class="metric-value">{{ formatNumber(microwave.material_temperature, 1, '°C') }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">功率</span>
              <span class="metric-value">{{ formatNumber(microwave.power_percent, 0, '%') }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">电流</span>
              <span class="metric-value">{{ formatNumber(microwave.current, 2, 'A') }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">运行时间</span>
              <span class="metric-value">{{ formatRuntime(microwave.runtime_seconds) }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">当前段</span>
              <span class="metric-value">{{ microwave.current_segment ?? '--' }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">当前模式</span>
              <span class="metric-value">{{ microwaveModeLabel(microwave.mode) }}</span>
            </div>
          </div>
          <div class="alarms">
            <el-tag :type="Number(microwave.fault_code || 0) ? 'danger' : 'info'" size="small">
              故障码 {{ microwave.fault_code ?? 0 }}
            </el-tag>
            <el-tag type="info" size="small" style="margin: 2px">
              串口 {{ microwave.connection_port ?? '--' }}
            </el-tag>
            <el-tag type="success" size="small" style="margin: 2px">
              配置写入可用
            </el-tag>
            <el-tag type="warning" size="small" style="margin: 2px">
              启动/停止可用
            </el-tag>
            <el-tag v-if="!microwave.connected" type="info" size="small" style="margin: 2px">未连接</el-tag>
            <el-tag v-if="microwave.error" type="danger" size="small" style="margin: 2px">读取失败</el-tag>
            <el-tag v-for="fault in microwave.faults || []" :key="fault" type="warning" size="small" style="margin: 2px">
              {{ fault }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>加热器实时温度曲线</span>
              <el-tag :type="wsConnected ? 'success' : 'danger'" size="small">
                {{ wsConnected ? '数据连接正常' : '数据连接断开' }}
              </el-tag>
            </div>
          </template>
          <div ref="heaterTempChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>微波合成仪物料温度曲线</span>
              <el-tag :type="wsConnected ? 'success' : 'danger'" size="small">
                {{ wsConnected ? '数据连接正常' : '数据连接断开' }}
              </el-tag>
            </div>
          </template>
          <div ref="microwaveTempChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="24">
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
import { computed, ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { init, type ECharts, type LineSeriesOption } from '../lib/echarts'
import { devicesApi } from '../api/devices'
import { useWebSocket, type MicrowaveRealtimeData, type RealtimeData } from '../composables/useWebSocket'

type TagType = 'success' | 'info' | 'danger'

const { data: realtimeData, connected: wsConnected } = useWebSocket()
const heaterTempChartRef = ref<HTMLElement>()
const microwaveTempChartRef = ref<HTMLElement>()
const flowChartRef = ref<HTMLElement>()
let heaterTempChart: ECharts | null = null
let microwaveTempChart: ECharts | null = null
let flowChart: ECharts | null = null
const maxPoints = 300

interface HeaterSeriesData {
  pv: [number, number][]
  sv: [number, number][]
}
const heaterDataMap: Record<string, HeaterSeriesData> = {}

interface MicrowaveSeriesData {
  temperature: [number, number][]
}
const microwaveDataMap: Record<string, MicrowaveSeriesData> = {}

interface PumpSeriesData {
  channels: Record<string, [number, number][]>
}
const pumpDataMap: Record<string, PumpSeriesData> = {}
const channelFlowUnitMap: Record<string, string> = {}

const channelColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c']

interface RegisteredMicrowaveStatus {
  connected: boolean
  status?: string
  connection_port?: string
  allow_experiment_control?: boolean
  allow_real_hardware_writes?: boolean
  enable_control_writes?: boolean
}

interface DashboardMicrowaveData extends MicrowaveRealtimeData {
  connected: boolean
  status?: string
}

const registeredMicrowaves = ref<Record<string, RegisteredMicrowaveStatus>>({})

const dashboardMicrowaves = computed<Record<string, DashboardMicrowaveData>>(() => {
  const merged: Record<string, DashboardMicrowaveData> = {}
  for (const [id, status] of Object.entries(registeredMicrowaves.value)) {
    merged[id] = {
      device_id: id,
      connected: Boolean(status.connected),
      status: status.status,
      connection_port: status.connection_port,
      allow_experiment_control: Boolean(status.allow_experiment_control),
      allow_real_hardware_writes: Boolean(status.allow_real_hardware_writes),
      enable_control_writes: Boolean(status.enable_control_writes),
    }
  }
  for (const [id, live] of Object.entries(realtimeData.value?.microwaves || {})) {
    const registered = registeredMicrowaves.value[id]
    merged[id] = {
      ...(merged[id] || {}),
      ...live,
      device_id: live.device_id || id,
      connected: registered?.connected ?? true,
      status: registered?.status ?? merged[id]?.status,
    }
  }
  return merged
})

const FLOW_UNIT_LABELS: Record<string, string> = {
  ML_MIN: 'mL/min',
  UL_MIN: 'uL/min',
  L_MIN: 'L/min',
  RPM: 'RPM',
}

function flowUnitLabel(unit: string | undefined): string {
  return FLOW_UNIT_LABELS[unit || 'ML_MIN'] || 'mL/min'
}

function microwaveModeLabel(mode: string | undefined): string {
  const labels: Record<string, string> = {
    manual_power: '手动功率',
    auto_power: '自动功率',
    constant_rate: '恒速率',
    unknown: '未知',
  }
  return labels[mode || 'unknown'] || mode || '--'
}

function formatNumber(value: number | null | undefined, digits: number, unit: string): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--'
  return `${value.toFixed(digits)}${unit}`
}

function formatRuntime(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || Number.isNaN(seconds)) return '--'
  const whole = Math.max(0, Math.floor(seconds))
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

function microwaveStatusType(microwave: DashboardMicrowaveData): TagType {
  if (!microwave.connected) return 'info'
  if (microwave.error) return 'danger'
  if (Number(microwave.fault_code || 0)) return 'danger'
  if (microwave.running) return 'success'
  return 'info'
}

function microwaveStatusText(microwave: DashboardMicrowaveData): string {
  if (!microwave.connected) return '离线'
  if (microwave.error) return '读取失败'
  if (Number(microwave.fault_code || 0)) return '异常'
  if (microwave.running) return '运行中'
  return '停止'
}

async function refreshRegisteredDevices() {
  try {
    const res = await devicesApi.list()
    registeredMicrowaves.value = res.data.microwaves || {}
  } catch (error) {
    console.error('[Dashboard] 设备状态读取失败:', error)
  }
}

let resizeObserver: ResizeObserver | null = null

function initCharts() {
  try {
    if (heaterTempChartRef.value) {
      if (heaterTempChart) heaterTempChart.dispose()
      heaterTempChart = init(heaterTempChartRef.value)
      heaterTempChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', name: '加热器温度(°C)' },
        series: [],
      })
    }
    if (microwaveTempChartRef.value) {
      if (microwaveTempChart) microwaveTempChart.dispose()
      microwaveTempChart = init(microwaveTempChartRef.value)
      microwaveTempChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', name: '微波物料温度(°C)' },
        series: [],
      })
    }
    if (flowChartRef.value) {
      if (flowChart) flowChart.dispose()
      flowChart = init(flowChartRef.value)
      flowChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'time' },
        yAxis: { type: 'value', name: '流量' },
        series: [],
      })
    }
  } catch (error) {
    console.error('[Dashboard] 图表初始化失败:', error)
  }
}

onMounted(async () => {
  await refreshRegisteredDevices()
  await nextTick()
  initCharts()

  resizeObserver = new ResizeObserver(() => {
    heaterTempChart?.resize()
    microwaveTempChart?.resize()
    flowChart?.resize()
  })
  if (heaterTempChartRef.value) resizeObserver.observe(heaterTempChartRef.value)
  if (microwaveTempChartRef.value) resizeObserver.observe(microwaveTempChartRef.value)
  if (flowChartRef.value) resizeObserver.observe(flowChartRef.value)

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  heaterTempChart?.dispose()
  microwaveTempChart?.dispose()
  flowChart?.dispose()
  heaterTempChart = null
  microwaveTempChart = null
  flowChart = null
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  heaterTempChart?.resize()
  microwaveTempChart?.resize()
  flowChart?.resize()
}

watch(realtimeData, (newData: RealtimeData | null) => {
  if (!newData) return
  const now = Date.now()

  const heaterKeys = Object.keys(newData.heaters || {})
  const pumpKeys = Object.keys(newData.pumps || {})
  const microwaveKeys = Object.keys(newData.microwaves || {})
  if (heaterKeys.length === 0 && pumpKeys.length === 0 && microwaveKeys.length === 0) return

  if (heaterTempChart) {
    for (const [id, heater] of Object.entries(newData.heaters || {})) {
      if (heater.error) continue
      if (typeof heater.pv !== 'number' || typeof heater.sv !== 'number') continue
      if (!heaterDataMap[id]) heaterDataMap[id] = { pv: [], sv: [] }
      heaterDataMap[id].pv.push([now, heater.pv])
      heaterDataMap[id].sv.push([now, heater.sv])
      heaterDataMap[id].pv = heaterDataMap[id].pv.slice(-maxPoints)
      heaterDataMap[id].sv = heaterDataMap[id].sv.slice(-maxPoints)
    }

    const heaterSeries: LineSeriesOption[] = []
    const heaterLegend: string[] = []
    for (const [id, s] of Object.entries(heaterDataMap)) {
      if (s.pv.length === 0) continue
      heaterLegend.push(`${id} PV`, `${id} SV`)
      heaterSeries.push(
        { name: `${id} PV`, type: 'line', data: s.pv, smooth: true, showSymbol: false },
        { name: `${id} SV`, type: 'line', data: s.sv, lineStyle: { type: 'dashed' }, showSymbol: false },
      )
    }
    if (heaterSeries.length > 0) {
      heaterTempChart.setOption(
        { legend: { data: heaterLegend }, series: heaterSeries },
        { replaceMerge: ['series'] }
      )
    }
  }

  if (microwaveTempChart) {
    for (const [id, microwave] of Object.entries(newData.microwaves || {})) {
      if (microwave.error) continue
      if (typeof microwave.material_temperature !== 'number') continue
      if (!microwaveDataMap[id]) microwaveDataMap[id] = { temperature: [] }
      microwaveDataMap[id].temperature.push([now, microwave.material_temperature])
      microwaveDataMap[id].temperature = microwaveDataMap[id].temperature.slice(-maxPoints)
    }

    const microwaveSeries: LineSeriesOption[] = []
    const microwaveLegend: string[] = []
    for (const [id, s] of Object.entries(microwaveDataMap)) {
      if (s.temperature.length === 0) continue
      const name = `${id} 物料温度`
      microwaveLegend.push(name)
      microwaveSeries.push({ name, type: 'line', data: s.temperature, smooth: true, showSymbol: false })
    }
    if (microwaveSeries.length > 0) {
      microwaveTempChart.setOption(
        { legend: { data: microwaveLegend }, series: microwaveSeries },
        { replaceMerge: ['series'] }
      )
    }
  }

  if (flowChart) {
    for (const [pumpId, pump] of Object.entries(newData.pumps || {})) {
      if (pump.error) continue
      if (!pump.channels) continue
      if (!pumpDataMap[pumpId]) pumpDataMap[pumpId] = { channels: {} }
      for (const [chId, chData] of Object.entries(pump.channels)) {
        if (!pumpDataMap[pumpId].channels[chId]) pumpDataMap[pumpId].channels[chId] = []
        const flowRate = chData.running ? chData.flow_rate : 0
        if (typeof flowRate !== 'number') continue
        pumpDataMap[pumpId].channels[chId].push([now, flowRate])
        pumpDataMap[pumpId].channels[chId] = pumpDataMap[pumpId].channels[chId].slice(-maxPoints)
        const unitKey = `${pumpId}_CH${chId}`
        if (chData.flow_unit) {
          channelFlowUnitMap[unitKey] = chData.flow_unit
        }
      }
    }

    const flowSeries: LineSeriesOption[] = []
    const flowLegend: string[] = []
    for (const [pumpId, pData] of Object.entries(pumpDataMap)) {
      for (const [chId, chSeries] of Object.entries(pData.channels)) {
        if (chSeries.length === 0) continue
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
    if (flowSeries.length > 0) {
      const units = new Set(Object.values(channelFlowUnitMap))
      const yAxisName = units.size === 1
        ? `流量(${flowUnitLabel([...units][0])})`
        : '流量'
      flowChart.setOption(
        { legend: { data: flowLegend }, yAxis: { name: yAxisName }, series: flowSeries },
        { replaceMerge: ['series'] }
      )
    }
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
.microwave-info {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 5px 0;
}
.metric-block {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 10px;
  min-width: 0;
}
.metric-label {
  display: block;
  color: #909399;
  font-size: 12px;
  margin-bottom: 4px;
}
.metric-value {
  display: block;
  color: #303133;
  font-weight: 600;
  font-size: 16px;
  word-break: break-word;
}
</style>
