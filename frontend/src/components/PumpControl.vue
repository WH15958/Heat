<template>
  <el-card shadow="never" class="device-card pump-card">
    <template #header>
      <div class="card-header">
        <div class="device-heading"><img :src="deviceArtwork" alt="" /><div><h2>蠕动泵</h2><span>{{ pumpId }} 控制</span></div></div>
        <div class="header-tags">
          <el-tag :type="pump.connectionError ? 'danger' : pump.connected ? 'success' : 'info'" size="small" style="margin-right: 8px">
            {{ pump.connectionError ? '连接异常' : pump.connected ? '已连接' : '未连接' }}
          </el-tag>

        </div>
        <DeviceConnectionControls :device-key="'pump:'+pumpId" :connected="pump.connected" :loading="pump.loading" :connect-disabled="pump.bindingResolved === false" hint="停止各通道后断开" @connect="$emit('connect', pumpId)" @disconnect="$emit('disconnect', pumpId)" />
      </div>
    </template>

    <el-alert v-if="pump.connectionError" :title="pump.connectionError" type="error" :closable="false" show-icon class="connection-feedback" />

    <el-alert
      title="蠕动泵开机后请检查通信参数设置（波特率、校验位、软管型号），确保与实际配置一致后再操作"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

    <details class="device-details"><summary>设备详情与通信配置</summary><div class="detail-tags">          <el-tag type="info" size="small" style="margin-right: 8px">串口 {{ pump.connectionPort || '--' }}</el-tag>
          <el-tag v-if="showBindingLabel" type="info" size="small" style="margin-right: 8px">{{ pump.bindingLabel }}</el-tag>
          <el-tag :type="bindingTagType" size="small" style="margin-right: 8px">{{ bindingTagText }}</el-tag></div></details>
    <p class="setting-caption">以下为待下发设置，点击启动后执行；通道标题显示设备当前读回状态。</p>
    <div class="channels-grid">
    <div v-for="ch in [1, 2, 3, 4]" :key="ch" class="channel-control">
      <div class="channel-header">
        <span class="channel-name">通道 {{ ch }}</span>
        <el-tag v-if="pump.connected && channelStatus(pumpId, ch)?.read_ok === false" type="danger" size="small">
          读取失败
        </el-tag>
        <el-tag v-else-if="pump.connected && channelStatus(pumpId, ch)?.read_ok === true && channelStatus(pumpId, ch)?.running" type="success" size="small">
          运行中 {{ channelStatus(pumpId, ch)?.flow_rate }} {{ statusFlowUnitLabel(channelStatus(pumpId, ch)?.flow_unit) }}
        </el-tag>
        <el-tag v-else-if="pump.connected && channelStatus(pumpId, ch)?.read_ok === true && channelStatus(pumpId, ch)?.run_status === 'PAUSE'" type="warning" size="small">暂停</el-tag>
        <el-tag v-else-if="pump.connected && channelStatus(pumpId, ch)?.read_ok === true && channelStatus(pumpId, ch)?.run_status === 'STOP'" type="info" size="small">停止</el-tag>
        <el-tag v-else-if="pump.connected" type="warning" size="small">状态未知</el-tag>
        <el-tag v-else type="info" size="small">未连接</el-tag>
      </div>
      <div class="channel-fields">
        <label class="control-field"><span>运行模式</span><el-select v-model="pump.channels[ch].mode"><el-option v-for="m in PUMP_MODES" :key="m.value" :label="m.label" :value="m.value" /></el-select></label>
        <label class="control-field"><span>软管型号</span><el-select v-model="pump.channels[ch].tubeModel" @change="onTubeModelChange(pump.channels[ch])"><el-option v-for="t in TUBE_MODELS" :key="t.value" :label="`${t.label} (${t.value})`" :value="t.value" /></el-select></label>
        <div class="control-field full-field"><label :for="`${pumpId}-${ch}-flow`">{{ pump.channels[ch].mode === 'TIME_QUANTITY' ? '计算流量（由体积与时间换算）' : '设定流量' }}</label><div class="field-value">
          <template v-if="pump.channels[ch].mode === 'TIME_QUANTITY'"><el-input-number :id="`${pumpId}-${ch}-flow`" :model-value="calcFlowRate(pump.channels[ch])" disabled :precision="2" /><span>mL/min</span></template>
          <template v-else><el-input-number :id="`${pumpId}-${ch}-flow`" v-model="pump.channels[ch].flowRate" :min="0.01" :max="flowRateMax(pump.channels[ch])" :step="0.01" :precision="3" /><el-select v-model="pump.channels[ch].flowUnit" aria-label="流量单位" @change="clampFlowRate(pump.channels[ch])"><el-option v-for="u in FLOW_UNITS" :key="u.value" :label="u.label" :value="u.value" :disabled="!isFlowUnitAvailable(pump.channels[ch], u.value)" /></el-select></template>
        </div></div>
        <div class="control-field full-field"><span>旋转方向</span><el-radio-group v-model="pump.channels[ch].direction"><el-radio-button value="CW">顺时针</el-radio-button><el-radio-button value="CCW">逆时针</el-radio-button></el-radio-group></div>
        <div v-if="needsRunTime(pump.channels[ch].mode)" class="control-field full-field"><label :for="`${pumpId}-${ch}-time`">运行时间</label><div class="field-value"><el-input-number :id="`${pumpId}-${ch}-time`" v-model="pump.channels[ch].runTime" :min="0.1" :max="9999" :step="1" :precision="1" /><el-select v-model="pump.channels[ch].timeUnit" aria-label="运行时间单位"><el-option v-for="u in TIME_UNITS" :key="u.value" :label="u.label" :value="u.value" /></el-select></div></div>
        <div v-if="needsDispenseVolume(pump.channels[ch].mode)" class="control-field full-field"><label :for="`${pumpId}-${ch}-volume`">目标体积</label><div class="field-value"><el-input-number :id="`${pumpId}-${ch}-volume`" v-model="pump.channels[ch].dispenseVolume" :min="0.01" :max="9999" :step="1" :precision="2" /><el-select v-model="pump.channels[ch].volumeUnit" aria-label="体积单位"><el-option v-for="u in VOLUME_UNITS" :key="u.value" :label="u.label" :value="u.value" /></el-select></div></div>
        <template v-if="pump.channels[ch].mode !== 'FLOW_MODE'">
          <label class="control-field"><span>重复次数（0 为无限）</span><el-input-number v-model="pump.channels[ch].repeatCount" :min="0" :max="9999" :step="1" /></label>
          <div class="control-field full-field"><label :for="`${pumpId}-${ch}-interval`">循环间隔</label><div class="field-value"><el-input-number :id="`${pumpId}-${ch}-interval`" v-model="pump.channels[ch].intervalTime" :min="0" :max="9999" :step="0.1" :precision="1" /><el-select v-model="pump.channels[ch].intervalTimeUnit" aria-label="间隔时间单位"><el-option v-for="u in TIME_UNITS" :key="u.value" :label="u.label" :value="u.value" /></el-select></div></div>
        </template>
      </div>
      <div class="channel-actions"><el-button type="success" @click="$emit('startChannel', pumpId, ch)" :loading="pump.channels[ch].starting">启动通道 {{ ch }}</el-button><el-button type="danger" plain @click="$emit('stopChannel', pumpId, ch)" :loading="pump.channels[ch].stopping">停止</el-button></div>
      <el-collapse class="priming-collapse">
        <el-collapse-item name="priming">
          <template #title>
            <span class="priming-title">预灌估算</span>
          </template>
          <div class="segment-list">
            <div
              v-for="(_lengthCm, segmentIndex) in pump.channels[ch].tubeSegmentLengthsCm"
              :key="segmentIndex"
              class="segment-row"
            >
              <span class="segment-label">管段 {{ segmentIndex + 1 }}</span>
              <el-input-number
                v-model="pump.channels[ch].tubeSegmentLengthsCm[segmentIndex]"
                :min="0.1"
                :step="1"
                :precision="1"
                size="small"
                controls-position="right"
                placeholder="长度"
                class="segment-length-input"
              />
              <span class="unit-label">cm</span>
              <el-button
                type="danger"
                link
                size="small"
                :disabled="pump.channels[ch].tubeSegmentLengthsCm.length === 1"
                @click="removeTubeSegment(pump.channels[ch], segmentIndex)"
              >
                删除
              </el-button>
            </div>
            <el-button type="primary" link size="small" @click="addTubeSegment(pump.channels[ch])">
              添加管段
            </el-button>
          </div>

          <div class="priming-results">
            <div class="result-item">
              <span class="result-label">软管内径</span>
              <strong>{{ tubeInnerDiameter(pump.channels[ch]).toFixed(2) }} mm</strong>
            </div>
            <div class="result-item">
              <span class="result-label">总长度</span>
              <strong>{{ totalTubeLengthCm(pump.channels[ch]).toFixed(1) }} cm</strong>
            </div>
            <div class="result-item">
              <span class="result-label">理论死体积</span>
              <strong>{{ deadVolumeMl(pump.channels[ch]).toFixed(4) }} mL</strong>
            </div>
            <div class="result-item">
              <span class="result-label">有效流量</span>
              <strong>{{ effectiveFlowLabel(pump.channels[ch]) }}</strong>
            </div>
            <div class="result-item result-item-wide">
              <span class="result-label">理论预灌时间</span>
              <strong>{{ primingTimeLabel(pump.channels[ch]) }}</strong>
            </div>
          </div>
          <el-alert
            title="理论估算不包含接头、反应器、气泡、管路弹性、背压和安全余量，实际操作请以标定结果为准。"
            type="info"
            :closable="false"
            show-icon
            class="priming-note"
          />
        </el-collapse-item>
      </el-collapse>
    </div>

    </div>
    <div class="pump-stop-all">
      <el-button type="danger" plain size="small" @click="$emit('stopAll', pumpId)" :loading="pump.stoppingAll">
        停止所有通道
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import DeviceConnectionControls from './DeviceConnectionControls.vue'
import deviceArtwork from '../assets/theme/pump.webp'
import { computed } from 'vue'
import { PUMP_MODES, TUBE_MODELS, FLOW_UNITS, TIME_UNITS, VOLUME_UNITS, type PumpMode } from '../api/devices'
import { calculateDeadVolumeMl, calculatePrimingTimeSeconds, convertFlowToMlMin } from '../utils/pumpCalculations'

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

