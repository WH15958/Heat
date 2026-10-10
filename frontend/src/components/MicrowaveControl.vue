<template>
  <el-card shadow="never" class="device-card microwave-card">
    <template #header>
      <div class="card-header">
        <div class="device-heading"><img :src="deviceArtwork" alt="" /><div><h2>微波仪</h2><span>{{ microwaveId }} 控制</span></div></div>
        <div class="header-tags">
          <el-tag type="info" size="small">串口 {{ connectionPort }}</el-tag>
          <el-tag v-if="showBindingLabel" type="info" size="small">{{ bindingLabel }}</el-tag>
          <el-tag :type="bindingTagType" size="small">{{ bindingTagText }}</el-tag>
          <el-tag :type="microwave.connected ? 'success' : 'info'" size="small">
            {{ microwave.connected ? '已连接' : '未连接' }}
          </el-tag>
          <el-tag type="success" size="small">配置写入可用</el-tag>
          <el-tag type="warning" size="small">启动/停止可用</el-tag>
        </div>
      </div>
    </template>

    <el-alert v-if="microwave.connectionError" :title="microwave.connectionError" type="error" :closable="false" show-icon class="connection-feedback" />

    <el-alert
      title="操作前请人工检查炉门、反应瓶、探头、设备绑定身份、当前解析串口和现场看护。协议当前没有可靠门状态寄存器，软件不会伪造 door_closed。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <el-form label-width="88px" size="default">
      <el-form-item label="连接">
        <el-button v-if="!microwave.connected" type="primary" @click="$emit('connect', microwaveId)" :loading="microwave.loading">
          {{ microwave.loading ? '连接中…' : '连接设备' }}
        </el-button>
        <el-button v-else type="danger" @click="$emit('disconnect', microwaveId)" :loading="microwave.loading">
          {{ microwave.loading ? '断开中…' : '断开连接' }}
        </el-button>
        <el-button
          style="margin-left: 8px"
          @click="$emit('refresh', microwaveId)"
          :loading="microwave.refreshing"
        >
          刷新状态
        </el-button>
      </el-form-item>

      <el-form-item label="绑定状态">
        <div class="status-tags">
          <el-tag :type="bindingTagType" size="small">{{ bindingTagText }}</el-tag>
          <el-tag v-if="realtime?.binding_match_count !== undefined" type="info" size="small">
            匹配数 {{ realtime.binding_match_count }}
          </el-tag>
          <el-tag :type="statusTagType" size="small">{{ statusText }}</el-tag>
        </div>
      </el-form-item>

      <el-form-item label="模式">
        <el-select v-model="microwave.mode" :disabled="settingsDisabled" style="width: 160px">
          <el-option v-for="mode in MICROWAVE_MODES.filter(m => m.value !== 'constant_rate')" :key="mode.value" :label="mode.label" :value="mode.value" />
        </el-select>
      </el-form-item>

      <el-form-item label="程序段">
        <span>本次共 {{ microwave.usedSegments }} 段</span>
        <el-button :disabled="settingsDisabled || microwave.usedSegments >= 5" @click="addSegment">添加一段</el-button>
        <span class="unit-label">最多 5 段</span>
      </el-form-item>
      <el-alert class="program-notice" type="info" :closable="false" title="电脑托管：每段到温后计时保温，确认停止后进入下一段。无需设置触摸屏执行范围，段间会短暂停机；运行期间须保持后端服务运行并现场看护。" />
      <div v-if="hostProgram && (hostProgram.state !== 'idle' || hostProgram.status_error || hostProgram.recovery_required)" class="program-notice">
        <p>托管状态：{{ hostStateLabel }} · 逻辑段 {{ hostProgram.current_stage || 0 }}/{{ hostProgram.total_stages || 0 }} · {{ phaseLabel }}</p>
        <el-alert v-if="hostProgram.error || hostProgram.status_error" :title="hostProgram.error || hostProgram.status_error" type="error" :closable="false" />
        <el-button v-if="hostProgram.recovery_required" type="warning" @click="$emit('recover', microwaveId)">现场确认停止后解除锁定</el-button>
      </div>
      <section v-for="segment in activeSegments" :key="segment.segment" class="program-segment">
        <div class="segment-heading">
          <h4>第 {{ segment.segment }} 段</h4>
          <el-button v-if="segment.segment === microwave.usedSegments && microwave.usedSegments > 1" :disabled="settingsDisabled" @click="removeSegment">移除本段</el-button>
        </div>
        <el-form-item label="温度">
          <el-input-number
            v-model="segment.temperature"
            :disabled="settingsDisabled"
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
            v-model="segment.powerPercent"
            :disabled="settingsDisabled"
            :min="0"
            :max="100"
            :step="1"
            style="width: 140px"
          />
          <span class="unit-label">%</span>
        </el-form-item>

        <el-form-item label="保温时间">
          <div class="time-row">
            <el-input-number v-model="segment.hours" :disabled="settingsDisabled" :min="0" :max="99" :step="1" size="small" style="width: 86px" />
            <span class="unit-label">时</span>
            <el-input-number v-model="segment.minutes" :disabled="settingsDisabled" :min="0" :max="59" :step="1" size="small" style="width: 86px" />
            <span class="unit-label">分</span>
            <el-input-number v-model="segment.seconds" :disabled="settingsDisabled" :min="0" :max="59" :step="1" size="small" style="width: 86px" />
            <span class="unit-label">秒</span>
          </div>
        </el-form-item>

      </section>

      <el-form-item label="运行控制">
        <el-button
          type="primary"
          @click="$emit('configure', microwaveId)"
          :loading="microwave.configuring"
          :disabled="settingsDisabled || !microwave.connected"
        >
          检查程序
        </el-button>
        <el-button
          type="success"
          @click="$emit('start', microwaveId)"
          :loading="microwave.starting"
          :disabled="settingsDisabled || !microwave.connected || !programConfigured || !hostProgram || hostProgram.status_error || hostProgram.recovery_required"
        >
          启动托管程序
        </el-button>
        <el-button
          type="warning"
          @click="$emit('stop', microwaveId)"
          :loading="microwave.stopping"
        >
          停止
        </el-button>
        <span class="unit-label">{{ programConfigured ? '程序已检查，启动后由后端逐段执行' : '请先检查程序；修改参数后重新检查' }}</span>
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
        <span class="metric-label">硬件当前段</span>
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
import deviceArtwork from '../assets/theme/microwave.webp'
import { computed } from 'vue'
import { MICROWAVE_MODES, type MicrowaveMode } from '../api/devices'
import type { MicrowaveRealtimeData } from '../composables/useWebSocket'
import { microwaveProgramConfigured, type MicrowaveProgram } from '../utils/microwaveProgram'

