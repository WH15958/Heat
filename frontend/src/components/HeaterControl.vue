<template>
  <el-card shadow="never" class="device-card heater-card">
    <template #header>
      <div class="card-header">
        <div class="device-heading"><img :src="deviceArtwork" alt="" /><div><h2>加热器</h2><span>{{ heaterId }} 控制</span></div></div>
        <div class="header-tags">
          <el-tag type="info" size="small">串口 {{ heater.connectionPort || '--' }}</el-tag>
          <el-tag v-if="showBindingLabel" type="info" size="small">{{ heater.bindingLabel }}</el-tag>
          <el-tag :type="bindingTagType" size="small">{{ bindingTagText }}</el-tag>
          <el-tag :type="heater.disconnectFailed ? 'danger' : heater.connected ? 'success' : 'info'" size="small">
            {{ heater.disconnectFailed ? '连接异常' : heater.connected ? '已连接' : '未连接' }}
          </el-tag>
        </div>
        <DeviceConnectionControls :device-key="'heater:'+heaterId" :connected="heater.connected" :loading="heater.loading" :connect-disabled="heater.bindingResolved === false" hint="安全停止后断开；失败时可重试" @connect="$emit('connect', heaterId)" @disconnect="$emit('disconnect', heaterId)" />
      </div>
    </template>
    <el-alert v-if="heater.connectionError" :title="heater.connectionError" type="error" :closable="false" show-icon class="connection-feedback" />
    <el-form label-width="80px" size="default">
      <el-alert
        v-if="heater.disconnectFailed"
        title="上次安全断开失败，设备停止状态未确认。请先现场确认设备状态并检查串口，再重试。"
        type="error"
        :closable="false"
        show-icon
        class="disconnect-alert"
      />
      <el-form-item label="目标温度">
        <el-input-number v-model="heater.targetTemp" :min="heater.minTemperature" :max="heater.maxTemperature" :step="1" :precision="1" />
        <el-button type="primary" @click="$emit('setTemp', heaterId, heater.targetTemp)" style="margin-left: 10px">
          设置
        </el-button>
      </el-form-item>
      <el-form-item label="运行控制">
        <el-button type="success" @click="$emit('start', heaterId)" :loading="heater.starting">启动</el-button>
        <el-button type="warning" @click="$emit('stop', heaterId)" :loading="heater.stopping">停止</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import DeviceConnectionControls from './DeviceConnectionControls.vue'
import deviceArtwork from '../assets/theme/heater.webp'
import { computed } from 'vue'

const props = defineProps<{
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
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.header-tags { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.disconnect-alert { margin-bottom: 18px; }
.connection-feedback { margin-bottom: 16px; }
</style>