const props = defineProps<{
  pumpId: string
  pump: {
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
  channelStatus: (pumpId: string, ch: number) => any
}>()

defineEmits<{
  connect: [id: string]
  disconnect: [id: string]
  startChannel: [pumpId: string, channel: number]
  stopChannel: [pumpId: string, channel: number]
  stopAll: [pumpId: string]
}>()

const bindingTagType = computed(() => {
  if (props.pump.bindingResolved === false) return 'danger'
  if (props.pump.bindingError === 'fallback_to_port') return 'warning'
  return 'success'
})

const bindingTagText = computed(() => {
  if (props.pump.bindingResolved === false) return '未匹配'
  if (props.pump.bindingError === 'fallback_to_port') return '端口回退'
  return '已匹配'
})

const showBindingLabel = computed(() => props.pump.bindingMode === 'fingerprint' && Boolean(props.pump.bindingLabel))

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

function addTubeSegment(ch: ChannelConfig) {
  ch.tubeSegmentLengthsCm.push(null)
}

function removeTubeSegment(ch: ChannelConfig, segmentIndex: number) {
  if (ch.tubeSegmentLengthsCm.length === 1) return
  ch.tubeSegmentLengthsCm.splice(segmentIndex, 1)
}

function tubeInnerDiameter(ch: ChannelConfig): number {
  return TUBE_MODELS.find(tube => tube.value === ch.tubeModel)?.innerDiameterMm ?? 0
}

function totalTubeLengthCm(ch: ChannelConfig): number {
  return ch.tubeSegmentLengthsCm.reduce<number>((total, lengthCm) => {
    return total + (typeof lengthCm === 'number' && Number.isFinite(lengthCm) && lengthCm > 0 ? lengthCm : 0)
  }, 0)
}

function deadVolumeMl(ch: ChannelConfig): number {
  return calculateDeadVolumeMl(tubeInnerDiameter(ch), ch.tubeSegmentLengthsCm)
}

function effectiveFlowMlMin(ch: ChannelConfig): number | null {
  if (ch.mode === 'TIME_QUANTITY') return convertFlowToMlMin(calcFlowRate(ch), 1)
  return convertFlowToMlMin(ch.flowRate, ch.flowUnit)
}

function effectiveFlowLabel(ch: ChannelConfig): string {
  const flowMlMin = effectiveFlowMlMin(ch)
  return flowMlMin === null ? 'RPM 无法换算' : `${flowMlMin.toFixed(4)} mL/min`
}

function primingTimeLabel(ch: ChannelConfig): string {
  if (ch.flowUnit === 3 && ch.mode !== 'TIME_QUANTITY') return 'RPM 模式不可计算'
  if (deadVolumeMl(ch) <= 0) return '请输入管段长度'
  const seconds = calculatePrimingTimeSeconds(deadVolumeMl(ch), effectiveFlowMlMin(ch))
  if (seconds === null) return '不可计算'
  return `${(seconds / 60).toFixed(2)} 分钟（${seconds.toFixed(1)} 秒）`
}

function statusFlowUnitLabel(unit: unknown): string {
  const labels: Record<string, string> = {
    UL_MIN: 'uL/min',
    ML_MIN: 'mL/min',
    L_MIN: 'L/min',
    RPM: 'RPM',
  }
  return typeof unit === 'string' ? labels[unit] || unit : '--'
}

function getMaxFlowRate(tubeModel: number): number {
  const found = TUBE_MODELS.find(t => t.value === tubeModel)
  return found ? found.maxFlow : 7.55
}

function flowRateMaxForUnit(maxFlowRate: number, flowUnit: number): number {
  if (flowUnit === 3) return 150
  const convertedMax = flowUnit === 0
    ? maxFlowRate * 1000
    : flowUnit === 2
      ? maxFlowRate / 1000
      : maxFlowRate
  return Math.min(convertedMax, 9999)
}

function flowRateMax(ch: ChannelConfig): number {
  const effectiveMaxFlowRate = Math.min(ch.maxFlowRate, getMaxFlowRate(ch.tubeModel))
  return flowRateMaxForUnit(effectiveMaxFlowRate, ch.flowUnit)
}

function isFlowUnitAvailable(ch: ChannelConfig, flowUnit: number): boolean {
  const effectiveMaxFlowRate = Math.min(ch.maxFlowRate, getMaxFlowRate(ch.tubeModel))
  return flowUnit === 3 || flowRateMaxForUnit(effectiveMaxFlowRate, flowUnit) >= 0.01
}

function clampFlowRate(ch: ChannelConfig) {
  ch.flowRate = Math.min(Math.max(ch.flowRate, 0.01), flowRateMax(ch))
}

function onTubeModelChange(ch: ChannelConfig) {
  if (!isFlowUnitAvailable(ch, ch.flowUnit)) {
    ch.flowUnit = [1, 0, 2].find(unit => isFlowUnitAvailable(ch, unit)) ?? 3
  }
  clampFlowRate(ch)
}
</script>

<style scoped>
.channels-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,330px),1fr)); gap: 16px; align-items: start; }
.channel-fields { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px 12px; }
.control-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; font-size: 13px; color: #425b73; }
.control-field :deep(.el-select), .control-field :deep(.el-input-number) { width: 100%; }
.full-field { grid-column: 1 / -1; }
.field-value { display: flex; align-items: center; gap: 8px; }
.field-value :deep(.el-input-number) { flex: 1; min-width: 0; }
.field-value :deep(.el-select) { width: 100px; flex: 0 0 100px; }
.channel-actions { display: flex; justify-content: space-between; gap: 16px; margin-top: 18px; border-top: 1px solid #e3ebf3; padding-top: 14px; }
.device-details { margin: 12px 0; padding: 12px; background: #f3f7fb; border-radius: 8px; font-size: 13px; }
.device-details summary { cursor: pointer; color: #425b73; }
.detail-tags { display:flex; gap: 8px; flex-wrap:wrap; margin-top:12px; }
.setting-caption { color: #526b83; font-size:13px; line-height:1.7; }
.pump-stop-all { position: sticky; bottom: 12px; margin-top: 16px; padding: 12px; border: 1px solid #f3d2d2; border-radius: 10px; background: #fffafa; text-align:right; z-index: 2; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.connection-feedback { margin-bottom: 12px; }
.channel-control {
  padding: 16px;
  border: 1px solid #dce7f1;
  border-radius: 12px;
  background: #fbfdff;
  min-width: 0;
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
.param-label {
  color: #606266;
  font-size: 12px;
  white-space: nowrap;
  margin-right: 2px;
}
.priming-collapse {
  margin-top: 8px;
  border-bottom: none;
}
.priming-title {
  color: #409eff;
  font-size: 13px;
  font-weight: 600;
}
.segment-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.segment-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.segment-label {
  color: #606266;
  font-size: 12px;
  min-width: 48px;
}
.segment-length-input {
  width: 130px;
}
.priming-results {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 8px 16px;
  margin-top: 10px;
  padding: 10px 0;
  border-top: 1px solid #ebeef5;
}
.result-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  font-size: 12px;
}
.result-item strong {
  color: #303133;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.result-label {
  color: #909399;
}
.priming-note {
  margin-top: 2px;
}
:deep(.priming-collapse .el-collapse-item__header) {
  height: 34px;
  line-height: 34px;
}
:deep(.priming-collapse .el-collapse-item__content) {
  padding-bottom: 8px;
}
</style>