type TagType = 'success' | 'warning' | 'info' | 'danger'

interface MicrowaveDeviceState extends MicrowaveProgram {
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
}

const props = defineProps<{
  microwaveId: string
  microwave: MicrowaveDeviceState
  realtime: MicrowaveRealtimeData | null
  hostProgram?: { state: string; current_stage?: number; total_stages?: number; phase?: string;
    recovery_required?: boolean; cleanup_pending?: boolean; status_error?: string; error?: string }
}>()

defineEmits<{
  connect: [id: string]
  disconnect: [id: string]
  refresh: [id: string]
  configure: [id: string]
  start: [id: string]
  stop: [id: string]
  recover: [id: string]
}>()

const activeSegments = computed(() => Array.from({ length: props.microwave.usedSegments }, (_, index) => props.microwave.segments[index + 1]!))
const programConfigured = computed(() => microwaveProgramConfigured(props.microwave))
const settingsDisabled = computed(() => props.microwave.configuring || props.microwave.starting
  || Boolean(props.realtime?.control_active || props.realtime?.output_active)
  || props.hostProgram?.state === 'running' || props.hostProgram?.state === 'paused')
const hostStateLabel = computed(() => ({ running: '运行中', completed: '完成', failed: '失败',
  stopped: '已停止', interrupted: '服务中断，需恢复确认' }[props.hostProgram?.state || ''] || props.hostProgram?.state))
const phaseLabel = computed(() => ({ configure: '配置当前逻辑段', heat: '等待到温', hold: '计时保温', stop: '确认停止',
  completed: '全部段完成', failed: '失败', stopped: '已停止', acknowledged: '已人工解除锁定' }[props.hostProgram?.phase || ''] || '等待确认'))
function addSegment() {
  if (!settingsDisabled.value && props.microwave.usedSegments < 5) props.microwave.usedSegments++
}

function removeSegment() {
  if (!settingsDisabled.value && props.microwave.usedSegments > 1) props.microwave.usedSegments--
}

const connectionPort = computed(() => props.realtime?.connection_port ?? props.microwave.connectionPort ?? '--')
const bindingMode = computed(() => props.realtime?.connection_binding_mode ?? props.microwave.bindingMode ?? 'fixed_port')
const bindingLabel = computed(() => props.realtime?.binding_label ?? props.microwave.bindingLabel ?? '未配置绑定')
const bindingResolved = computed(() => props.realtime?.binding_resolved ?? props.microwave.bindingResolved ?? true)
const bindingError = computed(() => props.realtime?.binding_error ?? props.microwave.bindingError ?? null)
const faultCode = computed(() => Number(props.realtime?.fault_code ?? 0))

const bindingTagType = computed<TagType>(() => {
  if (bindingResolved.value === false) return 'danger'
  if (bindingError.value === 'fallback_to_port') return 'warning'
  return 'success'
})

const bindingTagText = computed(() => {
  if (bindingResolved.value === false) return '未匹配'
  if (bindingError.value === 'fallback_to_port') return '端口回退'
  return '已匹配'
})

const showBindingLabel = computed(() => bindingMode.value === 'fingerprint' && Boolean(bindingLabel.value))

const statusTagType = computed<TagType>(() => {
  if (props.realtime?.error) return 'danger'
  if (faultCode.value) return 'danger'
  if (props.realtime?.control_active || props.realtime?.output_active) return 'success'
  if (!props.realtime?.status_confirmed) return 'warning'
  return 'info'
})

const statusText = computed(() => {
  if (faultCode.value) return '异常'
  if (props.realtime?.error) return '状态未知'
  if (props.realtime?.control_active || props.realtime?.output_active) return '运行中'
  if (props.realtime?.stop_confirmed) return '已确认停止'
  return '状态未知'
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
.connection-feedback { margin-bottom: 12px; }
.program-notice { margin-bottom: 18px; }
.program-segment { padding: 16px; margin-bottom: 16px; border: 1px solid var(--el-border-color-light); border-radius: 8px; }
.segment-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.segment-heading h4 { margin: 0; }
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
