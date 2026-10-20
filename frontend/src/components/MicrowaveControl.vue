<template>
  <el-card shadow="never" class="device-card microwave-card">
    <template #header>
      <div class="card-header">
        <div class="device-heading"><img :src="deviceArtwork" alt="" /><div><h2>微波仪</h2><span>{{ microwaveId }} 控制</span></div></div>
        <div class="header-tags">
          <el-tag :type="microwave.connected ? 'success' : 'info'">{{ microwave.connected ? '已连接' : '未连接' }}</el-tag>
          <el-tag v-if="microwave.connected" :type="statusTagType">{{ statusText }}</el-tag>
        </div>
        <DeviceConnectionControls :device-key="'microwave:'+microwaveId" :connected="microwave.connected" :loading="microwave.loading" :connect-disabled="microwave.bindingResolved === false" hint="确认停止后断开" @connect="$emit('connect', microwaveId)" @disconnect="$emit('disconnect', microwaveId)" />
      </div>
    </template>

    <el-alert v-if="microwave.connectionError" :title="microwave.connectionError" type="error" :closable="false" show-icon class="connection-feedback" />

    <el-alert
      title="启动前请确认炉门关闭、反应瓶与探头安装正确，并安排现场看护。软件无法确认炉门状态。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

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

    </div>

    <div class="fault-row">
      <el-tag :type="faultCode ? 'danger' : 'info'" size="small">
        故障码 {{ faultCode ?? '未知' }}
      </el-tag>
      <span v-if="faultCode === null" class="fault-text">故障状态未知，请连接设备并读取状态。</span>
      <span v-else-if="realtime?.faults?.length" class="fault-text">{{ realtime.faults.join('、') }}</span>
      <span v-else-if="faultCode" class="fault-text">协议未提供故障位释义，请按设备面板和说明书复核。</span>
      <span v-else class="fault-text">无故障码</span>
    </div>
      <div v-if="hostProgram && (hostProgram.state !== 'idle' || hostProgram.status_error || hostProgram.recovery_required)" class="program-notice">
        <p>托管状态：{{ hostStateLabel }} · 逻辑段 {{ hostProgram.current_stage || 0 }}/{{ hostProgram.total_stages || 0 }} · {{ phaseLabel }}</p>
        <MicrowaveHoldProgress :activity="hostProgram.activity" />
        <el-alert v-if="hostProgram.error || hostProgram.status_error" :title="hostProgram.error || hostProgram.status_error" type="error" :closable="false" />
        <el-button v-if="hostProgram.recovery_required" type="warning" @click="$emit('recover', microwaveId)">现场确认停止后解除锁定</el-button>
      </div>
    <details class="device-details">
      <summary>设备详情与通信状态</summary>
      <div class="status-tags">
        <span>串口 {{ connectionPort }}</span><span v-if="showBindingLabel">{{ bindingLabel }}</span>
        <el-tag :type="bindingTagType" size="small">{{ bindingTagText }}</el-tag>
        <span v-if="realtime?.binding_match_count !== undefined">匹配数 {{ realtime.binding_match_count }}</span>
        <el-button size="small" :loading="microwave.refreshing" @click="$emit('refresh', microwaveId)">刷新状态</el-button>
      </div>
      <div class="realtime-grid">      <div class="metric">
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
      </div></div>
    </details>
    <h3 class="section-title">程序设置</h3>
    <el-form label-width="88px" size="default">
      <el-form-item label="模式">
        <el-radio-group v-model="microwave.mode" :disabled="settingsDisabled">
          <el-radio-button value="auto_power">自动功率</el-radio-button>
          <el-radio-button value="manual_power">手动功率</el-radio-button>
        </el-radio-group>
        <span class="mode-help">{{ microwave.mode === 'auto_power' ? '设置目标温度，设备自动调节功率' : '设置目标温度与输出功率' }}</span>
      </el-form-item>

      <el-form-item label="程序段">
        <span>本次共 {{ microwave.usedSegments }} 段</span>
        <el-button :disabled="settingsDisabled || microwave.usedSegments >= 5" @click="addSegment">添加一段</el-button>
        <span class="unit-label">最多 5 段</span>
      </el-form-item>
      <el-alert class="program-notice" type="info" :closable="false" title="电脑托管：目标 ±3℃ 内连续稳定 30 秒后定时保温，之后温度偏离不暂停计时，段间确认停机。运行期间请保持服务运行并现场看护。" />
      <div class="segments-table" :class="{ 'multiple-segments': microwave.usedSegments > 1 }">
      <section v-for="segment in activeSegments" :key="segment.segment" class="program-segment">
        <div class="segment-heading">
          <h4>第 {{ segment.segment }} 段</h4>
          <el-button v-if="segment.segment === microwave.usedSegments && microwave.usedSegments > 1" :disabled="settingsDisabled" @click="removeSegment">移除本段</el-button>
        </div>
        <el-form-item label="目标温度">
          <el-input-number
            v-model="segment.temperature"
            :disabled="settingsDisabled"
            :min="0"
            :max="300"
            :step="1"
            style="width: 140px"
          />
          <span class="unit-label">℃（整数）</span>
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

      </div>
      <div class="run-controls">
      <p class="check-hint">{{ programConfigured ? '参数检查通过，可以启动；启动前仍需现场确认' : '请先检查程序；检查只校验参数，不启动设备' }}</p>
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
          启动程序
        </el-button>
        <el-button
          type="danger"
          plain
          class="stop-button"
          @click="$emit('stop', microwaveId)"
          :loading="microwave.stopping"
        >
          停止
        </el-button>

      </el-form-item>
      </div>
    </el-form>


  </el-card>
