<template>
  <div class="control-panel">
    <div class="emergency-bar">
      <div class="emergency-description"><strong>全局设备控制</strong><span>停止所有已注册设备</span></div>
      <el-button type="danger" size="large" @click="emergencyStop" class="emergency-button">
        紧急停止所有设备
      </el-button>
    </div>
    <div class="device-workspace">
      <nav class="device-selector" aria-label="选择控制设备">
        <div class="selector-heading">设备列表 <span>{{ controlDeviceEntries.length }} 台</span></div>
        <button v-for="item in controlDevices" :key="item.key" type="button" class="device-choice" :class="{ selected: selectedDevice === item.key }" :aria-pressed="selectedDevice === item.key" @click="selectedDevice = item.key">
          <span class="choice-heading"><strong>{{ item.name }}</strong><span class="connection-dot" :class="{ online: item.connected }" /></span>
          <span class="choice-meta">{{ item.summary }}</span>
        </button>
        <el-empty v-if="!controlDevices.length" description="暂无设备" :image-size="48" />
      </nav>
      <div class="device-detail">
        <section v-if="Object.keys(devices.heaters).length" v-show="selectedDevice === 'heater'" aria-label="加热器设备">
          <HeaterControl
            v-for="(heater, id) in devices.heaters"
            :key="'h-' + id"
            :heater-id="id"
            :heater="heater"
            @connect="connectHeater"
            @disconnect="disconnectHeater"
            @set-temp="setTemp"
            @start="startHeater"
            @stop="stopHeater"
          />
        </section>
        <MicrowaveControl
          v-for="(microwave, microwaveId) in devices.microwaves"
          v-show="selectedDevice === 'microwave'"
          :key="'m-' + microwaveId"
          :microwave-id="microwaveId"
          :microwave="microwave"
          :realtime="microwaveStatus(microwaveId)"
          :host-program="microwavePrograms[microwaveId]"
          @recover="recoverMicrowaveProgram"
          @connect="connectMicrowave"
          @disconnect="disconnectMicrowave"
          @refresh="readMicrowaveData"
          @configure="configureMicrowave"
          @start="startMicrowave"
          @stop="stopMicrowave"
        />
        <PumpControl
          v-for="(pump, pumpId) in devices.pumps"
          v-show="selectedDevice === 'pump'"
          :key="'p-' + pumpId"
          :pump-id="pumpId"
          :pump="pump"
          :channel-status="channelStatus"
          @connect="connectPump"
          @disconnect="disconnectPump"
          @start-channel="startPumpChannel"
          @stop-channel="stopPumpChannel"
          @stop-all="stopPumpAll"
        />
        <section v-show="selectedDevice === 'valve'" aria-label="三通阀设备">
          <ValveControl v-for="(valve, id) in valves" :key="id" :valve-id="id" :state="valve" @update="updateValve" />
        </section>
        <div v-show="selectedDevice === 'syringe'">
          <SyringePumpGroup @devices="syringeDevices = $event" />
        </div>
        <el-empty v-if="!controlDevices.length" description="暂无可控制设备" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { devicesApi, FLOW_UNITS, PUMP_MODES, TUBE_MODELS, type MicrowaveMode, type PumpMode } from '../api/devices'
import { hostedMicrowavePayload, microwaveProgramPayload, microwaveProgramKey, microwaveProgramConfigured, type MicrowaveProgram, type MicrowaveSegmentConfig } from '../utils/microwaveProgram'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket, type MicrowaveRealtimeData } from '../composables/useWebSocket'
import ValveControl from '../components/ValveControl.vue'
import type { ValveState } from '../api/devices'
import HeaterControl from '../components/HeaterControl.vue'
import PumpControl from '../components/PumpControl.vue'
import MicrowaveControl from '../components/MicrowaveControl.vue'
import SyringePumpGroup from '../components/SyringePumpGroup.vue'
import type { SyringeState } from '../api/syringePumps'
import { normalizeTubeSegmentLengths } from '../utils/pumpCalculations'

const valves = reactive<Record<string, ValveState>>({})
function updateValve(id: string, state: ValveState) { valves[id] = state }

const STORAGE_KEY = 'heat_control_params'

const { data: realtimeData, connected: wsConnected } = useWebSocket()
watch(realtimeData, payload => {
  for (const [id, state] of Object.entries(payload?.valves || {})) {
    if (valves[id]) valves[id] = { ...valves[id], ...state }
  }
})
watch(wsConnected, online => {
  if (!online) for (const state of Object.values(valves)) {
    state.read_ok = false
    state.relay_energized = null
  }
})

interface ChannelConfig {
  flowRate: number
  direction: string
  mode: PumpMode
  runTime: number
  timeUnit: number
  dispenseVolume: number
  volumeUnit: number
  repeatCount: number
  intervalTime: number
  intervalTimeUnit: number
  tubeModel: number
  maxFlowRate: number
  flowUnit: number
  tubeSegmentLengthsCm: Array<number | null>
  starting: boolean
  stopping: boolean
}

interface PumpDeviceState {
  connected: boolean
  loading: boolean
  connectionError?: string | null
  connectionPort?: string
  bindingMode?: string
  bindingLabel?: string
  bindingResolved?: boolean
  bindingError?: string | null
  stoppingAll: boolean
  channels: Record<number, ChannelConfig>
}

interface HeaterDeviceState {
  connected: boolean
  disconnectFailed: boolean
  loading: boolean
  connectionError?: string | null
  connectionPort?: string
  bindingMode?: string
  bindingLabel?: string
  bindingResolved?: boolean
  bindingError?: string | null
  targetTemp: number
  starting: boolean
  stopping: boolean
}

interface MicrowaveDeviceState extends MicrowaveProgram {
  programRevision: number
  programRequestId: string
  connected: boolean
  loading: boolean
  connectionError?: string | null
  refreshing: boolean
  configuring: boolean
  starting: boolean
  stopping: boolean
  mode: MicrowaveMode
  connectionPort?: string
  bindingMode?: string
  bindingLabel?: string
  bindingResolved?: boolean
  bindingError?: string | null
  allowExperimentControl: boolean
  allowRealHardwareWrites: boolean
  enableControlWrites: boolean
  segments: Record<number, MicrowaveSegmentConfig>
}

