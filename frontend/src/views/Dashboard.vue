<template>
  <div class="dashboard">
    <el-alert v-if="demo" title="离线演示 · 全部为模拟数据，不连接设备、不发送控制命令" type="warning" :closable="false" show-icon />
    <div class="trend-toolbar">
      <span>{{ freshnessLabel }}</span>
      <label>显示范围 <select v-model.number="windowSeconds"><option :value="60">最近 1 分钟</option><option :value="120">最近 2 分钟</option><option :value="300">最近 5 分钟</option><option :value="0">全部（最多 1800 点）</option></select></label>
      <button type="button" @click="following = !following">{{ following ? '暂停跟随，查看历史' : '回到实时' }}</button>
      <template v-if="demo"><button type="button" @click="demoPaused = !demoPaused">{{ demoPaused ? '恢复模拟数据' : '模拟数据中断' }}</button></template>
    </div>
    <p v-if="!wsConnected && lastReceived" class="stale-note">当前状态未知；灰色温度为上次有效读数，不能用于判断当前设备状态。曲线仅保留已收到的历史采样。</p>
    <div class="device-workspace">
      <nav class="device-selector" aria-label="选择监测设备">
        <div class="selector-heading">设备列表 <span>{{ dashboardDevices.length }} 台</span></div>
        <button v-for="item in deviceGroups" :key="item.key" type="button" class="device-choice" :class="{ selected: selectedDevice === item.key }" :aria-pressed="selectedDevice === item.key" @click="selectedDevice = item.key">
          <span class="choice-heading"><strong>{{ item.name }}</strong><span class="connection-dot" :class="{ online: item.online }" /></span>
          <span class="choice-meta">{{ item.summary }}</span>
        </button>
        <el-empty v-if="!dashboardDevices.length" description="暂无设备" :image-size="48" />
      </nav>
      <div class="device-detail">
      <div v-for="(valve, id) in dashboardValves" v-show="selectedDevice === 'valves'" :key="'v-' + id">
        <el-card class="device-card" shadow="hover">
          <template #header><div class="card-header">
            <div class="device-heading"><img :src="valveArtwork" alt="" /><div><h2>三通阀</h2><span>{{ id }} 监测</span></div></div>
            <el-tag :type="valve.read_ok ? 'success' : 'info'">{{ deviceInfo('valves', id)?.status }}</el-tag>
          </div></template>
          <div class="valve-status-grid">
            <div class="valve-status-item"><span class="status-light" :class="valve.connected && valve.read_ok ? 'is-online' : 'is-unknown'" /><div><small>通信</small><strong>{{ valve.connected && valve.read_ok ? '正常' : '未知' }}</strong></div></div>
            <div class="valve-status-item"><span class="status-light" :class="valve.read_ok ? (valve.relay_energized ? 'is-energized' : 'is-deenergized') : 'is-unknown'" /><div><small>继电器</small><strong>{{ !valve.read_ok ? '未知' : valve.relay_energized ? '通电' : '断电' }}</strong></div></div>
            <div class="valve-status-item"><span class="status-light" :class="valve.read_ok ? 'is-route' : 'is-unknown'" /><div><small>当前流路</small><strong>{{ !valve.read_ok ? '未知' : valve.relay_energized ? '公共口 → NC' : '公共口 → NO' }}</strong></div></div>
            <div class="valve-status-item"><span class="status-light" :class="valve.experiment_owned ? 'is-busy' : 'is-ready'" /><div><small>控制权</small><strong>{{ valve.experiment_owned ? '实验占用' : '手动可用' }}</strong></div></div>
          </div>
          <div class="valve-meta"><span>串口 {{ valve.connection_port || '--' }}</span><span>继电器读回</span></div>
          <p class="valve-note">流路按 T 型阀和继电器 NO 接线推定；实际出口需要现场确认。</p>
        </el-card>
      </div>
      <div v-for="(pump, id) in dashboardSyringes" v-show="selectedDevice === 'syringe_pumps'" :key="id">
        <el-card class="device-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="device-heading"><img :src="syringePumpArtwork" alt="" /><div><h2>注射泵</h2><span>{{ pump.name }} 监测</span></div></div>
            </div>
          </template>
          <p>{{ !pump.configured ? '待配置' : !pump.connected ? '未连接' : !wsConnected || !pump.read_ok ? '状态未知' : pump.fault_code ? pump.fault_description : pump.busy ? '运行中' : '空闲' }}</p>
          <p>位置：{{ wsConnected && pump.read_ok ? pump.position ?? '运动中' : '未知' }} 步；理论筒内体积：{{ wsConnected && pump.read_ok && pump.position_trusted ? pump.theoretical_volume_ul?.toFixed(2) : '未知' }} µL</p>
          <p>地址 {{ pump.address }} · {{ pump.connection_port || '串口待配置' }} · {{ pump.orientation || '方向未确认' }}</p>
        </el-card>
      </div>
      <div v-for="(turntable, id) in dashboardTurntables" v-show="selectedDevice === 'turntables'" :key="'t-'+id">
        <el-card class="device-card" shadow="hover">
          <template #header><div class="card-header"><div class="device-heading"><img :src="turntableArtwork" alt="" /><div><h2>接样转盘</h2><span>{{ turntable.name }} · CL-01A</span></div></div><el-tag :type="turntable.read_ok ? 'success' : 'info'">{{ deviceInfo('turntables', id)?.status }}</el-tag></div></template>
          <div class="valve-status-grid">
            <div class="valve-status-item"><div><small>当前瓶位</small><strong>{{ turntableBottle(turntable) }}</strong></div></div>
            <div class="valve-status-item"><div><small>运行状态</small><strong>{{ turntable.read_ok ? turntableWorkState[turntable.state_name || ''] || '未知' : '未知' }}</strong></div></div>
            <div class="valve-status-item"><div><small>停止确认</small><strong>{{ turntable.read_ok ? turntable.stop_confirmed ? '已确认' : '未确认' : '未知' }}</strong></div></div>
            <div class="valve-status-item"><div><small>当前动作</small><strong>{{ turntable.read_ok ? turntableResult[turntable.action?.result || ''] || '无' : '未知' }}</strong></div></div>
          </div>
          <details class="turntable-details"><summary>设备详情</summary><p>控制器坐标 {{ turntable.read_ok ? turntable.position ?? '未知' : '未知' }} 脉冲</p>
          <div class="valve-meta"><span>串口 {{ turntable.connection_port || '--' }}</span><span>正限位 {{ turntableInput(turntable, 'positive_limit') }} · 原点 {{ turntableInput(turntable, 'home') }} · 负限位 {{ turntableInput(turntable, 'negative_limit') }} · 输入4 {{ turntableInput(turntable, 'input4') }}</span></div></details>
          <p v-if="turntable.action?.error" class="valve-note">{{ turntable.action.error }}</p>
        </el-card>
      </div>
      <div v-for="(heater, id) in dashboardHeaters" v-show="selectedDevice === 'heaters'" :key="'h-'+id">
        <el-card shadow="hover" class="device-card">
          <template #header>
            <div class="card-header">
              <div class="device-heading"><img :src="heaterArtwork" alt="" /><div><h2>加热器</h2><span>{{ id }} 监测</span></div></div>
              <el-tag :type="heater.error ? 'danger' : heater.run_status === 'RUN' ? 'success' : 'info'" size="small">
                {{ !deviceInfo('heaters', id)?.hasData ? deviceInfo('heaters', id)?.status : heater.error ? '异常' : heaterStatusLabel(heater.run_status) }}
              </el-tag>
            </div>
          </template>
          <div :class="['heater-info', { 'stale-readings': !deviceInfo('heaters', id)?.hasData }]">
            <div class="temp-block">
              <span class="temp-label">当前温度</span>
              <span class="temp-value">{{ heater.pv?.toFixed(1) ?? '--' }}°C</span>
            </div>
            <div class="temp-block">
              <span class="temp-label">设定温度</span>
              <span class="temp-value target">{{ heater.sv?.toFixed(1) ?? '--' }}°C</span>
            </div>
            <div class="temp-block">
              <span class="temp-label">输出功率</span>
              <span class="temp-value">{{ heater.mv ?? '--' }}%</span>
            </div>
          </div>
          <div class="alarms">
            <el-tag type="info" size="small">串口 {{ heater.connection_port ?? '--' }}</el-tag>
          </div>
          <div v-if="heater.alarms?.length" class="alarms">
            <el-tag v-for="alarm in heater.alarms" :key="alarm" type="warning" size="small" style="margin: 2px">
              {{ alarm }}
            </el-tag>
          </div>
        </el-card>
      </div>

      <div v-for="(pump, id) in dashboardPumps" v-show="selectedDevice === 'pumps'" :key="'p-'+id">
        <el-card shadow="hover" class="device-card">
          <template #header>
            <div class="card-header">
              <div class="device-heading"><img :src="pumpArtwork" alt="" /><div><h2>蠕动泵</h2><span>{{ id }} 监测</span></div></div>
              <el-tag :type="pump.error ? 'danger' : deviceInfo('pumps', id)?.hasData ? 'success' : 'info'" size="small">
                {{ pump.error ? '异常' : deviceInfo('pumps', id)?.status }}
              </el-tag>
            </div>
          </template>
          <div class="pump-channels">
            <div class="channel-row">
              <span class="channel-label">串口</span>
              <el-tag type="info" size="small">{{ pump.connection_port ?? '--' }}</el-tag>
            </div>
            <div v-for="(ch, chId) in pump.channels" :key="chId" class="channel-row">
              <span class="channel-label">通道 {{ chId }}</span>
              <el-tag v-if="ch.running == null" type="info" size="small">未知</el-tag>
              <el-tag v-else-if="ch.read_ok === false" type="danger" size="small">
                读取失败
              </el-tag>
              <el-tag v-else :type="ch.running ? 'success' : 'info'" size="small">
                {{ ch.run_status === 'PAUSE' ? '暂停' : ch.running ? '运行中' : ch.run_status === 'STOP' ? '停止' : '未知' }}
              </el-tag>
              <span v-if="ch.read_ok !== false && ch.running" class="channel-detail">
                {{ ch.flow_rate?.toFixed(1) ?? '0.0' }} {{ flowUnitLabel(ch.flow_unit) }}
              </span>
              <span v-if="ch.read_ok !== false && ch.running && ch.volume != null && ch.volume > 0" class="channel-detail">
                已泵 {{ ch.volume?.toFixed(1) ?? '0.0' }} mL
              </span>
              <span v-if="ch.read_ok !== false && ch.running && ch.direction" class="channel-detail">
                {{ ch.direction === 'CLOCKWISE' ? '顺时针' : '逆时针' }}
              </span>
            </div>
          </div>
        </el-card>
      </div>

      <div v-for="(microwave, id) in dashboardMicrowaves" v-show="selectedDevice === 'microwaves'" :key="'m-'+id">
        <el-card shadow="hover" class="device-card">
          <template #header>
            <div class="card-header">
              <div class="device-heading"><img :src="microwaveArtwork" alt="" /><div><h2>微波仪</h2><span>{{ id }} 监测</span></div></div>
              <el-tag :type="microwaveStatusType(microwave)" size="small">
                {{ microwaveStatusText(microwave) }}
              </el-tag>
            </div>
          </template>
          <div :class="['microwave-info', { 'stale-readings': !deviceInfo('microwaves', id)?.hasData }]">
            <div class="metric-block">
              <span class="metric-label">物料温度</span>
              <span class="metric-value">{{ formatNumber(microwave.material_temperature, 1, '°C') }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">功率</span>
              <span class="metric-value">{{ formatNumber(microwave.power_percent, 0, '%') }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">电流</span>
              <span class="metric-value">{{ formatNumber(microwave.current, 2, 'A') }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">运行时间</span>
              <span class="metric-value">{{ formatRuntime(microwave.runtime_seconds) }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">当前段</span>
              <span class="metric-value">{{ microwave.current_segment ?? '--' }}</span>
            </div>
            <div class="metric-block">
              <span class="metric-label">当前模式</span>
              <span class="metric-value">{{ microwaveModeLabel(microwave.mode, microwave.current_mode_code) }}</span>
            </div>
          </div>
          <div class="alarms">
            <el-tag :type="Number(microwave.fault_code || 0) ? 'danger' : 'info'" size="small">
              故障码 {{ microwave.fault_code ?? '未知' }}
            </el-tag>
            <el-tag type="info" size="small" style="margin: 2px">
              串口 {{ microwave.connection_port ?? '--' }}
            </el-tag>
            <el-tag v-if="!microwave.connected" type="info" size="small" style="margin: 2px">未连接</el-tag>
            <el-tag v-if="microwave.error" type="danger" size="small" style="margin: 2px">读取失败</el-tag>
            <el-tag v-for="fault in microwave.faults || []" :key="fault" type="warning" size="small" style="margin: 2px">
              {{ fault }}
            </el-tag>
          </div>
        </el-card>
      </div>
      <el-empty v-if="!dashboardDevices.length" description="暂无设备数据" />

    <div class="chart-grid">
      <div v-show="selectedDevice === 'heaters'">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>加热器实时温度曲线</span>
              <div class="stream-status">
              <el-tag :type="communicationTagType" size="small">
                {{ communicationLabel }}
              </el-tag>
              <el-tag v-if="monitorState !== 'live'" :type="waitingForData ? 'info' : 'warning'" size="small">{{ dataStatusLabel }}</el-tag>
              </div>
            </div>
          </template>
          <p class="trend-note">{{ heaterCurveNote }}</p>
          <p v-if="!Object.keys(heaterDataMap).length" class="trend-empty">{{ waitingForData ? '等待首包有效温度数据' : '设备未连接或暂无有效温度数据' }}</p>
          <div ref="heaterTempChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </div>
      <div v-show="selectedDevice === 'microwaves'">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>微波合成仪物料温度曲线</span>
              <div class="stream-status">
              <el-tag :type="communicationTagType" size="small">
                {{ communicationLabel }}
              </el-tag>
              <el-tag v-if="monitorState !== 'live'" :type="waitingForData ? 'info' : 'warning'" size="small">{{ dataStatusLabel }}</el-tag>
              </div>
            </div>
          </template>
          <p v-if="!Object.keys(microwaveDataMap).length" class="trend-empty">{{ waitingForData ? '等待首包有效温度数据' : '设备未连接或暂无有效温度数据' }}</p>
          <div ref="microwaveTempChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </div>
      <div v-show="selectedDevice === 'pumps'">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>实时流量曲线</span>
              <div class="stream-status">
              <el-tag :type="communicationTagType" size="small">
                {{ communicationLabel }}
              </el-tag>
              <el-tag v-if="monitorState !== 'live'" :type="waitingForData ? 'info' : 'warning'" size="small">{{ dataStatusLabel }}</el-tag>
              </div>
            </div>
          </template>
          <div ref="flowChartRef" style="width: 100%; height: 350px"></div>
        </el-card>
      </div>
    </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { init, type ECharts, type LineSeriesOption } from '../lib/echarts'
import { useDashboardDemo } from '../composables/useDashboardDemo'
import { devicesApi } from '../api/devices'
import { useWebSocket, type HeaterRealtimeData, type PumpRealtimeData, type PumpChannelData, type MicrowaveRealtimeData } from '../composables/useWebSocket'
import type { SyringeState } from '../api/syringePumps'
import { turntableResult, turntableWorkState, type TurntableState } from '../api/turntables'
import { MONITOR_FRESHNESS_MS } from '../utils/monitorHistory'
import heaterArtwork from '../assets/theme/heater.webp'
import pumpArtwork from '../assets/theme/pump.webp'
import syringePumpArtwork from '../assets/theme/syringe-pump.webp'
import valveArtwork from '../assets/theme/valve.webp'
import microwaveArtwork from '../assets/theme/microwave.webp'
import turntableArtwork from '../assets/theme/turntable.svg'

type TagType = 'success' | 'warning' | 'info' | 'danger'

const demo = import.meta.env.DEV && new URLSearchParams(location.search).get('demo') === '1'
const demoSource = demo ? useDashboardDemo() : null
const dataSource = demoSource || useWebSocket()
const realtimeData = 'monitorData' in dataSource ? dataSource.monitorData : dataSource.data
const wsConnected = 'monitorFresh' in dataSource ? dataSource.monitorFresh : dataSource.fresh
const { monitorHistory, monitorState } = dataSource
const demoPaused = demoSource?.paused || ref(false)
const clock = ref(Date.now())
const lastReceived = computed(() => monitorHistory.lastReceivedAt)
const windowSeconds = ref(120)
const following = ref(true)
const windowEnd = ref(Date.now())
let clockTimer: ReturnType<typeof setInterval> | undefined
const communicationLabel = computed(() => monitorState.value === 'connecting' ? '正在连接服务器'
  : monitorState.value === 'disconnected' ? '服务器通信中断' : '服务器通信正常')
const dataStatusLabel = computed(() => ({ connecting: '等待连接', waiting: '等待设备采样', live: '实时数据已更新', stale: '设备数据已过期', disconnected: '设备状态未知' })[monitorState.value])
const waitingForData = computed(() => ['connecting', 'waiting'].includes(monitorState.value))
const communicationTagType = computed<TagType>(() => monitorState.value === 'connecting' ? 'info' : monitorState.value === 'disconnected' ? 'danger' : 'success')
const freshnessLabel = computed(() => `${communicationLabel.value} · ${dataStatusLabel.value}${lastReceived.value ? ` · 最后采样 ${Math.max(0, Math.floor((clock.value - lastReceived.value) / 1000))} 秒前` : ''}`)
const { lastHeaters, lastMicrowaves } = monitorHistory

function heaterStatusLabel(status?: string): string {
  return ({ RUN: '运行', STOP: '停止', HOLD: '保持' } as Record<string, string>)[status || ''] || '状态未知'
}
const heaterTempChartRef = ref<HTMLElement>()
const microwaveTempChartRef = ref<HTMLElement>()
const flowChartRef = ref<HTMLElement>()
let heaterTempChart: ECharts | null = null
let microwaveTempChart: ECharts | null = null
let flowChart: ECharts | null = null
const { heaters: heaterDataMap, microwaves: microwaveDataMap, pumps: pumpDataMap } = monitorHistory

const channelColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c']

interface RegisteredMicrowaveStatus {
  connected: boolean
  status?: string
  connection_port?: string
  binding_label?: string
  binding_resolved?: boolean
  binding_error?: string | null
  allow_experiment_control?: boolean
  allow_real_hardware_writes?: boolean
  enable_control_writes?: boolean
}

interface DashboardMicrowaveData extends MicrowaveRealtimeData {
  connected: boolean
  status?: string
}

const registeredMicrowaves = ref<Record<string, RegisteredMicrowaveStatus>>({})
const selectedDevice = ref('')
let initialSelectionReady = false
const registeredDevices = ref<Record<string, Record<string, { connected: boolean; connection_port?: string; name?: string; configured?: boolean; channels?: Record<string, unknown> }>>>({})
const registeredSyringes = ref<Record<string, SyringeState>>({})
const registeredTurntables = ref<Record<string, TurntableState>>({})
const dashboardDevices = computed(() => {
  const groups = [ ['heaters', '加热器'], ['pumps', '蠕动泵'], ['microwaves', '微波仪'], ['syringe_pumps', '注射泵'], ['valves', '三通阀'], ['turntables', '接样转盘'] ] as const
  return groups.flatMap(([kind, label]) => {
    const liveDevices = realtimeData.value?.[kind] || {}
    const registered = registeredDevices.value[kind] || {}
    return [...new Set([...Object.keys(registered), ...Object.keys(liveDevices)])].map((id, index) => {
      const live = liveDevices[id]
      const config = registered[id]
      const configured = (kind !== 'syringe_pumps' && kind !== 'turntables') || config?.configured !== false
      const online = configured && (wsConnected.value ? Boolean(live && (!('connected' in live) || live.connected)) : Boolean(config?.connected))
      const readFailed = live && (('read_ok' in live && live.read_ok === false) || ('error' in live && live.error))
      const turntableReadAt = live && 'read_at' in live ? Date.parse(live.read_at || '') : NaN
      const turntableStale = kind === 'turntables' && (!Number.isFinite(turntableReadAt) || clock.value - turntableReadAt >= MONITOR_FRESHNESS_MS)
      const fault = live && 'fault_code' in live && live.fault_code
      return {
        key: `${kind}:${id}`, name: config?.name || `${label}${index + 1}`,
        port: live?.connection_port || config?.connection_port,
        online,
        status: !configured ? '待配置' : !online ? '未连接' : !wsConnected.value || !live || turntableStale ? '状态未知' : readFailed ? '读取失败' : fault ? '故障' : '在线',
        hasData: Boolean(live && online && wsConnected.value && !readFailed && !turntableStale),
      }
    })
  })
})
const deviceGroups = computed(() => [
  { key: 'heaters', name: '加热器' },
  { key: 'pumps', name: '蠕动泵' },
  { key: 'microwaves', name: '微波仪' },
  { key: 'syringe_pumps', name: '注射泵' },
  { key: 'turntables', name: '接样转盘' },
  { key: 'valves', name: '三通阀' },
].map(group => {
  const members = dashboardDevices.value.filter(device => device.key.startsWith(group.key + ':'))
  const connectedCount = members.filter(device => device.online).length
  const attention = [...new Set(members.map(device => device.status).filter(status => ['待配置', '读取失败', '故障', '状态未知'].includes(status)))]
  return { ...group, count: members.length, online: connectedCount > 0,
    summary: `${members.length} 台 · 已连接 ${connectedCount}/${members.length}${attention.length ? ' · ' + attention.join('、') : ''}` }
}).filter(group => group.count > 0))
function deviceInfo(kind: string, id: string) {
  return dashboardDevices.value.find(item => item.key === `${kind}:${id}`)
}
const dashboardHeaters = computed<Record<string, Partial<HeaterRealtimeData>>>(() => Object.fromEntries(
  dashboardDevices.value.filter(item => item.key.startsWith('heaters:')).map(item => {
    const id = item.key.slice(8)
    return [id, { ...(lastHeaters[id] ? { pv: lastHeaters[id].pv, sv: lastHeaters[id].sv } : {}), connection_port: item.port, ...(item.hasData ? realtimeData.value?.heaters[id] : {}), run_status: item.hasData ? realtimeData.value?.heaters[id]?.run_status : undefined }]
  })
))
const heaterCurveNote = computed(() => {
  const targets = wsConnected.value ? Object.values(realtimeData.value?.heaters || {})
    .filter(heater => !heater.error && Number.isFinite(heater.sv)).map(heater => heater.sv) : []
  const equalTargets = targets.length > 1 && targets.every(target => target === targets[0])
  return equalTargets ? `当前 ${targets.length} 台加热器均设为 ${targets[0]!.toFixed(1)}℃，设定曲线重合。实线为实测、虚线为设定；悬停可分别查看，点击图例可单独显示。`
    : '每台加热器各有实测、设定两条曲线；数值相同时曲线会重合。实线为实测、虚线为设定；悬停可分别查看。'
})
const dashboardPumps = computed<Record<string, Partial<PumpRealtimeData>>>(() => Object.fromEntries(
  dashboardDevices.value.filter(item => item.key.startsWith('pumps:')).map(item => {
    const id = item.key.slice(6)
    const channels: Record<string, PumpChannelData> = Object.fromEntries(
      Object.keys(registeredDevices.value.pumps?.[id]?.channels || {}).map(channel => [channel, {
        running: null, flow_rate: null, volume: null, direction: null, flow_unit: null,
      }])
    )
    return [id, { connection_port: item.port, channels, ...(item.hasData ? realtimeData.value?.pumps[id] : {}) }]
  })
))
const dashboardValves = computed(() => Object.fromEntries(
  dashboardDevices.value.filter(item => item.key.startsWith('valves:')).map(item => {
    const id = item.key.slice(7)
    return [id, { connection_port: item.port, ...(item.hasData ? realtimeData.value?.valves[id] : {}), read_ok: item.hasData }]
  })
))
const dashboardSyringes = computed(() => Object.fromEntries(
  dashboardDevices.value.filter(item => item.key.startsWith('syringe_pumps:')).map(item => {
    const id = item.key.slice(14)
    const state = realtimeData.value?.syringe_pumps[id] || registeredSyringes.value[id]
    return [id, { ...state, read_ok: item.hasData, position_trusted: item.hasData && state?.position_trusted }]
  })
))
const dashboardTurntables = computed<Record<string, Partial<TurntableState>>>(() => Object.fromEntries(
  dashboardDevices.value.filter(item => item.key.startsWith('turntables:')).map(item => {
    const id = item.key.slice(11)
    const state = realtimeData.value?.turntables[id] || registeredTurntables.value[id]
    return [id, { ...state, connection_port: item.port, read_ok: item.hasData }]
  })
))
function turntableBottle(state: Partial<TurntableState>) {
  const bottle = state.current_bottle
  return state.connected && state.read_ok && state.bottle_ready && state.stop_confirmed && state.busy === false && !state.motion_blocked && !['accepted', 'running', 'unknown', 'stop_requested', 'stop_unconfirmed'].includes(state.action?.result || '') && Number.isInteger(bottle) && bottle != null && bottle >= 1 && bottle <= (state.bottle_count ?? 0) ? `${bottle}号瓶` : '未确认'
}
function turntableInput(state: Partial<TurntableState>, key: keyof NonNullable<TurntableState['inputs']>) {
  return !state.read_ok || state.inputs?.[key] == null ? '未知' : state.inputs[key] ? '有效' : '无效'
}
watch(deviceGroups, items => {
  if (!initialSelectionReady) return
  if (!items.some(item => item.key === selectedDevice.value)) selectedDevice.value = items[0]?.key || ''
}, { immediate: true })

const dashboardMicrowaves = computed<Record<string, DashboardMicrowaveData>>(() => {
  const merged: Record<string, DashboardMicrowaveData> = {}
  for (const [id, status] of Object.entries(registeredMicrowaves.value)) {
    merged[id] = {
      device_id: id,
      material_temperature: lastMicrowaves[id]?.material_temperature,
      connected: Boolean(status.connected),
      status: status.status,
      connection_port: status.connection_port,
      binding_label: status.binding_label,
      binding_resolved: status.binding_resolved,
      binding_error: status.binding_error,
      allow_experiment_control: Boolean(status.allow_experiment_control),
      allow_real_hardware_writes: Boolean(status.allow_real_hardware_writes),
      enable_control_writes: Boolean(status.enable_control_writes),
    }
  }
  for (const [id, live] of Object.entries(realtimeData.value?.microwaves || {})) {
    const item = dashboardDevices.value.find(device => device.key === `microwaves:${id}`)
    merged[id] = {
      ...(merged[id] || {}),
      ...(lastMicrowaves[id] ? { material_temperature: lastMicrowaves[id].material_temperature } : {}),
      ...(item?.hasData ? live : {}),
      device_id: live.device_id || id,
      connected: item?.online ?? false,
      status: item?.status,
    }
  }
  return merged
})

const FLOW_UNIT_LABELS: Record<string, string> = {
  ML_MIN: 'mL/min',
  UL_MIN: 'uL/min',
  L_MIN: 'L/min',
  RPM: 'RPM',
}

function flowUnitLabel(unit: string | null | undefined): string {
  return FLOW_UNIT_LABELS[unit || 'ML_MIN'] || 'mL/min'
}

function microwaveModeLabel(mode: string | undefined, currentModeCode?: number): string {
  const labels: Record<string, string> = {
    manual_power: '手动功率',
    auto_power: '自动功率',
    constant_rate: '恒速率',
    unknown: '未知',
  }
  const label = labels[mode || 'unknown'] || mode || '--'
  if ((!mode || mode === 'unknown') && currentModeCode !== undefined && currentModeCode !== null) {
    return label + ' (' + currentModeCode + ')'
  }
  return label
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

function microwaveStatusType(microwave: DashboardMicrowaveData): TagType {
  if (!microwave.connected) return 'info'
  if (microwave.status === '读取失败' || microwave.status === '状态未知') return 'warning'
  if (microwave.error) return 'danger'
  if (Number(microwave.fault_code || 0)) return 'danger'
  if (microwave.control_active || microwave.output_active) return 'success'
  if (!microwave.status_confirmed) return 'warning'
  return 'info'
}

function microwaveStatusText(microwave: DashboardMicrowaveData): string {
  if (!microwave.connected) return '离线'
  if (microwave.status === '读取失败' || microwave.status === '状态未知') return microwave.status
  if (microwave.error) return '读取失败'
  if (Number(microwave.fault_code || 0)) return '异常'
  if (microwave.control_active || microwave.output_active) return '运行中'
  if (microwave.stop_confirmed) return '已确认停止'
  return '状态未知'
}

async function refreshRegisteredDevices() {
  try {
    const res = demoSource ? { data: demoSource.devices } : await devicesApi.list()
    registeredDevices.value = res.data
    registeredSyringes.value = res.data.syringe_pumps || {}
    registeredTurntables.value = res.data.turntables || {}
    registeredMicrowaves.value = res.data.microwaves || {}
    if (!initialSelectionReady) {
      selectedDevice.value = deviceGroups.value[0]?.key || ''
      initialSelectionReady = true
    }
  } catch (error) {
    console.error('[Dashboard] 设备状态读取失败:', error)
  }
}

let resizeObserver: ResizeObserver | null = null

function temperatureAxis() {
  return { type: 'value' as const, name: '温度（℃）', axisLabel: { color: '#34465b', fontSize: 13 },
    min: ({ min }: { min: number }) => Math.floor((min - 5) / 10) * 10,
    max: ({ max }: { max: number }) => Math.ceil((max + 5) / 10) * 10,
    splitLine: { lineStyle: { color: '#e2e8f0' } } }
}
function updateWindows() {
  for (const chart of [heaterTempChart, microwaveTempChart, flowChart]) chart?.setOption({ xAxis: { min: windowSeconds.value ? windowEnd.value - windowSeconds.value * 1000 : null, max: windowSeconds.value ? windowEnd.value : null } })
}
watch([windowSeconds, following], () => {
  for (const chart of [heaterTempChart, microwaveTempChart, flowChart]) chart?.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
  updateWindows()
})
function initCharts() {
  try {
    if (heaterTempChartRef.value) {
      if (heaterTempChart) heaterTempChart.dispose()
      heaterTempChart = init(heaterTempChartRef.value, undefined, { width: heaterTempChartRef.value.clientWidth || 400, height: 350 })
      heaterTempChart.setOption({
        animation: false,
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0, left: 10, right: 10, type: 'plain', textStyle: { color: '#34465b', fontSize: 12 } },
        dataZoom: [{ type: 'inside', filterMode: 'none' }],
        grid: { left: 60, right: 20, top: 80, bottom: 55 },
        xAxis: { type: 'time', name: '时间', nameLocation: 'middle', nameGap: 30, axisLabel: { color: '#34465b', fontSize: 13, hideOverlap: true, formatter: '{HH}:{mm}:{ss}' } },
        yAxis: temperatureAxis(),
        series: [],
      })
    }
    if (microwaveTempChartRef.value) {
      if (microwaveTempChart) microwaveTempChart.dispose()
      microwaveTempChart = init(microwaveTempChartRef.value, undefined, { width: microwaveTempChartRef.value.clientWidth || 400, height: 350 })
      microwaveTempChart.setOption({
        animation: false,
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0, type: 'scroll', textStyle: { color: '#34465b', fontSize: 13 } },
        dataZoom: [{ type: 'inside', filterMode: 'none' }],
        grid: { left: 60, right: 20, top: 60, bottom: 55 },
        xAxis: { type: 'time', name: '时间', nameLocation: 'middle', nameGap: 30, axisLabel: { color: '#34465b', fontSize: 13, hideOverlap: true, formatter: '{HH}:{mm}:{ss}' } },
        yAxis: temperatureAxis(),
        series: [],
      })
    }
    if (flowChartRef.value) {
      if (flowChart) flowChart.dispose()
      flowChart = init(flowChartRef.value, undefined, { width: flowChartRef.value.clientWidth || 400, height: 350 })
      flowChart.setOption({
        animation: false,
        tooltip: { trigger: 'axis' },
        legend: { data: [], top: 0, type: 'scroll', textStyle: { color: '#34465b', fontSize: 13 } },
        dataZoom: [{ type: 'inside', filterMode: 'none' }],
        grid: { left: 60, right: 20, top: 60, bottom: 55 },
        xAxis: { type: 'time', name: '时间', nameLocation: 'middle', nameGap: 30, axisLabel: { color: '#34465b', fontSize: 13, hideOverlap: true, formatter: '{HH}:{mm}:{ss}' } },
        yAxis: { type: 'value', name: '流量(mL/min)' },
        series: [],
      })
    }
  } catch (error) {
    console.error('[Dashboard] 图表初始化失败:', error)
  }
}

onMounted(async () => {
  clockTimer = setInterval(() => { clock.value = Date.now(); if (following.value) windowEnd.value = clock.value; updateWindows() }, 1000)
  await nextTick()
  initCharts()
  renderCharts()
  void refreshRegisteredDevices().then(renderCharts)

  resizeObserver = new ResizeObserver(handleResize)
  if (heaterTempChartRef.value) resizeObserver.observe(heaterTempChartRef.value)
  if (microwaveTempChartRef.value) resizeObserver.observe(microwaveTempChartRef.value)
  if (flowChartRef.value) resizeObserver.observe(flowChartRef.value)

  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  resizeObserver?.disconnect()
  heaterTempChart?.dispose()
  microwaveTempChart?.dispose()
  flowChart?.dispose()
  heaterTempChart = null
  microwaveTempChart = null
  flowChart = null
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  if (heaterTempChartRef.value?.clientWidth) heaterTempChart?.resize({ width: heaterTempChartRef.value.clientWidth, height: 350 })
  if (microwaveTempChartRef.value?.clientWidth) microwaveTempChart?.resize({ width: microwaveTempChartRef.value.clientWidth, height: 350 })
  if (flowChartRef.value?.clientWidth) flowChart?.resize({ width: flowChartRef.value.clientWidth, height: 350 })
}

watch(selectedDevice, async () => {
  await nextTick()
  handleResize()
})

function renderCharts() {
  if (heaterTempChart) {
    const heaterSeries: LineSeriesOption[] = []
    const heaterLegend: string[] = []
    for (const [id, s] of Object.entries(heaterDataMap)) {
      if (selectedDevice.value !== 'heaters') continue
      if (s.pv.length === 0) continue
      heaterLegend.push(`${deviceInfo('heaters', id)?.name || id} · 实测温度`, `${deviceInfo('heaters', id)?.name || id} · 设定温度`)
      heaterSeries.push(
        { name: `${deviceInfo('heaters', id)?.name || id} · 实测温度`, type: 'line', data: s.pv, smooth: false, showSymbol: true, symbol: 'circle', symbolSize: 4 },
        { name: `${deviceInfo('heaters', id)?.name || id} · 设定温度`, type: 'line', data: s.sv, lineStyle: { type: 'dashed' }, showSymbol: true, symbol: heaterSeries.length === 0 ? 'diamond' : 'rect', symbolSize: heaterSeries.length === 0 ? 8 : 4 },
      )
    }
    heaterTempChart.setOption(
        { color: ['#2563eb', '#2563eb', '#d97706', '#d97706'], legend: { data: heaterLegend }, series: heaterSeries },
        { replaceMerge: ['series'] }
      )
  }

  if (microwaveTempChart) {
    const microwaveSeries: LineSeriesOption[] = []
    const microwaveLegend: string[] = []
    for (const [id, s] of Object.entries(microwaveDataMap)) {
      if (selectedDevice.value !== 'microwaves') continue
      if (s.temperature.length === 0) continue
      const name = `${deviceInfo('microwaves', id)?.name || id} · 物料温度`
      microwaveLegend.push(name)
      microwaveSeries.push({ name, type: 'line', data: s.temperature, smooth: false, showSymbol: true, symbolSize: 4 })
    }
    microwaveTempChart.setOption(
        { legend: { data: microwaveLegend }, series: microwaveSeries },
        { replaceMerge: ['series'] }
      )
  }

  if (flowChart) {
    const flowSeries: LineSeriesOption[] = []
    const flowLegend: string[] = []
    for (const [pumpId, pData] of Object.entries(pumpDataMap)) {
      if (selectedDevice.value !== 'pumps') continue
      for (const [chId, chSeries] of Object.entries(pData.channels)) {
        if (chSeries.length === 0) continue
        const name = `${pumpId} CH${chId}`
        flowLegend.push(name)
        const colorIdx = (parseInt(chId) - 1) % channelColors.length
        flowSeries.push({
          name,
          type: 'line',
          data: chSeries,
          smooth: false,
          showSymbol: true,
          symbolSize: 4,
          lineStyle: { color: channelColors[colorIdx] },
          itemStyle: { color: channelColors[colorIdx] },
          areaStyle: { opacity: 0.1 },
        })
      }
    }
    flowChart.setOption(
        { legend: { data: flowLegend }, series: flowSeries },
        { replaceMerge: ['series'] }
      )
  }
}
watch([() => monitorHistory.revision, selectedDevice, wsConnected], renderCharts, { flush: 'post' })
</script>

<style scoped>
.turntable-details { margin-top: 14px; font-size: 12px; color: var(--el-text-color-secondary); }
.turntable-details summary { cursor: pointer; }
.dashboard { padding: 0; }
.device-workspace { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 20px; align-items: start; }
.device-selector { position: sticky; top: 88px; padding-right: 14px; border-right: 1px solid var(--el-border-color-light); min-width: 0; }
.trend-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 12px 0 18px; color: #34465b; font-size: 14px; }
.trend-toolbar button, .trend-toolbar select { border: 1px solid #b6cee6; background: white; color: #245483; border-radius: 6px; padding: 7px 10px; }
.stale-readings { opacity: .5; }
.stale-note, .trend-empty { color: #6b7280; font-size: 14px; }
.trend-note { color: #52677c; font-size: 13px; line-height: 1.6; margin: 0 0 8px; }
.stream-status { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }
.selector-heading { display: flex; justify-content: space-between; padding: 8px 12px 14px; font-size: 14px; font-weight: 600; }
.selector-heading span { color: var(--el-text-color-secondary); font-size: 12px; }
.device-choice { display: block; width: 100%; margin-bottom: 6px; padding: 12px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--el-text-color-regular); text-align: left; cursor: pointer; font: inherit; }
.device-choice:hover { background: var(--el-fill-color-light); }
.device-choice.selected { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }
.device-choice:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.choice-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 14px; }
.choice-heading strong, .choice-meta { overflow-wrap: anywhere; }
.connection-dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: var(--el-text-color-placeholder); }
.connection-dot.online { background: var(--el-color-success); }
.choice-meta { display: block; margin-top: 5px; color: var(--el-text-color-secondary); font-size: 12px; }
.device-detail { min-width: 0; display: flex; flex-direction: column; gap: 20px; }
.device-card { margin-bottom: 0; }
.device-detail :deep(.el-card__header) { min-height: 88px; display: flex; align-items: center; box-sizing: border-box; }
.device-detail .card-header { width: 100%; }
.chart-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; }
.chart-grid > div { min-width: 0; }
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.heater-info { display: flex; gap: 30px; justify-content: center; padding: 10px 0; }
.temp-block { display: flex; flex-direction: column; align-items: center; }
.temp-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.temp-value { font-size: 28px; font-weight: bold; color: #303133; }
.temp-value.target { color: #409eff; }
.alarms { margin-top: 8px; text-align: center; }
.pump-channels { padding: 5px 0; }
.channel-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 6px 0; border-bottom: 1px solid #f0f0f0; }
.channel-row:last-child { border-bottom: none; }
.channel-label { font-weight: 500; min-width: 60px; }
.channel-detail { color: #606266; font-size: 13px; }
.microwave-info {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 5px 0;
}
.metric-block {
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
.valve-status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.valve-status-item { display: flex; align-items: center; gap: 14px; padding: 20px 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 12px; background: var(--el-fill-color-extra-light); }
.valve-status-item small { display: block; margin-bottom: 6px; color: var(--el-text-color-secondary); font-size: 12px; }
.valve-status-item strong { display: block; font-size: 17px; color: var(--el-text-color-primary); }
.status-light { --light-color: #a8abb2; display: block; width: 16px; height: 16px; flex: 0 0 16px; border-radius: 50%; background: radial-gradient(circle at 35% 30%, #fff9, transparent 55%), var(--light-color); box-shadow: 0 0 0 5px color-mix(in srgb, var(--light-color) 12%, transparent), 0 0 12px color-mix(in srgb, var(--light-color) 28%, transparent); }
.status-light.is-online, .status-light.is-ready { --light-color: #52b788; }
.status-light.is-energized, .status-light.is-route { --light-color: #409eff; }
.status-light.is-deenergized { --light-color: #7892ac; }
.status-light.is-busy { --light-color: #e6a23c; }
.valve-meta { display: flex; justify-content: space-between; margin-top: 18px; color: var(--el-text-color-secondary); font-size: 13px; }
.valve-note { margin: 14px 0 0; padding-top: 14px; border-top: 1px solid var(--el-border-color-lighter); color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
@media (max-width: 900px) {
  .valve-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .device-workspace, .chart-grid { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .device-selector { position: static; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; padding: 0 0 12px; border-right: 0; border-bottom: 1px solid var(--el-border-color-light); }
  .trend-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 12px 0 18px; color: #34465b; font-size: 14px; }
.trend-toolbar button, .trend-toolbar select { border: 1px solid #b6cee6; background: white; color: #245483; border-radius: 6px; padding: 7px 10px; }
.stale-readings { opacity: .5; }
.stale-note, .trend-empty { color: #6b7280; font-size: 14px; }
.selector-heading { grid-column: 1 / -1; padding: 0 2px 4px; }
  .device-choice { margin: 0; padding: 10px; }
  .heater-info { gap: 12px; flex-wrap: wrap; }
  .temp-value { font-size: 22px; }
  .microwave-info { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
