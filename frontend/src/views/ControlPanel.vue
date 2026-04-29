<template>
  <div class="control-panel">
    <el-row :gutter="20">
      <el-col :span="12">
        <el-card v-for="(heater, id) in devices.heaters" :key="'h-'+id" shadow="hover" style="margin-bottom: 20px">
          <template #header>
            <div class="card-header">
              <span>加热器 {{ id }} 控制</span>
              <el-tag :type="heater.connected ? 'success' : 'info'" size="small">
                {{ heater.connected ? '已连接' : '未连接' }}
              </el-tag>
            </div>
          </template>
          <el-form label-width="80px" size="default">
            <el-form-item label="连接">
              <el-button v-if="!heater.connected" type="primary" @click="connectHeater(id)" :loading="heater.loading">
                连接设备
              </el-button>
              <el-button v-else type="danger" @click="disconnectHeater(id)" :loading="heater.loading">
                断开连接
              </el-button>
            </el-form-item>
            <el-form-item label="目标温度">
              <el-input-number v-model="heater.targetTemp" :min="0" :max="450" :step="1" :precision="1" />
              <el-button type="primary" @click="setTemp(id, heater.targetTemp)" :disabled="!heater.connected" style="margin-left: 10px">
                设置
              </el-button>
            </el-form-item>
            <el-form-item label="运行控制">
              <el-button type="success" @click="startHeater(id)" :disabled="!heater.connected" :loading="heater.starting">启动</el-button>
              <el-button type="warning" @click="stopHeater(id)" :disabled="!heater.connected" :loading="heater.stopping">停止</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card v-for="(pump, pumpId) in devices.pumps" :key="'p-'+pumpId" shadow="hover" style="margin-bottom: 20px">
          <template #header>
            <div class="card-header">
              <span>蠕动泵 {{ pumpId }} 控制</span>
              <div>
                <el-tag :type="pump.connected ? 'success' : 'info'" size="small" style="margin-right: 8px">
                  {{ pump.connected ? '已连接' : '未连接' }}
                </el-tag>
                <el-button v-if="!pump.connected" type="primary" size="small" @click="connectPump(pumpId)" :loading="pump.loading">
                  连接
                </el-button>
                <el-button v-else type="danger" size="small" @click="disconnectPump(pumpId)" :loading="pump.loading">
                  断开
                </el-button>
              </div>
            </div>
          </template>

          <div v-for="ch in [1,2,3,4]" :key="ch" class="channel-control">
            <div class="channel-header">
              <span class="channel-name">通道 {{ ch }}</span>
              <el-tag v-if="pump.connected && channelStatus(pumpId, ch)?.running" type="success" size="small">
                运行中 {{ channelStatus(pumpId, ch)?.flow_rate }} mL/min
              </el-tag>
              <el-tag v-else-if="pump.connected" type="info" size="small">停止</el-tag>
            </div>
            <div class="channel-row">
              <el-select v-model="pump.channels[ch].mode" size="small" style="width: 120px" :disabled="!pump.connected">
                <el-option v-for="m in PUMP_MODES" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <el-input-number
                v-model="pump.channels[ch].flowRate"
                :min="0.1" :max="100" :step="0.5" :precision="1"
                size="small"
                style="width: 120px"
                :disabled="!pump.connected"
              />
              <span class="unit-label">mL/min</span>
            </div>
            <div class="channel-row" style="margin-top: 6px">
              <el-radio-group v-model="pump.channels[ch].direction" size="small" :disabled="!pump.connected">
                <el-radio-button value="CW">顺时针</el-radio-button>
                <el-radio-button value="CCW">逆时针</el-radio-button>
              </el-radio-group>
              <el-input-number
                v-if="needsRunTime(pump.channels[ch].mode)"
                v-model="pump.channels[ch].runTime"
                :min="0.1" :max="9999" :step="1" :precision="1"
                size="small"
                style="width: 110px"
                :disabled="!pump.connected"
              />
              <span v-if="needsRunTime(pump.channels[ch].mode)" class="unit-label">秒</span>
              <el-input-number
                v-if="needsDispenseVolume(pump.channels[ch].mode)"
                v-model="pump.channels[ch].dispenseVolume"
                :min="0.1" :max="9999" :step="1" :precision="1"
                size="small"
                style="width: 110px"
                :disabled="!pump.connected"
              />
              <span v-if="needsDispenseVolume(pump.channels[ch].mode)" class="unit-label">mL</span>
            </div>
            <div class="channel-row" style="margin-top: 6px">
              <el-button type="success" size="small" @click="startPumpChannel(pumpId, ch)" :disabled="!pump.connected" :loading="pump.channels[ch].starting">
                启动
              </el-button>
              <el-button type="warning" size="small" @click="stopPumpChannel(pumpId, ch)" :disabled="!pump.connected" :loading="pump.channels[ch].stopping">
                停止
              </el-button>
            </div>
          </div>

          <div style="margin-top: 12px; text-align: center">
            <el-button type="danger" size="small" @click="stopPumpAll(pumpId)" :disabled="!pump.connected" :loading="pump.stoppingAll">
              停止所有通道
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-button type="danger" size="large" @click="emergencyStop"
               style="width: 100%; margin-top: 10px; font-size: 18px; height: 56px">
      紧急停止所有设备
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { devicesApi, PUMP_MODES, type PumpMode } from '../api/devices'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket } from '../composables/useWebSocket'

const { data: realtimeData } = useWebSocket()

interface ChannelConfig {
  flowRate: number
  direction: string
  mode: PumpMode
  runTime: number
  dispenseVolume: number
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

function needsRunTime(mode: PumpMode): boolean {
  return mode === 'TIME_QUANTITY' || mode === 'TIME_SPEED'
}

function needsDispenseVolume(mode: PumpMode): boolean {
  return mode === 'TIME_QUANTITY' || mode === 'QUANTITY_SPEED'
}

function createPumpChannels(): Record<number, ChannelConfig> {
  const channels: Record<number, ChannelConfig> = {}
  for (let i = 1; i <= 4; i++) {
    channels[i] = { flowRate: 10.0, direction: 'CW', mode: 'FLOW_MODE', runTime: 60, dispenseVolume: 10.0, starting: false, stopping: false }
  }
  return channels
}

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
  refreshDevices()
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
  ch.starting = true
  try {
    await devicesApi.startPump(
      pumpId,
      channel,
      ch.flowRate,
      ch.direction,
      ch.mode,
      needsRunTime(ch.mode) ? ch.runTime : undefined,
      needsDispenseVolume(ch.mode) ? ch.dispenseVolume : undefined,
    )
    const modeLabel = PUMP_MODES.find(m => m.value === ch.mode)?.label || ch.mode
    ElMessage.success(`通道 ${channel} 已启动 [${modeLabel}]，流量 ${ch.flowRate} mL/min`)
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
</script>

<style scoped>
.control-panel { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.channel-control {
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}
.channel-control:last-of-type {
  border-bottom: none;
}
.channel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.channel-name {
  font-weight: 600;
  font-size: 14px;
  min-width: 60px;
}
.channel-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.unit-label {
  color: #909399;
  font-size: 12px;
  white-space: nowrap;
}
</style>