const devices = reactive<{
  heaters: Record<string, HeaterDeviceState>
  pumps: Record<string, PumpDeviceState>
  microwaves: Record<string, MicrowaveDeviceState>
}>({
  heaters: {},
  pumps: {},
  microwaves: {},
})

const microwaveSnapshots = reactive<Record<string, MicrowaveRealtimeData>>({})
const microwavePrograms = reactive<Record<string, any>>({})
watch(() => Object.entries(devices.microwaves).map(([id, device]) =>
  [id, JSON.stringify([microwaveProgramKey(device), device.connected, device.connectionPort])] as const),
  (current, previous) => {
    const old = new Map(previous)
    for (const [id, key] of current) {
      if (old.get(id) !== key) {
        devices.microwaves[id]!.configuredProgramKey = ''
        devices.microwaves[id]!.programRequestId = ''
        devices.microwaves[id]!.programRevision++
      }
    }
  }, { flush: 'sync' })
const selectedDevice = ref('')
let initialSelectionReady = false
const syringeDevices = ref<Record<string, SyringeState>>({})
const controlDeviceEntries = computed(() => [
  ...Object.entries(valves).map(([id, device]) => ({ key: `valve:${id}`, name: '三通阀', port: device.connection_port, connected: device.connected, status: !device.connected ? '未连接' : device.read_ok ? '已连接' : '状态未知' })),
  ...Object.entries(devices.heaters).map(([id, device], index) => ({ key: `heater:${id}`, name: `加热器${index + 1}`, port: device.connectionPort, connected: device.connected, status: device.disconnectFailed ? '连接异常' : device.connected ? '已连接' : '未连接' })),
  ...Object.entries(devices.pumps).map(([id, device], index) => ({ key: `pump:${id}`, name: `蠕动泵${index + 1}`, port: device.connectionPort, connected: device.connected, status: device.connected ? '已连接' : '未连接' })),
  ...Object.entries(devices.microwaves).map(([id, device], index) => ({ key: `microwave:${id}`, name: `微波仪${index + 1}`, port: device.connectionPort, connected: device.connected, status: device.connected ? '已连接' : '未连接' })),
  ...Object.entries(syringeDevices.value).map(([id, device]) => ({ key: `syringe:${id}`, name: device.name, port: device.connection_port, connected: device.connected, status: !device.configured ? '待配置' : !device.connected ? '未连接' : !device.read_ok ? '状态未知' : device.fault_code ? '故障' : device.busy ? '运行中' : '已连接' })),
])
const controlDevices = computed(() => [
  { key: 'heater', name: '加热器' },
  { key: 'pump', name: '蠕动泵' },
  { key: 'microwave', name: '微波仪' },
  { key: 'syringe', name: '注射泵' },
  { key: 'valve', name: '三通阀' },
].map(group => {
  const members = controlDeviceEntries.value.filter(device => device.key.startsWith(group.key + ':'))
  const connectedCount = members.filter(device => device.connected).length
  const attention = [...new Set(members.map(device => device.status).filter(status => ['待配置', '连接异常', '故障', '状态未知', '运行中'].includes(status)))]
  return { ...group, count: members.length, connected: connectedCount > 0,
    summary: `${members.length} 台 · 已连接 ${connectedCount}/${members.length}${attention.length ? ' · ' + attention.join('、') : ''}` }
}).filter(group => group.count > 0))
watch(controlDevices, items => {
  if (!initialSelectionReady) return
  if (!items.some(item => item.key === selectedDevice.value)) selectedDevice.value = items[0]?.key || ''
})

function channelStatus(pumpId: string, ch: number) {
  const pumpData = realtimeData.value?.pumps?.[pumpId]
  if (!pumpData || pumpData.error) return null
  return pumpData.channels?.[String(ch)] || null
}

function createPumpChannels(): Record<number, ChannelConfig> {
  const channels: Record<number, ChannelConfig> = {}
  for (let i = 1; i <= 4; i++) {
    channels[i] = { flowRate: 10.0, direction: 'CW', mode: 'FLOW_MODE', runTime: 60, timeUnit: 0, dispenseVolume: 10.0, volumeUnit: 1, repeatCount: 1, intervalTime: 0, intervalTimeUnit: 0, tubeModel: 11, maxFlowRate: 22.0, flowUnit: 1, tubeSegmentLengthsCm: [null], starting: false, stopping: false }
  }
  return channels
}

function createMicrowaveSegments(): Record<number, MicrowaveSegmentConfig> {
  const segments: Record<number, MicrowaveSegmentConfig> = {}
  for (let i = 1; i <= 5; i++) {
    segments[i] = { segment: i, temperature: 25.0, powerPercent: 0, hours: 0, minutes: 1, seconds: 0 }
  }
  return segments
}

function isPumpMode(value: unknown): value is PumpMode {
  return value === 'FLOW_MODE' || value === 'TIME_QUANTITY' || value === 'TIME_SPEED' || value === 'QUANTITY_SPEED'
}

function isPumpDirection(value: unknown): value is 'CW' | 'CCW' {
  return value === 'CW' || value === 'CCW'
}

function isFlowUnit(value: unknown): value is number {
  return value === 0 || value === 1 || value === 2 || value === 3
}

function isTimeUnit(value: unknown): value is number {
  return value === 0 || value === 1 || value === 2
}

function isVolumeUnit(value: unknown): value is number {
  return value === 0 || value === 1 || value === 2
}

function isTubeModel(value: unknown): value is number {
  return typeof value === 'number' && TUBE_MODELS.some(model => model.value === value)
}

function isPositiveFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

function configuredChannelFlowRateMax(
  channel: ChannelConfig,
  flowUnit = channel.flowUnit,
): number {
  if (flowUnit === 3) return 150
  const tube = TUBE_MODELS.find(model => model.value === channel.tubeModel)
  const tubeMaxFlowRate = tube ? tube.maxFlow : channel.maxFlowRate
  const maxMlMin = Math.min(channel.maxFlowRate, tubeMaxFlowRate)
  const convertedMax = flowUnit === 0
    ? maxMlMin * 1000
    : flowUnit === 2
      ? maxMlMin / 1000
      : maxMlMin
  return Math.min(convertedMax, 9999)
}

