<template>
  <el-card shadow="never" class="device-card heater-card">
    <template #header>
      <div class="card-header">
        <div class="device-heading"><img :src="deviceArtwork" alt="" /><div><h2>加热器</h2><span>{{ heaterId }} 控制</span></div></div>
        <div class="header-tags">
          <el-tag :type="heater.disconnectFailed ? 'danger' : heater.connected ? 'success' : 'info'" size="small">
            {{ heater.disconnectFailed ? '连接异常' : heater.connected ? '已连接' : '未连接' }}
          </el-tag>
        </div>
        <DeviceConnectionControls :device-key="'heater:'+heaterId" :connected="heater.connected" :loading="heater.loading" :connect-disabled="heater.bindingResolved === false" hint="安全停止后断开；失败时可重试" @connect="$emit('connect', heaterId)" @disconnect="$emit('disconnect', heaterId)" />
      </div>
    </template>
    <el-alert v-if="heater.connectionError" :title="heater.connectionError" type="error" :closable="false" show-icon class="connection-feedback" />
    <div class="heater-readings"><div><span>当前温度</span><strong>{{ reading ? reading.pv.toFixed(1) + ' ℃' : '—' }}</strong></div><div><span>设定温度读回</span><strong>{{ reading ? reading.sv.toFixed(1) + ' ℃' : '—' }}</strong></div><div><span>输出功率</span><strong>{{ reading ? reading.mv + ' %' : '—' }}</strong></div></div>
    <p class="reading-note">{{ reading ? '设备实时读回' : '未收到有效实时读数，当前状态未知' }}</p>
    <details class="device-details"><summary>设备详情与通信状态</summary><div class="detail-tags">          <el-tag type="info" size="small">串口 {{ heater.connectionPort || '--' }}</el-tag>
          <el-tag v-if="showBindingLabel" type="info" size="small">{{ heater.bindingLabel }}</el-tag>
          <el-tag :type="bindingTagType" size="small">{{ bindingTagText }}</el-tag>
</div></details>
    <el-form label-width="104px" size="default">
      <el-alert
        v-if="heater.disconnectFailed"
        title="上次安全断开失败，设备停止状态未确认。请先现场确认设备状态并检查串口，再重试。"
        type="error"
        :closable="false"
        show-icon
        class="disconnect-alert"
      />
      <el-form-item label="待设温度">
        <div class="temperature-input"><el-input-number v-model="heater.targetTemp" :min="heater.minTemperature" :max="heater.maxTemperature" :step="1" :precision="1" /><span>℃</span></div>
        <el-button type="primary" @click="$emit('setTemp', heaterId, heater.targetTemp)" style="margin-left: 10px">
          写入温度
        </el-button>
      </el-form-item>
      <el-form-item label="运行控制">
        <el-button type="success" @click="$emit('start', heaterId)" :loading="heater.starting">启动</el-button>
        <el-button type="danger" plain @click="$emit('stop', heaterId)" :loading="heater.stopping">停止</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import DeviceConnectionControls from './DeviceConnectionControls.vue'
import deviceArtwork from '../assets/theme/heater.webp'
import { computed } from 'vue'
import type { HeaterRealtimeData } from '../composables/useWebSocket'

const props = defineProps<{
  realtime?: HeaterRealtimeData | null
  heaterId: string
  heater: {
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
    minTemperature?: number
    maxTemperature?: number
    starting: boolean
    stopping: boolean
  }
}>()

const reading = computed(() => props.heater.connected && !props.realtime?.error && [props.realtime?.pv, props.realtime?.sv, props.realtime?.mv].every(v => typeof v === 'number' && Number.isFinite(v)) ? props.realtime! : null)

defineEmits<{
  connect: [id: string]
  disconnect: [id: string]
  setTemp: [id: string, temp: number]
  start: [id: string]
  stop: [id: string]
}>()

const bindingTagType = computed(() => {
  if (props.heater.bindingResolved === false) return 'danger'
  if (props.heater.bindingError === 'fallback_to_port') return 'warning'
  return 'success'
})

const bindingTagText = computed(() => {
  if (props.heater.bindingResolved === false) return '未匹配'
  if (props.heater.bindingError === 'fallback_to_port') return '端口回退'
  return '已匹配'
})

const showBindingLabel = computed(() => props.heater.bindingMode === 'fingerprint' && Boolean(props.heater.bindingLabel))
</script>

<style scoped>
.temperature-input { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.temperature-input > span { color: #526b83; font-size: 14px; }
.heater-readings { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; }
.heater-readings > div { background: #f0f6fd; border-radius: 10px; padding: 14px 10px; min-width: 0; }
.heater-readings span,.heater-readings strong { display: block; }
.heater-readings span { font-size: 12px; color: #526b83; margin-bottom: 8px; }
.heater-readings strong { font-size: 21px; color: #245483; overflow-wrap: anywhere; }
.reading-note { font-size: 12px; color: #526b83; }
.device-details { margin: 16px 0; padding: 12px; background: #f5f8fc; border-radius: 8px; font-size: 13px; }
.device-details summary { cursor: pointer; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }

.card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.header-tags { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.disconnect-alert { margin-bottom: 18px; }
.connection-feedback { margin-bottom: 16px; }
</style>
