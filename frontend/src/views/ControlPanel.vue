<template>
  <div class="control-panel">
    <el-row :gutter="20">
      <el-col :span="12">
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
      </el-col>

      <el-col :span="12">
        <PumpControl
          v-for="(pump, pumpId) in devices.pumps"
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
      </el-col>

      <el-col :span="12">
        <MicrowaveControl
          v-for="(microwave, microwaveId) in devices.microwaves"
          :key="'m-' + microwaveId"
          :microwave-id="microwaveId"
          :microwave="microwave"
          :realtime="microwaveStatus(microwaveId)"
          @connect="connectMicrowave"
          @disconnect="disconnectMicrowave"
          @refresh="readMicrowaveData"
          @configure="configureMicrowave"
          @start="startMicrowave"
          @stop="stopMicrowave"
        />
      </el-col>
    </el-row>

    <el-button type="danger" size="large" @click="emergencyStop"
               style="width: 100%; margin-top: 10px; font-size: 18px; height: 56px">
      紧急停止所有设备
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, watch } from 'vue'
import { devicesApi, PUMP_MODES, TUBE_MODELS, type MicrowaveMode, type MicrowaveSegmentPayload, type PumpMode } from '../api/devices'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket, type MicrowaveRealtimeData } from '../composables/useWebSocket'
import HeaterControl from '../components/HeaterControl.vue'
import PumpControl from '../components/PumpControl.vue'
import MicrowaveControl from '../components/MicrowaveControl.vue'

const STORAGE_KEY = 'heat_control_params'

const { data: realtimeData } = useWebSocket()

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
  starting: boolean
  stopping: boolean
}

interface PumpDeviceState {
  connected: boolean
  loading: boolean
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
  loading: boolean
  connectionPort?: string
  bindingMode?: string
  bindingLabel?: string
  bindingResolved?: boolean
  bindingError?: string | null
  targetTemp: number
  starting: boolean
  stopping: boolean
}

interface MicrowaveSegmentConfig {
  segment: number
  temperature: number
  powerPercent: number
  hours: number
  minutes: number
  seconds: number
}