function normalizeChannelFlow(channel: ChannelConfig) {
  if (
    channel.flowUnit !== 3
    && configuredChannelFlowRateMax(channel) < 0.01
  ) {
    channel.flowUnit = [1, 0, 2].find(
      unit => configuredChannelFlowRateMax(channel, unit) >= 0.01,
    ) ?? 3
  }
  const flowRate = Number.isFinite(channel.flowRate) ? channel.flowRate : 0.01
  channel.flowRate = Math.min(
    Math.max(flowRate, 0.01),
    configuredChannelFlowRateMax(channel),
  )
}

function saveParams() {
  const params: Record<string, any> = {}
  for (const [pumpId, pump] of Object.entries(devices.pumps)) {
    params[pumpId] = {}
    for (const [ch, cfg] of Object.entries(pump.channels)) {
      params[pumpId][ch] = {
        flowRate: cfg.flowRate,
        direction: cfg.direction,
        mode: cfg.mode,
        runTime: cfg.runTime,
        timeUnit: cfg.timeUnit,
        dispenseVolume: cfg.dispenseVolume,
        volumeUnit: cfg.volumeUnit,
        repeatCount: cfg.repeatCount,
        intervalTime: cfg.intervalTime,
        intervalTimeUnit: cfg.intervalTimeUnit,
        tubeModel: cfg.tubeModel,
        flowUnit: cfg.flowUnit,
        tubeSegmentLengthsCm: cfg.tubeSegmentLengthsCm,
      }
    }
  }
  for (const [heaterId, heater] of Object.entries(devices.heaters)) {
    params[heaterId] = { targetTemp: heater.targetTemp }
  }
  params.microwaves = {}
  for (const [microwaveId, microwave] of Object.entries(devices.microwaves)) {
    params.microwaves[microwaveId] = {
      mode: microwave.mode,
      segments: microwave.segments,
    }
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(params))
}

function restoreParams() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const params = JSON.parse(raw)
    for (const [pumpId, pump] of Object.entries(params)) {
      if (!devices.pumps[pumpId]) continue
      for (const [ch, cfg] of Object.entries(pump as Record<string, any>)) {
        const channel = devices.pumps[pumpId].channels[Number(ch)]
        if (!channel) continue
        if (cfg.flowRate !== undefined) channel.flowRate = cfg.flowRate
        if (isPumpDirection(cfg.direction)) channel.direction = cfg.direction
        if (isPumpMode(cfg.mode)) channel.mode = cfg.mode
        if (cfg.runTime !== undefined) channel.runTime = cfg.runTime
        if (isTimeUnit(cfg.timeUnit)) channel.timeUnit = cfg.timeUnit
        if (cfg.dispenseVolume !== undefined) channel.dispenseVolume = cfg.dispenseVolume
        if (isVolumeUnit(cfg.volumeUnit)) channel.volumeUnit = cfg.volumeUnit
        if (cfg.repeatCount !== undefined) channel.repeatCount = cfg.repeatCount
        if (cfg.intervalTime !== undefined) channel.intervalTime = cfg.intervalTime
        if (isTimeUnit(cfg.intervalTimeUnit)) channel.intervalTimeUnit = cfg.intervalTimeUnit
        if (isTubeModel(cfg.tubeModel)) {
          channel.tubeModel = cfg.tubeModel
        }
        if (isFlowUnit(cfg.flowUnit)) channel.flowUnit = cfg.flowUnit
        if (cfg.tubeSegmentLengthsCm !== undefined) {
          channel.tubeSegmentLengthsCm = normalizeTubeSegmentLengths(cfg.tubeSegmentLengthsCm)
        }
        normalizeChannelFlow(channel)
      }
    }
    for (const [heaterId, heater] of Object.entries(params)) {
      if (!devices.heaters[heaterId]) continue
      const cfg = heater as any
      if (cfg.targetTemp !== undefined) devices.heaters[heaterId].targetTemp = cfg.targetTemp
    }
    const microwaveParams = params.microwaves || {}
    for (const [microwaveId, cfg] of Object.entries(microwaveParams as Record<string, any>)) {
      if (!devices.microwaves[microwaveId]) continue
      if (cfg.mode === 'auto_power' || cfg.mode === 'manual_power') devices.microwaves[microwaveId].mode = cfg.mode
      for (const [segmentId, segmentCfg] of Object.entries(cfg.segments || {})) {
        const segment = devices.microwaves[microwaveId].segments[Number(segmentId)]
        if (!segment) continue
        const saved = segmentCfg as any
        if (saved.temperature !== undefined) segment.temperature = saved.temperature
        if (saved.powerPercent !== undefined) segment.powerPercent = saved.powerPercent
        if (saved.hours !== undefined) segment.hours = saved.hours
        if (saved.minutes !== undefined) segment.minutes = saved.minutes
        if (saved.seconds !== undefined) segment.seconds = saved.seconds
      }
    }
  } catch {
    // ignore parse errors
  }
}

let paramsRestored = false

watch(devices, () => {
  if (paramsRestored) saveParams()
}, { deep: true })

function hasUnresolvedBinding(data: any): boolean {
  const groups = [data?.heaters || {}, data?.pumps || {}, data?.microwaves || {}]
  return groups.some(group =>
    Object.values(group).some((info: any) => info?.binding_resolved === false),
  )
}

