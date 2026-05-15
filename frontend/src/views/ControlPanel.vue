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
    </el-row>

    <el-button type="danger" size="large" @click="emergencyStop"
               style="width: 100%; margin-top: 10px; font-size: 18px; height: 56px">
      紧急停止所有设备
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, watch } from 'vue'
import { devicesApi, PUMP_MODES, TUBE_MODELS, type PumpMode } from '../api/devices'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket } from '../composables/useWebSocket'
import HeaterControl from '../components/HeaterControl.vue'
import PumpControl from '../components/PumpControl.vue'

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
  stoppingAll: boolean
  channels: Record<number, ChannelConfig>
}

interface HeaterDeviceState {
  connected: boolean
  loading: boolean
  targetTemp: number
  starting: boolean
  stopping: boolean
}

const devices = reactive<{
  heaters: Record<string, HeaterDeviceState>
  pumps: Record<string, PumpDeviceState>
}>({
  heaters: {},
  pumps: {},
})

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
        devices.heaters[id] = { connected: false, loading: false, targetTemp: 25.0, starting: false, stopping: false }
      }
      devices.heaters[id].connected = (info as any).connected
    }
    for (const [id, info] of Object.entries(data.pumps || {})) {
      if (!devices.pumps[id]) {
        devices.pumps[id] = { connected: false, loading: false, stoppingAll: false, channels: createPumpChannels() }
      }
      devices.pumps[id].connected = (info as any).connected
    }
  } catch (e) {
    console.error('Failed to refresh devices:', e)
  }
}

onMounted(() => {
  refreshDevices().then(restoreParams)
})

async function connectHeater(id: string) {
  devices.heaters[id].loading = true
  try {
    await devicesApi.connectHeater(id)
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
    await devicesApi.disconnectHeater(id)
    devices.heaters[id].connected = false
    ElMessage.info(`加热器 ${id} 已断开`)
  } catch (e: any) {
    ElMessage.error(`断开失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.heaters[id].loading = false
  }
}

async function setTemp(id: string, temp: number) {
  try {
    await devicesApi.setTemperature(id, temp)
    ElMessage.success(`温度已设为 ${temp}°C`)
  } catch (e: any) {
    ElMessage.error(`设置失败: ${e.response?.data?.detail || e.message}`)
  }
}

async function startHeater(id: string) {
  devices.heaters[id].starting = true
  try {
    await devicesApi.startHeater(id)
    ElMessage.success(`加热器 ${id} 已启动`)
  } catch (e: any) {
    ElMessage.error(`启动失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.heaters[id].starting = false
  }
}

async function stopHeater(id: string) {
  devices.heaters[id].stopping = true
  try {
    await devicesApi.stopHeater(id)
    ElMessage.info(`加热器 ${id} 已停止`)
  } catch (e: any) {
    ElMessage.error(`停止失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.heaters[id].stopping = false
  }
}

async function connectPump(id: string) {
  devices.pumps[id].loading = true
  try {
    await devicesApi.connectPump(id)
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
    await devicesApi.disconnectPump(id)
    devices.pumps[id].connected = false
    ElMessage.info(`蠕动泵 ${id} 已断开`)
  } catch (e: any) {
    ElMessage.error(`断开失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    devices.pumps[id].loading = false
  }
}

async function startPumpChannel(pumpId: string, channel: number) {
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

  ch.starting = true
  try {
    const effectiveFlowRate = ch.mode === 'TIME_QUANTITY' ? calcFlowRate(ch) : ch.flowRate
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
  const ch = devices.pumps[pumpId].channels[channel]
  ch.stopping = true
  try {
    await devicesApi.stopPump(pumpId, channel)
    ElMessage.info(`通道 ${channel} 已停止`)
  } catch (e: any) {
    ElMessage.error(`通道 ${channel} 停止失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    ch.stopping = false
  }
}

async function stopPumpAll(pumpId: string) {
  devices.pumps[pumpId].stoppingAll = true
  try {
    await ElMessageBox.confirm('确定要停止所有通道吗？', '确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await devicesApi.stopPump(pumpId)
    ElMessage.info('所有通道已停止')
  } catch {
    // 用户取消
  } finally {
    devices.pumps[pumpId].stoppingAll = false
  }
}

async function emergencyStop() {
  try {
    await ElMessageBox.confirm('确定要紧急停止所有设备吗？此操作不可撤销！', '紧急停止确认', {
      confirmButtonText: '确认紧急停止',
      cancelButtonText: '取消',
      type: 'error',
    })
    await devicesApi.emergencyStop()
    ElMessage.error('紧急停止已执行！')
    refreshDevices()
  } catch {
    // 用户取消
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