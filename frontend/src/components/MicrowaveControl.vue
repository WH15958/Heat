<template>
  <el-card shadow="hover" style="margin-bottom: 20px">
    <template #header>
      <div class="card-header">
        <span>微波仪 {{ microwaveId }} 控制</span>
        <div class="header-tags">
          <el-tag :type="microwave.connected ? 'success' : 'info'" size="small">
            {{ microwave.connected ? '已连接' : '未连接' }}
          </el-tag>
          <el-tag :type="controlWritesEnabled ? 'success' : 'warning'" size="small">
            {{ controlWritesEnabled ? '控制写入已启用' : '控制写入禁用' }}
          </el-tag>
        </div>
      </div>
    </template>

    <el-alert
      v-if="!controlWritesEnabled"
      title="后端安全开关 enable_control_writes=false：配置和真实启动保持禁用；连接、读取和人工停止仍需明确点击。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <el-form label-width="88px" size="default">
      <el-form-item label="连接">
        <el-button v-if="!microwave.connected" type="primary" @click="$emit('connect', microwaveId)" :loading="microwave.loading">
          连接设备
        </el-button>
        <el-button v-else type="danger" @click="$emit('disconnect', microwaveId)" :loading="microwave.loading">
          断开连接
        </el-button>
        <el-button
          style="margin-left: 8px"
          @click="$emit('refresh', microwaveId)"
          :disabled="!microwave.connected"
          :loading="microwave.refreshing"
        >
          刷新状态
        </el-button>
      </el-form-item>

      <el-form-item label="安全状态">
        <div class="status-tags">
          <el-tag :type="experimentControlEnabled ? 'warning' : 'info'" size="small">
            {{ experimentControlEnabled ? '实验自动控制已启用' : '实验自动控制禁用' }}
          </el-tag>
          <el-tag v-if="realtime?.error" type="danger" size="small">读取失败</el-tag>
          <el-tag v-else :type="statusTagType" size="small">{{ statusText }}</el-tag>
        </div>
      </el-form-item>

      <el-form-item label="模式">
        <el-select v-model="microwave.mode" style="width: 160px">
          <el-option v-for="mode in MICROWAVE_MODES" :key="mode.value" :label="mode.label" :value="mode.value" />
        </el-select>
      </el-form-item>

      <el-form-item label="配置段">
        <el-select v-model="microwave.selectedSegment" style="width: 120px">
          <el-option v-for="segment in [1, 2, 3, 4, 5]" :key="segment" :label="`第 ${segment} 段`" :value="segment" />
        </el-select>
      </el-form-item>

      <el-form-item label="温度">
        <el-input-number
          v-model="currentSegment.temperature"
          :min="0"
          :max="300"
          :step="1"
          :precision="1"
          style="width: 140px"
        />
        <span class="unit-label">°C</span>
      </el-form-item>

      <el-form-item v-if="microwave.mode === 'manual_power'" label="功率">
        <el-input-number
          v-model="currentSegment.powerPercent"
          :min="0"
          :max="100"
          :step="1"
          style="width: 140px"
        />
        <span class="unit-label">%</span>
      </el-form-item>

      <el-form-item label="时间">
        <div class="time-row">
          <el-input-number v-model="currentSegment.hours" :min="0" :max="99" :step="1" size="small" style="width: 86px" />
          <span class="unit-label">时</span>
          <el-input-number v-model="currentSegment.minutes" :min="0" :max="59" :step="1" size="small" style="width: 86px" />
          <span class="unit-label">分</span>
          <el-input-number v-model="currentSegment.seconds" :min="0" :max="59" :step="1" size="small" style="width: 86px" />
          <span class="unit-label">秒</span>
        </div>
      </el-form-item>

      <el-form-item label="运行控制">
        <el-button
          type="primary"
          @click="$emit('configure', microwaveId)"
          :disabled="!microwave.connected || !controlWritesEnabled"
          :loading="microwave.configuring"
        >
          配置
        </el-button>
        <el-button
          type="success"
          @click="$emit('start', microwaveId)"
          :disabled="!microwave.connected || !controlWritesEnabled"
          :loading="microwave.starting"
        >
          启动
        </el-button>
        <el-button
          type="warning"
          @click="$emit('stop', microwaveId)"
          :disabled="!microwave.connected"
          :loading="microwave.stopping"
        >
          停止
        </el-button>
      </el-form-item>
    </el-form>

    <div class="realtime-grid">
      <div class="metric">
        <span class="metric-label">物料温度</span>
        <span class="metric-value">{{ formatNumber(realtime?.material_temperature, 1, '°C') }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">当前功率</span>
        <span class="metric-value">{{ formatNumber(realtime?.power_percent, 0, '%') }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">电流</span>
        <span class="metric-value">{{ formatNumber(realtime?.current, 2, 'A') }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">运行时间</span>
        <span class="metric-value">{{ formatRuntime(realtime?.runtime_seconds) }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">当前段</span>
        <span class="metric-value">{{ realtime?.current_segment ?? '--' }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">当前模式</span>
        <span class="metric-value">{{ modeLabel(realtime?.mode) }}</span>
      </div>
    </div>

    <div class="fault-row">
      <el-tag :type="faultCode ? 'danger' : 'info'" size="small">
        故障码 {{ faultCode }}
      </el-tag>
      <span v-if="realtime?.faults?.length" class="fault-text">{{ realtime.faults.join('、') }}</span>
      <span v-else-if="faultCode" class="fault-text">协议未提供故障位释义，请按设备面板和说明书复核。</span>
      <span v-else class="fault-text">无故障码</span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { MICROWAVE_MODES, type MicrowaveMode } from '../api/devices'
import type { MicrowaveRealtimeData } from '../composables/useWebSocket'

type TagType = 'success' | 'warning' | 'info' | 'danger'

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
  allowExperimentControl: boolean
  enableControlWrites: boolean
  segments: Record<number, MicrowaveSegmentConfig>
}

const props = defineProps<{
  microwaveId: string
  microwave: MicrowaveDeviceState
  realtime: MicrowaveRealtimeData | null
}>()

defineEmits<{
  connect: [id: string]
  disconnect: [id: string]
  refresh: [id: string]
  configure: [id: string]
  start: [id: string]
  stop: [id: string]
}>()

const currentSegment = computed(() => props.microwave.segments[props.microwave.selectedSegment] ?? props.microwave.segments[1])
const controlWritesEnabled = computed(() => props.realtime?.enable_control_writes ?? props.microwave.enableControlWrites)
const experimentControlEnabled = computed(() => props.realtime?.allow_experiment_control ?? props.microwave.allowExperimentControl)
const faultCode = computed(() => Number(props.realtime?.fault_code ?? 0))

const statusTagType = computed<TagType>(() => {
  if (props.realtime?.error) return 'danger'
  if (faultCode.value) return 'danger'
  if (props.realtime?.running) return 'success'
  return 'info'
})

const statusText = computed(() => {
  if (faultCode.value) return '异常'
  if (props.realtime?.running) return '运行中'
  return '停止'
})

function modeLabel(mode: string | undefined): string {
  const found = MICROWAVE_MODES.find(item => item.value === mode)
  if (found) return found.label
  return mode || '--'
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
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.header-tags,
.status-tags,
.time-row,
.fault-row {
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
.realtime-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.metric {
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
.fault-row {
  margin-top: 12px;
}
.fault-text {
  color: #606266;
  font-size: 13px;
}
</style>