function applyDeviceData(data: any) {
  for (const id of Object.keys(valves)) if (!data.valves?.[id]) delete valves[id]
  Object.assign(valves, data.valves || {})
  for (const [id, info] of Object.entries(data.heaters || {})) {
    if (!devices.heaters[id]) {
      devices.heaters[id] = { connected: false, disconnectFailed: false, loading: false, targetTemp: 25.0, starting: false, stopping: false, bindingResolved: true }
    }
    devices.heaters[id].connected = (info as any).connected
    if (!devices.heaters[id].connected) {
      devices.heaters[id].disconnectFailed = false
    }
    if (devices.heaters[id].connected) devices.heaters[id].connectionError = null
    devices.heaters[id].connectionPort = (info as any).connection_port
    devices.heaters[id].bindingMode = (info as any).connection_binding_mode
    devices.heaters[id].bindingLabel = (info as any).binding_label
    devices.heaters[id].bindingResolved = (info as any).binding_resolved !== false
    devices.heaters[id].bindingError = (info as any).binding_error ?? null
  }
  for (const [id, info] of Object.entries(data.pumps || {})) {
    const isNewPump = !devices.pumps[id]
    if (isNewPump) {
      devices.pumps[id] = { connected: false, loading: false, stoppingAll: false, channels: createPumpChannels(), bindingResolved: true }
    }
    const pumpInfo = info as any
    devices.pumps[id].connected = pumpInfo.connected
    devices.pumps[id].connectionError = pumpInfo.connection_error || null
    devices.pumps[id].connectionPort = pumpInfo.connection_port
    devices.pumps[id].bindingMode = pumpInfo.connection_binding_mode
    devices.pumps[id].bindingLabel = pumpInfo.binding_label
    devices.pumps[id].bindingResolved = pumpInfo.binding_resolved !== false
    devices.pumps[id].bindingError = pumpInfo.binding_error ?? null
    for (const [channelId, configuredChannel] of Object.entries(pumpInfo.channels || {})) {
      const channel = devices.pumps[id].channels[Number(channelId)]
      if (!channel) continue
      const channelInfo = configuredChannel as any
      if (isNewPump && isTubeModel(channelInfo.tube_model)) {
        channel.tubeModel = channelInfo.tube_model
      }
      if (isPositiveFiniteNumber(channelInfo.max_flow_rate)) {
        channel.maxFlowRate = channelInfo.max_flow_rate
      }
      normalizeChannelFlow(channel)
    }
  }
  for (const [id, info] of Object.entries(data.microwaves || {})) {
    if (!devices.microwaves[id]) {
      devices.microwaves[id] = {
        connected: false,
        loading: false,
        refreshing: false,
        configuring: false,
        starting: false,
        stopping: false,
        mode: 'auto_power',
        usedSegments: 1,
        configuredProgramKey: '',
        programRevision: 0,
        programRequestId: '',
        connectionPort: undefined,
        bindingMode: undefined,
        bindingLabel: undefined,
        bindingResolved: true,
        bindingError: null,
        allowExperimentControl: false,
        allowRealHardwareWrites: false,
        enableControlWrites: false,
        segments: createMicrowaveSegments(),
      }
    }
    devices.microwaves[id].connected = (info as any).connected
    if (devices.microwaves[id].connected) devices.microwaves[id].connectionError = null
    devices.microwaves[id].connectionPort = (info as any).connection_port
    devices.microwaves[id].bindingMode = (info as any).connection_binding_mode
    devices.microwaves[id].bindingLabel = (info as any).binding_label
    devices.microwaves[id].bindingResolved = (info as any).binding_resolved !== false
    devices.microwaves[id].bindingError = (info as any).binding_error ?? null
    devices.microwaves[id].allowExperimentControl = Boolean((info as any).allow_experiment_control)
    devices.microwaves[id].allowRealHardwareWrites = Boolean((info as any).allow_real_hardware_writes)
    devices.microwaves[id].enableControlWrites = Boolean((info as any).enable_control_writes)
  }
}

async function refreshDevices(refreshUnresolvedBindings = true) {
  try {
    const res = await devicesApi.list()
    const data = res.data
    applyDeviceData(data)
    if (!initialSelectionReady) {
      selectedDevice.value = controlDevices.value[0]?.key || ''
      initialSelectionReady = true
    }
    if (!paramsRestored) {
      restoreParams()
      paramsRestored = true
    }
    if (refreshUnresolvedBindings && hasUnresolvedBinding(data)) {
      const refreshed = await devicesApi.refreshBindings()
      applyDeviceData(refreshed.data)
    }
  } catch (e) {
    console.error('Failed to refresh devices:', e)
  }
}

let programTimer: ReturnType<typeof setInterval> | undefined
let readingPrograms = false
async function refreshMicrowavePrograms() {
  if (readingPrograms) return
  readingPrograms = true
  try {
    for (const id of Object.keys(devices.microwaves)) {
      try { microwavePrograms[id] = (await devicesApi.currentMicrowaveProgram(id)).data }
      catch { microwavePrograms[id] = { ...microwavePrograms[id], status_error: '托管状态读取失败，请刷新后核对' } }
    }
  } finally { readingPrograms = false }
}
onMounted(async () => {
  await refreshDevices()
  await refreshMicrowavePrograms()
  programTimer = setInterval(() => { void refreshMicrowavePrograms() }, 1000)
})
onUnmounted(() => { if (programTimer) clearInterval(programTimer) })

function heaterConnectionPort(id: string): string {
  return realtimeData.value?.heaters?.[id]?.connection_port ?? devices.heaters[id]?.connectionPort ?? '--'
}

function pumpConnectionPort(id: string): string {
  return realtimeData.value?.pumps?.[id]?.connection_port ?? devices.pumps[id]?.connectionPort ?? '--'
}

function ensureConnected(connected: boolean, label: string, port: string): boolean {
  if (connected) return true
  ElMessage.error(label + ' 未连接。请先确认设备绑定身份与当前解析端口 ' + port + ' 一致，并连接成功。')
  return false
}

function ensureBindingResolved(resolved: boolean | undefined, label: string, bindingLabel: string | undefined): boolean {
  if (resolved !== false) return true
  ElMessage.error(label + ' 串口绑定未解析。请先确认绑定身份 ' + (bindingLabel || '--') + ' 与当前设备一致。')
  return false
}

