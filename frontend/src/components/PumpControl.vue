<template>
  <el-card shadow="hover" style="margin-bottom: 20px">
    <template #header>
      <div class="card-header">
        <span>蠕动泵 {{ pumpId }} 控制</span>
        <div>
          <el-tag :type="pump.connected ? 'success' : 'info'" size="small" style="margin-right: 8px">
            {{ pump.connected ? '已连接' : '未连接' }}
          </el-tag>
          <el-button v-if="!pump.connected" type="primary" size="small" @click="$emit('connect', pumpId)" :loading="pump.loading">
            连接
          </el-button>
          <el-button v-else type="danger" size="small" @click="$emit('disconnect', pumpId)" :loading="pump.loading">
            断开
          </el-button>
        </div>
      </div>
    </template>

    <el-alert
      title="蠕动泵开机后请检查通信参数设置（波特率、校验位、软管型号），确保与实际配置一致后再操作"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />

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
        <el-select v-model="pump.channels[ch].tubeModel" size="small" style="width: 130px" :disabled="!pump.connected" @change="onTubeModelChange(pump.channels[ch])">
          <el-option v-for="t in TUBE_MODELS" :key="t.value" :label="`${t.label} (${t.value})`" :value="t.value" />
        </el-select>
        <template v-if="pump.channels[ch].mode === 'TIME_QUANTITY'">
          <el-input-number
            :model-value="calcFlowRate(pump.channels[ch])"
            size="small"
            style="width: 100px"
            disabled
            :precision="2"
          />
          <span class="unit-label">mL/min</span>
          <span class="unit-label" style="color: #909399; font-size: 11px">(自动)</span>
        </template>
        <template v-else>
          <el-input-number
            v-model="pump.channels[ch].flowRate"
            :min="0.001" :max="pump.channels[ch].flowUnit === 3 ? 150 : pump.channels[ch].maxFlowRate" :step="0.001" :precision="3"
            size="small"
            style="width: 100px"
            :disabled="!pump.connected"
          />
          <el-select v-model="pump.channels[ch].flowUnit" size="small" style="width: 95px" :disabled="!pump.connected">
            <el-option v-for="u in FLOW_UNITS" :key="u.value" :label="u.label" :value="u.value" />
          </el-select>
        </template>
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
        <el-select
          v-if="needsRunTime(pump.channels[ch].mode)"
          v-model="pump.channels[ch].timeUnit"
          size="small"
          style="width: 95px"
          :disabled="!pump.connected"
        >
          <el-option v-for="u in TIME_UNITS" :key="u.value" :label="u.label" :value="u.value" />
        </el-select>
        <el-input-number
          v-if="needsDispenseVolume(pump.channels[ch].mode)"
          v-model="pump.channels[ch].dispenseVolume"
          :min="0.01" :max="9999" :step="1" :precision="2"
          size="small"
          style="width: 110px"
          :disabled="!pump.connected"
        />
        <el-select
          v-if="needsDispenseVolume(pump.channels[ch].mode)"
          v-model="pump.channels[ch].volumeUnit"
          size="small"
          style="width: 80px"
          :disabled="!pump.connected"
        >
          <el-option v-for="u in VOLUME_UNITS" :key="u.value" :label="u.label" :value="u.value" />
        </el-select>
      </div>
      <div class="channel-row" style="margin-top: 6px" v-if="pump.channels[ch].mode !== 'FLOW_MODE'">
        <span class="param-label">重复</span>
        <el-input-number
          v-model="pump.channels[ch].repeatCount"
          :min="0" :max="9999" :step="1"
          size="small"
          style="width: 95px"
          :disabled="!pump.connected"
        />
        <span class="unit-label" style="font-size: 11px">0=无限</span>
        <span class="param-label">间隔</span>
        <el-input-number
          v-model="pump.channels[ch].intervalTime"
          :min="0" :max="9999" :step="0.1" :precision="1"
          size="small"
          style="width: 95px"
          :disabled="!pump.connected"
        />
        <el-select
          v-model="pump.channels[ch].intervalTimeUnit"
          size="small"
          style="width: 95px"
          :disabled="!pump.connected"
        >
          <el-option v-for="u in TIME_UNITS" :key="u.value" :label="u.label" :value="u.value" />
        </el-select>
      </div>
      <div class="channel-row" style="margin-top: 6px">
        <el-button type="success" size="small" @click="$emit('startChannel', pumpId, ch)" :disabled="!pump.connected" :loading="pump.channels[ch].starting">
          启动
        </el-button>
        <el-button type="warning" size="small" @click="$emit('stopChannel', pumpId, ch)" :disabled="!pump.connected" :loading="pump.channels[ch].stopping">
          停止
        </el-button>
      </div>
    </div>

    <div style="margin-top: 12px; text-align: center">
      <el-button type="danger" size="small" @click="$emit('stopAll', pumpId)" :disabled="!pump.connected" :loading="pump.stoppingAll">
        停止所有通道
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { PUMP_MODES, TUBE_MODELS, FLOW_UNITS, TIME_UNITS, VOLUME_UNITS, type PumpMode } from '../api/devices'

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

const props = defineProps<{
  pumpId: string
  pump: {
    connected: boolean
    loading: boolean
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

function getMaxFlowRate(tubeModel: number): number {
  const found = TUBE_MODELS.find(t => t.value === tubeModel)
  return found ? found.maxFlow : 7.55
}

function onTubeModelChange(ch: ChannelConfig) {
  ch.maxFlowRate = getMaxFlowRate(ch.tubeModel)
  if (ch.flowRate > ch.maxFlowRate) {
    ch.flowRate = ch.maxFlowRate
  }
}
</script>

<style scoped>
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
.param-label {
  color: #606266;
  font-size: 12px;
  white-space: nowrap;
  margin-right: 2px;
}
</style>