</template>

<script setup lang="ts">
import MicrowaveHoldProgress from './MicrowaveHoldProgress.vue'
import DeviceConnectionControls from './DeviceConnectionControls.vue'
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
    recovery_required?: boolean; cleanup_pending?: boolean; status_error?: string; error?: string;
    activity?: InstanceType<typeof MicrowaveHoldProgress>['$props']['activity'] }
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
const phaseLabel = computed(() => ({ configure: '配置当前逻辑段', heat: '等待稳定到温', hold: '定时保温', stop: '确认停止',
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
const faultCode = computed(() => props.microwave.connected && !props.realtime?.error && typeof props.realtime?.fault_code === 'number' && Number.isFinite(props.realtime.fault_code) ? props.realtime.fault_code : null)

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
  if (!props.microwave.connected) return 'info'
  if (props.realtime?.error) return 'danger'
  if (faultCode.value) return 'danger'
  if (props.realtime?.control_active || props.realtime?.output_active) return 'success'
  if (!props.realtime?.status_confirmed) return 'warning'
  return 'info'
})

const statusText = computed(() => {
  if (!props.microwave.connected) return '未连接'
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
.section-title { margin: 20px 0 16px; font-size: 16px; color: #245483; }
.device-details { margin-top: 16px; padding: 12px; background: #f5f8fc; border-radius: 8px; font-size: 13px; color: #52647a; }
.device-details summary { cursor: pointer; }
.device-details[open] summary { margin-bottom: 12px; }
.mode-help { margin-left: 12px; font-size: 13px; color: #606266; }
.run-controls { position: sticky; bottom: 0; background: #f4f8ff; border: 1px solid #dce8fa; border-radius: 8px; padding: 12px 12px 1px; z-index: 2; }
.check-hint { margin: 0 0 12px; font-size: 13px; color: #52647a; }
.stop-button { margin-left: 24px !important; }
.multiple-segments .program-segment { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 12px; margin-bottom: 8px; align-items: center; }
.multiple-segments .segment-heading { width: 100%; margin-bottom: 4px; }
.multiple-segments :deep(.el-form-item) { margin-bottom: 6px; }
.realtime-grid > .metric:first-child .metric-value { color: #1d5c9e; font-size: 26px; }
@media (max-width: 700px) { .card-header { flex-wrap: wrap; } .mode-help { margin: 8px 0 0; } .time-row { gap: 4px; } }
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