async function confirmHeaterOperation(id: string, action: string, detail: string): Promise<boolean> {
  try {
    await ElMessageBox.confirm(
      '即将' + action + '加热器 ' + id + '（串口 ' + heaterConnectionPort(id) + '）。\n' +
      detail + '\n' +
      '请确认温度探头、加热对象、接线和现场看护都已检查完毕。',
      '加热器 ' + id + ' 操作前检查',
      {
        confirmButtonText: '已检查，继续',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    return true
  } catch {
    return false
  }
}

function pumpModeLabel(mode: PumpMode): string {
  return PUMP_MODES.find(m => m.value === mode)?.label || mode
}

function tubeModelLabel(tubeModel: number): string {
  return TUBE_MODELS.find(t => t.value === tubeModel)?.label || String(tubeModel)
}

function directionLabel(direction: string): string {
  return direction === 'CCW' ? '逆时针' : '顺时针'
}

function flowUnitLabel(unit: number): string {
  return FLOW_UNITS.find(item => item.value === unit)?.label || '未知单位'
}

async function confirmPumpStart(pumpId: string, channel: number, effectiveFlowRate: number): Promise<boolean> {
  const ch = devices.pumps[pumpId].channels[channel]
  const effectiveFlowUnit = ch.mode === 'TIME_QUANTITY' ? 1 : ch.flowUnit
  try {
    await ElMessageBox.confirm(
      '即将启动蠕动泵 ' + pumpId + '（串口 ' + pumpConnectionPort(pumpId) + '）通道 ' + channel + '。\n' +
      '模式：' + pumpModeLabel(ch.mode) + '；方向：' + directionLabel(ch.direction) + '；软管：' + tubeModelLabel(ch.tubeModel) + '；流量：' + effectiveFlowRate.toFixed(3) + ' ' + flowUnitLabel(effectiveFlowUnit) + '。\n' +
      '请确认管路、夹管、入口/出口、废液或收集容器、流向和现场看护都已检查完毕。',
      '蠕动泵 ' + pumpId + ' 通道 ' + channel + ' 启动前检查',
      {
        confirmButtonText: '已检查，启动',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    return true
  } catch {
    return false
  }
}

async function connectHeater(id: string) {
  if (!ensureBindingResolved(devices.heaters[id].bindingResolved, '加热器' + id, devices.heaters[id].bindingLabel)) return
  devices.heaters[id].connectionError = null
  devices.heaters[id].loading = true
  try {
    const res = await devicesApi.connectHeater(id)
    if (!res.data.success) {
      const message = '连接失败: 加热器设备返回失败'
      devices.heaters[id].connectionError = message
      ElMessage.error(message)
      return
    }
    devices.heaters[id].connected = true
    devices.heaters[id].disconnectFailed = false
    ElMessage.success(`加热器 ${id} 已连接`)
  } catch (e: any) {
    const message = `连接失败: ${e.response?.data?.detail || e.message}`
    devices.heaters[id].connectionError = message
    ElMessage.error(message)
  } finally {
    devices.heaters[id].loading = false
  }
}

async function disconnectHeater(id: string) {
  devices.heaters[id].loading = true
  const progressMessage = ElMessage({
    message: `正在安全停止并断开加热器 ${id}...`,
    type: 'info',
    duration: 0,
  })
  try {
    const res = await devicesApi.disconnectHeater(id)
    if (!res.data.success) {
      devices.heaters[id].disconnectFailed = true
      ElMessage.error('断开失败: 加热器设备返回失败')
      return
    }
    devices.heaters[id].connected = false
    devices.heaters[id].disconnectFailed = false
    ElMessage.info(`加热器 ${id} 已断开`)
  } catch (e: any) {
    devices.heaters[id].disconnectFailed = true
    ElMessage.error(`断开失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    progressMessage.close()
    devices.heaters[id].loading = false
  }
}

async function setTemp(id: string, temp: number) {
  const heater = devices.heaters[id]
  if (!ensureConnected(heater.connected, '加热器 ' + id, heaterConnectionPort(id))) return
  if (!await confirmHeaterOperation(id, '设置目标温度', '目标温度：' + temp + '°C。')) return
  try {
    const res = await devicesApi.setTemperature(id, temp)
    if (!res.data.success) {
      ElMessage.error('设置失败: 加热器设备返回失败')
      return
    }
    ElMessage.success(`温度已设为 ${temp}°C`)
  } catch (e: any) {
    ElMessage.error(`设置失败: ${e.response?.data?.detail || e.message}`)
  }
}

async function startHeater(id: string) {
  const heater = devices.heaters[id]
  if (!ensureConnected(heater.connected, '加热器 ' + id, heaterConnectionPort(id))) return
  if (!await confirmHeaterOperation(id, '启动', '目标温度：' + heater.targetTemp + '°C。')) return
  heater.starting = true
  try {
    const res = await devicesApi.startHeater(id)
    if (!res.data.success) {
      ElMessage.error('启动失败: 加热器设备返回失败')
      return
    }
    ElMessage.success(`加热器 ${id} 已启动`)
  } catch (e: any) {
    ElMessage.error(`启动失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    heater.starting = false
  }
}

async function stopHeater(id: string) {
  const heater = devices.heaters[id]
  if (!ensureConnected(heater.connected, '加热器 ' + id, heaterConnectionPort(id))) return
  heater.stopping = true
  try {
    const res = await devicesApi.stopHeater(id)
    if (!res.data.success) {
      ElMessage.error('停止失败: 加热器设备返回失败')
      return
    }
    ElMessage.info(`加热器 ${id} 已停止`)
  } catch (e: any) {
    ElMessage.error(`停止失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    heater.stopping = false
  }
}

async function connectPump(id: string) {
  if (!ensureBindingResolved(devices.pumps[id].bindingResolved, '蠕动泵' + id, devices.pumps[id].bindingLabel)) return
  devices.pumps[id].connectionError = null
  devices.pumps[id].loading = true
  try {
    const res = await devicesApi.connectPump(id)
    if (!res.data.success) {
      const message = '连接失败: 蠕动泵设备返回失败'
      devices.pumps[id].connectionError = message
      ElMessage.error(message)
      return
    }
    devices.pumps[id].connected = true
    ElMessage.success(`蠕动泵 ${id} 已连接`)
  } catch (e: any) {
    const message = `连接失败: ${e.response?.data?.detail || e.message}`
    devices.pumps[id].connectionError = message
    ElMessage.error(message)
  } finally {
    devices.pumps[id].loading = false
  }
}

async function disconnectPump(id: string) {
  devices.pumps[id].loading = true
  try {
    const res = await devicesApi.disconnectPump(id)
    if (!res.data.success) {
      ElMessage.error('断开失败: 蠕动泵设备返回失败')
      return
    }
    devices.pumps[id].connected = false
    ElMessage.info(`蠕动泵 ${id} 已断开`)
  } catch (e: any) {
    ElMessage.error(`断开失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.pumps[id].loading = false
  }
}

async function startPumpChannel(pumpId: string, channel: number) {
  const pump = devices.pumps[pumpId]
  if (!ensureConnected(pump.connected, '蠕动泵 ' + pumpId, pumpConnectionPort(pumpId))) return
  const ch = devices.pumps[pumpId].channels[channel]

  if (ch.mode !== 'FLOW_MODE') {
    if (ch.repeatCount < 0 || ch.repeatCount > 9999) {
      ElMessage.error(`通道 ${channel}: 重复次数范围 0-9999，0 表示无限`)
      return
    }
    if (ch.repeatCount !== 1 && ch.intervalTime <= 0) {
      ElMessage.error(`通道 ${channel}: 重复次数 ≠ 1 时（0=无限）间隔时间必须 > 0`)
      return
    }
    if (ch.intervalTime > 0 && ch.intervalTime < 0.1) {
      ElMessage.error(`通道 ${channel}: 间隔时间最小值为 0.1 秒`)
      return
    }
  }

  const effectiveFlowRate = ch.mode === 'TIME_QUANTITY' ? calcFlowRate(ch) : ch.flowRate
  if (!await confirmPumpStart(pumpId, channel, effectiveFlowRate)) return
  ch.starting = true
  try {
    const res = await devicesApi.startPump(
      pumpId,
      channel,
      effectiveFlowRate,
      ch.direction,
      ch.mode,
      needsRunTime(ch.mode) ? ch.runTime : undefined,
      needsDispenseVolume(ch.mode) ? ch.dispenseVolume : undefined,
      ch.tubeModel,
      ch.mode === 'TIME_QUANTITY' ? 1 : ch.flowUnit,
      needsRunTime(ch.mode) ? ch.timeUnit : undefined,
      needsDispenseVolume(ch.mode) ? ch.volumeUnit : undefined,
      ch.mode !== 'FLOW_MODE' ? ch.repeatCount : undefined,
      ch.mode !== 'FLOW_MODE' && ch.intervalTime > 0 ? ch.intervalTime : undefined,
      ch.mode !== 'FLOW_MODE' && ch.intervalTime > 0 ? ch.intervalTimeUnit : undefined,
    )
    if (!res.data.success) {
      ElMessage.error(`通道 ${channel} 启动失败: 泵设备返回失败`)
      return
    }
    const modeLabel = PUMP_MODES.find(m => m.value === ch.mode)?.label || ch.mode
    const effectiveFlowUnit = ch.mode === 'TIME_QUANTITY' ? 1 : ch.flowUnit
    ElMessage.success(`通道 ${channel} 已启动 [${modeLabel}]，流量 ${effectiveFlowRate.toFixed(2)} ${flowUnitLabel(effectiveFlowUnit)}`)
  } catch (e: any) {
    ElMessage.error(`通道 ${channel} 启动失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    ch.starting = false
  }
}

async function stopPumpChannel(pumpId: string, channel: number) {
  const pump = devices.pumps[pumpId]
  if (!ensureConnected(pump.connected, '蠕动泵 ' + pumpId, pumpConnectionPort(pumpId))) return
  const ch = devices.pumps[pumpId].channels[channel]
  ch.stopping = true
  try {
    const res = await devicesApi.stopPump(pumpId, channel)
    if (!res.data.success) {
      ElMessage.error(`通道 ${channel} 停止失败: 泵设备返回失败`)
      return
    }
    ElMessage.info(`通道 ${channel} 已停止`)
  } catch (e: any) {
    ElMessage.error(`通道 ${channel} 停止失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    ch.stopping = false
  }
}

async function stopPumpAll(pumpId: string) {
  const pump = devices.pumps[pumpId]
  if (!ensureConnected(pump.connected, '蠕动泵 ' + pumpId, pumpConnectionPort(pumpId))) return
  try {
    await ElMessageBox.confirm('确定要停止所有通道吗？', '确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }

  pump.stoppingAll = true
  try {
    const res = await devicesApi.stopPump(pumpId)
    if (!res.data.success) {
      ElMessage.error('停止所有通道失败: 泵设备返回失败')
      return
    }
    ElMessage.info('所有通道已停止')
  } catch (e: any) {
    ElMessage.error(`停止所有通道失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    pump.stoppingAll = false
  }
}

function microwaveStatus(id: string): MicrowaveRealtimeData | null {
  return realtimeData.value?.microwaves?.[id] || microwaveSnapshots[id] || null
}

function syncMicrowaveSafetyFlags(id: string, status: MicrowaveRealtimeData) {
  if (!devices.microwaves[id]) return
  if (typeof status.connection_port === 'string') {
    devices.microwaves[id].connectionPort = status.connection_port
  }
  if (typeof status.connection_binding_mode === 'string') {
    devices.microwaves[id].bindingMode = status.connection_binding_mode
  }
  if (typeof status.binding_label === 'string') {
    devices.microwaves[id].bindingLabel = status.binding_label
  }
  if (typeof status.binding_resolved === 'boolean') {
    devices.microwaves[id].bindingResolved = status.binding_resolved
  }
  if (status.binding_error !== undefined) {
    devices.microwaves[id].bindingError = status.binding_error ?? null
  }
  if (typeof status.allow_experiment_control === 'boolean') {
    devices.microwaves[id].allowExperimentControl = status.allow_experiment_control
  }
  if (typeof status.allow_real_hardware_writes === 'boolean') {
    devices.microwaves[id].allowRealHardwareWrites = status.allow_real_hardware_writes
  }
  if (typeof status.enable_control_writes === 'boolean') {
    devices.microwaves[id].enableControlWrites = status.enable_control_writes
  }
}

function microwaveConnectionPort(id: string): string {
  const status = microwaveStatus(id)
  return status?.connection_port ?? devices.microwaves[id]?.connectionPort ?? '--'
}

function validateMicrowaveProgram(microwave: MicrowaveDeviceState): boolean {
  try {
    microwaveProgramPayload(microwave)
    return true
  } catch (e: any) {
    ElMessage.error(e.message)
    return false
  }
}

async function connectMicrowave(id: string) {
  if (!ensureBindingResolved(devices.microwaves[id].bindingResolved, '微波仪' + id, devices.microwaves[id].bindingLabel)) return
  devices.microwaves[id].connectionError = null
  devices.microwaves[id].configuredProgramKey = ''
  devices.microwaves[id].loading = true
  try {
    const res = await devicesApi.connectMicrowave(id)
    if (!res.data.success) {
      const message = '连接失败: 微波仪设备返回失败'
      devices.microwaves[id].connectionError = message
      ElMessage.error(message)
      return
    }
    devices.microwaves[id].connected = true
    ElMessage.success(`微波仪 ${id} 已连接`)
    await refreshDevices()
    await readMicrowaveData(id)
  } catch (e: any) {
    const message = `连接失败: ${e.response?.data?.detail || e.message}`
    if (!devices.microwaves[id].connected) devices.microwaves[id].connectionError = message
    ElMessage.error(message)
  } finally {
    devices.microwaves[id].loading = false
  }
}

async function disconnectMicrowave(id: string) {
  devices.microwaves[id].configuredProgramKey = ''
  devices.microwaves[id].loading = true
  try {
    const res = await devicesApi.disconnectMicrowave(id)
    if (!res.data.success) {
      ElMessage.error('断开失败: 微波仪设备返回失败')
      return
    }
    devices.microwaves[id].connected = false
    delete microwaveSnapshots[id]
    ElMessage.info(`微波仪 ${id} 已断开`)
    await refreshDevices()
  } catch (e: any) {
    ElMessage.error(`断开失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.microwaves[id].loading = false
  }
}

async function readMicrowaveData(id: string) {
  if (!ensureConnected(devices.microwaves[id].connected, '微波仪 ' + id, microwaveConnectionPort(id))) return
  devices.microwaves[id].refreshing = true
  try {
    const res = await devicesApi.readMicrowaveData(id)
    microwaveSnapshots[id] = res.data
    syncMicrowaveSafetyFlags(id, res.data)
    ElMessage.success(`微波仪 ${id} 状态已刷新`)
  } catch (e: any) {
    microwaveSnapshots[id] = {
      device_id: id,
      connection_port: devices.microwaves[id].connectionPort,
      error: 'read_failed',
    }
    ElMessage.error(`读取失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.microwaves[id].refreshing = false
  }
}

async function configureMicrowave(id: string) {
  const microwave = devices.microwaves[id]
  if (microwave.configuring || microwave.starting) return
  if (!validateMicrowaveProgram(microwave)) return
  const key = microwaveProgramKey(microwave)
  const revision = microwave.programRevision
  microwave.configuring = true
  microwave.configuredProgramKey = ''
  try {
    microwave.programRequestId = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      value => value.toString(16).padStart(2, '0')).join('')
    const res = await devicesApi.previewMicrowaveProgram(id, hostedMicrowavePayload(microwave, microwave.programRequestId))
    if (!res.data.success) throw new Error('程序校验失败')
    if (revision !== microwave.programRevision || key !== microwaveProgramKey(microwave)) throw new Error('参数已变化，请重新检查程序')
    microwave.configuredProgramKey = key
    ElMessage.success('电脑托管程序已检查；尚未控制设备')
  } catch (e: any) {
    ElMessage.error('检查失败: ' + (e.response?.data?.detail || e.message))
  } finally { microwave.configuring = false }
}

async function startMicrowave(id: string) {
  const microwave = devices.microwaves[id]
  if (!ensureConnected(microwave.connected, '微波仪 ' + id, microwaveConnectionPort(id))) return
  if (microwave.configuring || microwave.starting) return
  if (!validateMicrowaveProgram(microwave)) return
  if (!microwaveProgramConfigured(microwave)) {
    ElMessage.error('请先检查当前整套程序；参数变更后需要重新检查')
    return
  }
  const configuredKey = microwave.configuredProgramKey
  const status = microwaveStatus(id)
  if (!status) {
    ElMessage.error('微波仪尚未获取到状态，请先刷新状态并确认设备正常')
    return
  }
  if (status?.error) {
    ElMessage.error('微波仪状态读取失败，请先刷新状态并确认设备正常')
    return
  }
  if (!status?.status_confirmed || status?.control_active === null) {
    ElMessage.error('微波仪控制位状态未知，禁止启动；请检查 40151 读回')
    return
  }
  if (Number(status?.fault_code || 0)) {
    ElMessage.error('微波仪存在故障码 ' + status?.fault_code + '，禁止启动')
    return
  }
  if (status.control_active || Number(status?.power_percent || 0) > 0 || Number(status?.current || 0) > 0) {
    ElMessage.error('微波仪仍在控制运行或有输出，禁止重复启动；请先停止并确认设备状态')
    return
  }
  microwave.starting = true
  try {
    await ElMessageBox.confirm(
      '启动电脑托管程序，共 ' + microwave.usedSegments + ' 个逻辑段。后端将逐段配置温度、启动、等待到温、计时保温并确认停止，再进入下一段；段间会短暂停机。无需在触摸屏设置执行范围。\n本流程会覆盖设备五个硬件段的参数，运行期间须保持后端服务运行并有人看护。\n请确认炉门关闭、反应瓶非空载、探头没入物料，当前串口 ' + microwaveConnectionPort(id) + ' 对应目标设备。',
      '微波仪启动确认',
      {
        confirmButtonText: '确认启动托管程序',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    if (configuredKey !== microwave.configuredProgramKey || !microwaveProgramConfigured(microwave) || !microwave.connected) {
      throw new Error('参数或连接已变化，请重新检查程序')
    }
    const res = await devicesApi.startMicrowaveProgram(id, hostedMicrowavePayload(microwave, microwave.programRequestId, true))
    microwavePrograms[id] = res.data
    microwave.configuredProgramKey = ''
    if (res.data.state !== 'running') {
      ElMessage.error('托管请求已处理，请查看运行状态；不会重复执行旧请求')
      return
    }
    ElMessage.success(`微波仪 ${id} 托管程序已启动`)
    await readMicrowaveData(id)
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(`启动失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    microwave.starting = false
  }
}

async function stopMicrowave(id: string) {
  if (!ensureConnected(devices.microwaves[id].connected, '微波仪 ' + id, microwaveConnectionPort(id))) return
  try {
    await ElMessageBox.confirm(
      '即将向微波仪 ' + id + '（串口 ' + microwaveConnectionPort(id) + '）发送停止控制字。\n' +
      '该操作会触碰控制字 40151；请确认需要停止当前目标设备后继续。',
      '微波仪停止确认',
      {
        confirmButtonText: '确认停止',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    devices.microwaves[id].stopping = true
    devices.microwaves[id].configuredProgramKey = ''
    devices.microwaves[id].programRevision++
    await refreshMicrowavePrograms()
    const host = microwavePrograms[id]
    const hosted = host && host.state !== 'interrupted' && (host.state === 'running' || host.state === 'paused' || host.cleanup_pending)
    const res = hosted ? await devicesApi.stopMicrowaveProgram(id) : await devicesApi.stopMicrowave(id)
    await refreshMicrowavePrograms()
    if (!res.data.success) {
      ElMessage.error('停止失败: 微波仪设备返回失败')
      return
    }
    ElMessage.success('微波仪 ' + id + ' 已确认停止')
    await readMicrowaveData(id)
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error('停止失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    devices.microwaves[id].stopping = false
  }
}

async function recoverMicrowaveProgram(id: string) {
  try {
    await ElMessageBox.confirm('请现场确认微波设备已经停止且功率、电流归零。解除锁定不会恢复或重放程序。', '人工恢复确认', { type: 'warning', confirmButtonText: '设备已停止，解除锁定' })
    await devicesApi.acknowledgeMicrowaveProgram(id)
    await refreshMicrowavePrograms()
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error('解除锁定失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function emergencyStop() {
  try {
    await ElMessageBox.confirm('确定要紧急停止所有设备吗？此操作不可撤销！', '紧急停止确认', {
      confirmButtonText: '确认紧急停止',
      cancelButtonText: '取消',
      type: 'error',
    })
    for (const microwave of Object.values(devices.microwaves)) {
      microwave.configuredProgramKey = ''
      microwave.programRevision++
    }
    const res = await devicesApi.emergencyStop()
    await refreshDevices()
    if (!res.data.success) {
      const unresolved = (res.data.devices || [])
        .filter((item: any) => !item.success)
        .map((item: any) => `${item.device_type}/${item.device_id}: ${item.reason || '停止未确认'}`)
        .join('; ')
      ElMessage.error(`紧急停止未完全成功：${unresolved || '至少一个设备停止未确认'}`)
      return
    }
    ElMessage.success('所有已注册设备已确认停止')
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(`紧急停止失败: ${e.response?.data?.detail || e.message || e}`)
  }
}

function needsRunTime(mode: PumpMode): boolean {
  return mode === 'TIME_QUANTITY' || mode === 'TIME_SPEED'
}

function needsDispenseVolume(mode: PumpMode): boolean {
  return mode === 'TIME_QUANTITY' || mode === 'QUANTITY_SPEED'
}

function calcFlowRate(ch: ChannelConfig): number {
  if (ch.mode === 'TIME_QUANTITY' && ch.runTime > 0) {
    const volumeMl = ch.volumeUnit === 0
      ? ch.dispenseVolume / 1000
      : ch.volumeUnit === 2
        ? ch.dispenseVolume * 1000
        : ch.dispenseVolume
    const timeMinutes = ch.timeUnit === 0
      ? ch.runTime / 60
      : ch.timeUnit === 2
        ? ch.runTime * 60
        : ch.runTime
    return volumeMl / timeMinutes
  }
  return ch.flowRate
}
</script>

<style scoped>
.control-panel { padding: 0; }
.emergency-bar { position: static; margin: 0 0 18px; border-radius: 6px; box-shadow: none; }
.device-workspace { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 20px; align-items: start; }
.device-selector { position: sticky; top: 88px; padding: 0 14px 0 0; border-right: 1px solid var(--el-border-color-light); min-width: 0; }
.selector-heading { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px 14px; font-size: 14px; font-weight: 600; }
.selector-heading span { color: var(--el-text-color-secondary); font-size: 12px; }
.device-choice { display: block; width: 100%; margin-bottom: 6px; padding: 12px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--el-text-color-regular); text-align: left; cursor: pointer; font: inherit; }
.device-choice:hover { background: var(--el-fill-color-light); }
.device-choice.selected { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }
.device-choice:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.choice-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 14px; }
.choice-heading strong { overflow-wrap: anywhere; }
.connection-dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: var(--el-text-color-placeholder); }
.connection-dot.online { background: var(--el-color-success); }
.choice-meta { display: block; margin-top: 5px; color: var(--el-text-color-secondary); font-size: 12px; overflow-wrap: anywhere; }
.device-detail { min-width: 0; }
.device-detail > section, .device-detail :deep(section[aria-label="注射泵设备"]) { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
.device-detail :deep(.device-card), .device-detail :deep(.syringe-panel) { margin-bottom: 0; width: 100%; box-sizing: border-box; }
.device-detail :deep(.el-card__header) { min-height: 88px; box-sizing: border-box; display: flex; align-items: center; }
.device-detail :deep(.card-header) { width: 100%; }
@media (max-width: 900px) {
  .device-workspace { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .device-selector { position: static; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; padding: 0 0 12px; border-right: 0; border-bottom: 1px solid var(--el-border-color-light); }
  .selector-heading { grid-column: 1 / -1; padding: 0 2px 4px; }
  .device-choice { margin: 0; padding: 10px; }
}
</style>