interface MicrowaveDeviceState {
  connected: boolean
  loading: boolean
  refreshing: boolean
  configuring: boolean
  starting: boolean
  stopping: boolean
  mode: MicrowaveMode
  selectedSegment: number
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

function channelStatus(pumpId: string, ch: number) {
  const pumpData = realtimeData.value?.pumps?.[pumpId]
  if (!pumpData || pumpData.error) return null
  return pumpData.channels?.[String(ch)] || null
}

function createPumpChannels(): Record<number, ChannelConfig> {
  const channels: Record<number, ChannelConfig> = {}
  for (let i = 1; i <= 4; i++) {
    channels[i] = { flowRate: 10.0, direction: 'CW', mode: 'FLOW_MODE', runTime: 60, timeUnit: 0, dispenseVolume: 10.0, volumeUnit: 1, repeatCount: 1, intervalTime: 0, intervalTimeUnit: 0, tubeModel: 11, maxFlowRate: 22.0, flowUnit: 1, starting: false, stopping: false }
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

function isMicrowaveMode(value: unknown): value is MicrowaveMode {
  return value === 'manual_power' || value === 'auto_power' || value === 'constant_rate'
}

function getMaxFlowRate(tubeModel: number): number {
  const found = TUBE_MODELS.find(t => t.value === tubeModel)
  return found ? found.maxFlow : 7.55
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
      selectedSegment: microwave.selectedSegment,
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
        if (cfg.direction !== undefined) channel.direction = cfg.direction
        if (cfg.mode !== undefined) channel.mode = cfg.mode
        if (cfg.runTime !== undefined) channel.runTime = cfg.runTime
        if (cfg.timeUnit !== undefined) channel.timeUnit = cfg.timeUnit
        if (cfg.dispenseVolume !== undefined) channel.dispenseVolume = cfg.dispenseVolume
        if (cfg.volumeUnit !== undefined) channel.volumeUnit = cfg.volumeUnit
        if (cfg.repeatCount !== undefined) channel.repeatCount = cfg.repeatCount
        if (cfg.intervalTime !== undefined) channel.intervalTime = cfg.intervalTime
        if (cfg.intervalTimeUnit !== undefined) channel.intervalTimeUnit = cfg.intervalTimeUnit
        if (cfg.tubeModel !== undefined) {
          channel.tubeModel = cfg.tubeModel
          channel.maxFlowRate = getMaxFlowRate(cfg.tubeModel)
        }
        if (cfg.flowUnit !== undefined) channel.flowUnit = cfg.flowUnit
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
      if (isMicrowaveMode(cfg.mode)) devices.microwaves[microwaveId].mode = cfg.mode
      const selectedSegment = Number(cfg.selectedSegment)
      if (selectedSegment >= 1 && selectedSegment <= 5) {
        devices.microwaves[microwaveId].selectedSegment = selectedSegment
      }
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

watch(devices, saveParams, { deep: true })

async function refreshDevices() {
  try {
    const res = await devicesApi.list()
    const data = res.data
    for (const [id, info] of Object.entries(data.heaters || {})) {
      if (!devices.heaters[id]) {
        devices.heaters[id] = { connected: false, loading: false, targetTemp: 25.0, starting: false, stopping: false, bindingResolved: true }
      }
      devices.heaters[id].connected = (info as any).connected
      devices.heaters[id].connectionPort = (info as any).connection_port
      devices.heaters[id].bindingMode = (info as any).connection_binding_mode
      devices.heaters[id].bindingLabel = (info as any).binding_label
      devices.heaters[id].bindingResolved = (info as any).binding_resolved !== false
      devices.heaters[id].bindingError = (info as any).binding_error ?? null
    }
    for (const [id, info] of Object.entries(data.pumps || {})) {
      if (!devices.pumps[id]) {
        devices.pumps[id] = { connected: false, loading: false, stoppingAll: false, channels: createPumpChannels(), bindingResolved: true }
      }
      devices.pumps[id].connected = (info as any).connected
      devices.pumps[id].connectionPort = (info as any).connection_port
      devices.pumps[id].bindingMode = (info as any).connection_binding_mode
      devices.pumps[id].bindingLabel = (info as any).binding_label
      devices.pumps[id].bindingResolved = (info as any).binding_resolved !== false
      devices.pumps[id].bindingError = (info as any).binding_error ?? null
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
          mode: 'manual_power',
          selectedSegment: 1,
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
      devices.microwaves[id].connectionPort = (info as any).connection_port
      devices.microwaves[id].bindingMode = (info as any).connection_binding_mode
      devices.microwaves[id].bindingLabel = (info as any).binding_label
      devices.microwaves[id].bindingResolved = (info as any).binding_resolved !== false
      devices.microwaves[id].bindingError = (info as any).binding_error ?? null
      devices.microwaves[id].allowExperimentControl = Boolean((info as any).allow_experiment_control)
      devices.microwaves[id].allowRealHardwareWrites = Boolean((info as any).allow_real_hardware_writes)
      devices.microwaves[id].enableControlWrites = Boolean((info as any).enable_control_writes)
    }
  } catch (e) {
    console.error('Failed to refresh devices:', e)
  }
}

onMounted(() => {
  refreshDevices().then(restoreParams)
})

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

async function confirmPumpStart(pumpId: string, channel: number, effectiveFlowRate: number): Promise<boolean> {
  const ch = devices.pumps[pumpId].channels[channel]
  try {
    await ElMessageBox.confirm(
      '即将启动蠕动泵 ' + pumpId + '（串口 ' + pumpConnectionPort(pumpId) + '）通道 ' + channel + '。\n' +
      '模式：' + pumpModeLabel(ch.mode) + '；方向：' + directionLabel(ch.direction) + '；软管：' + tubeModelLabel(ch.tubeModel) + '；流量：' + effectiveFlowRate.toFixed(3) + ' mL/min。\n' +
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
  devices.heaters[id].loading = true
  try {
    const res = await devicesApi.connectHeater(id)
    if (!res.data.success) {
      ElMessage.error('连接失败: 加热器设备返回失败')
      return
    }
    devices.heaters[id].connected = true
    ElMessage.success(`加热器 ${id} 已连接`)
  } catch (e: any) {
    ElMessage.error(`连接失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.heaters[id].loading = false
  }
}

async function disconnectHeater(id: string) {
  devices.heaters[id].loading = true
  try {
    const res = await devicesApi.disconnectHeater(id)
    if (!res.data.success) {
      ElMessage.error('断开失败: 加热器设备返回失败')
      return
    }
    devices.heaters[id].connected = false
    ElMessage.info(`加热器 ${id} 已断开`)
  } catch (e: any) {
    ElMessage.error(`断开失败: ${e.response?.data?.detail || e.message}`)
  } finally {
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
  devices.pumps[id].loading = true
  try {
    const res = await devicesApi.connectPump(id)
    if (!res.data.success) {
      ElMessage.error('连接失败: 蠕动泵设备返回失败')
      return
    }
    devices.pumps[id].connected = true
    ElMessage.success(`蠕动泵 ${id} 已连接`)
  } catch (e: any) {
    ElMessage.error(`连接失败: ${e.response?.data?.detail || e.message}`)
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
    ElMessage.success(`通道 ${channel} 已启动 [${modeLabel}]，流量 ${effectiveFlowRate.toFixed(2)} mL/min`)
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
  pump.stoppingAll = true
  try {
    await ElMessageBox.confirm('确定要停止所有通道吗？', '确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const res = await devicesApi.stopPump(pumpId)
    if (!res.data.success) {
      ElMessage.error('停止所有通道失败: 泵设备返回失败')
      return
    }
    ElMessage.info('所有通道已停止')
  } catch {
    // 用户取消
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

function microwaveSegmentPayload(microwave: MicrowaveDeviceState): MicrowaveSegmentPayload {
  const segment = microwave.segments[microwave.selectedSegment]
  const payload: MicrowaveSegmentPayload = {
    segment: segment.segment,
    heating_temperature: segment.temperature,
    target_temperature: segment.temperature,
    holding_temperature: segment.temperature,
    holding_deviation: 0,
    hours: segment.hours,
    minutes: segment.minutes,
    seconds: segment.seconds,
    ramp_hours: 0,
    ramp_minutes: 0,
    ramp_seconds: 0,
  }
  if (microwave.mode === 'manual_power') {
    payload.heating_power_percent = segment.powerPercent
    payload.holding_power_percent = segment.powerPercent
  }
  return payload
}

function validateMicrowaveSegment(microwave: MicrowaveDeviceState): boolean {
  if (!isMicrowaveMode(microwave.mode)) {
    ElMessage.error('微波仪模式不合法')
    return false
  }
  const segment = microwave.segments[microwave.selectedSegment]
  if (segment.segment < 1 || segment.segment > 5) {
    ElMessage.error('微波仪段号范围为 1-5')
    return false
  }
  if (segment.temperature < 0 || segment.temperature > 300) {
    ElMessage.error('微波仪温度范围为 0-300°C')
    return false
  }
  if (microwave.mode === 'manual_power' && (segment.powerPercent < 0 || segment.powerPercent > 100)) {
    ElMessage.error('微波仪手动功率范围为 0-100%')
    return false
  }
  if (segment.hours < 0 || segment.minutes < 0 || segment.minutes > 59 || segment.seconds < 0 || segment.seconds > 59) {
    ElMessage.error('微波仪时间范围不合法')
    return false
  }
  return true
}

async function connectMicrowave(id: string) {
  if (!ensureBindingResolved(devices.microwaves[id].bindingResolved, '微波仪' + id, devices.microwaves[id].bindingLabel)) return
  devices.microwaves[id].loading = true
  try {
    const res = await devicesApi.connectMicrowave(id)
    if (!res.data.success) {
      ElMessage.error('连接失败: 微波仪设备返回失败')
      return
    }
    devices.microwaves[id].connected = true
    ElMessage.success(`微波仪 ${id} 已连接`)
    await refreshDevices()
    await readMicrowaveData(id)
  } catch (e: any) {
    ElMessage.error(`连接失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.microwaves[id].loading = false
  }
}

async function disconnectMicrowave(id: string) {
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
  if (!ensureConnected(microwave.connected, '微波仪 ' + id, microwaveConnectionPort(id))) return
  if (!validateMicrowaveSegment(microwave)) return
  try {
    const segment = microwave.segments[microwave.selectedSegment]
    await ElMessageBox.confirm(
      '即将向微波仪 ' + id + '（串口 ' + microwaveConnectionPort(id) + '）写入普通配置寄存器。\n' +
      '本操作不会调用 start/stop，不会写控制字 40151。\n' +
      '模式：' + microwave.mode + '；段：' + microwave.selectedSegment + '；温度：' + segment.temperature + '°C；功率：' + segment.powerPercent + '%。\n' +
      '请确认设备、串口和参数已检查无误后继续。',
      '微波仪配置写入确认',
      {
        confirmButtonText: '确认写入配置',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    microwave.configuring = true
    await devicesApi.configureMicrowave(id, microwave.mode, [microwaveSegmentPayload(microwave)], true)
    ElMessage.success('微波仪 ' + id + ' 第 ' + microwave.selectedSegment + ' 段已配置')
    await readMicrowaveData(id)
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error('配置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    microwave.configuring = false
  }
}

async function startMicrowave(id: string) {
  const microwave = devices.microwaves[id]
  if (!ensureConnected(microwave.connected, '微波仪 ' + id, microwaveConnectionPort(id))) return
  if (!validateMicrowaveSegment(microwave)) return
  const status = microwaveStatus(id)
  if (!status) {
    ElMessage.error('微波仪尚未获取到状态，请先刷新状态并确认设备正常')
    return
  }
  if (status?.error) {
    ElMessage.error('微波仪状态读取失败，请先刷新状态并确认设备正常')
    return
  }
  if (Number(status?.fault_code || 0)) {
    ElMessage.error('微波仪存在故障码 ' + status?.fault_code + '，禁止启动')
    return
  }
  if (Number(status?.power_percent || 0) > 0 || Number(status?.current || 0) > 0) {
    ElMessage.error('微波仪已有功率输出或电流非零，禁止重复启动；请先确认设备状态')
    return
  }
  microwave.starting = true
  try {
    await ElMessageBox.confirm(
      '启动微波输出前请确认：\n1. 炉门已关闭，设备门控联锁正常；说明书记录未关门时设备/HMI 会禁止启动并提示门未关严。\n2. 反应瓶非空载，光纤探头已没入物料。\n3. 温度、功率和时间参数已核对。\n4. 设备运行期间有人看护。\n5. 当前串口为 ' + microwaveConnectionPort(id) + '，确认连接的是目标微波仪。\n确认后才会调用微波仪启动接口。',
      '微波仪启动确认',
      {
        confirmButtonText: '确认启动',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    const res = await devicesApi.startMicrowave(id, microwave.mode)
    if (!res.data.success) {
      ElMessage.error('微波仪启动失败: 设备返回失败')
      return
    }
    ElMessage.success(`微波仪 ${id} 启动请求已发送`)
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
    const res = await devicesApi.stopMicrowave(id)
    if (!res.data.success) {
      ElMessage.error('停止失败: 微波仪设备返回失败')
      return
    }
    ElMessage.info('微波仪 ' + id + ' 已发送停止请求')
    await readMicrowaveData(id)
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error('停止失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    devices.microwaves[id].stopping = false
  }
}

async function emergencyStop() {
  try {
    await ElMessageBox.confirm('确定要紧急停止所有设备吗？此操作不可撤销！', '紧急停止确认', {
      confirmButtonText: '确认紧急停止',
      cancelButtonText: '取消',
      type: 'error',
    })
    const res = await devicesApi.emergencyStop()
    await refreshDevices()
    if (!res.data.success) {
      ElMessage.error('紧急停止未完全成功：至少一个设备返回失败')
      return
    }
    ElMessage.error('紧急停止已执行！')
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
    return ch.dispenseVolume / (ch.runTime / 60)
  }
  return ch.flowRate
}
</script>

<style scoped>
.control-panel { padding: 20px; }
</style>
