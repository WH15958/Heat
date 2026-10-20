import { computed, reactive, ref, onMounted, onUnmounted } from 'vue'
import { createMonitorHistory, mergeMonitorFrames, recordMonitorFrame, MONITOR_FRESHNESS_MS } from '../utils/monitorHistory'
import type { ValveState } from '../api/devices'
import type { SyringeState } from '../api/syringePumps'

export interface HeaterRealtimeData {
  device_id?: string
  connection_port?: string
  connection_binding_mode?: string
  binding_label?: string
  binding_resolved?: boolean
  binding_match_count?: number
  binding_error?: string | null
  binding_candidates?: string[]
  pv: number
  sv: number
  mv: number
  alarms: string[]
  run_status: string
  error?: string
}

export interface PumpChannelData {
  running: boolean | null
  run_status?: string
  flow_rate: number | null
  volume: number | null
  direction: string | null
  flow_unit: string | null
  read_ok?: boolean
}

export interface PumpRealtimeData {
  device_id: string
  connection_port?: string
  connection_binding_mode?: string
  binding_label?: string
  binding_resolved?: boolean
  binding_match_count?: number
  binding_error?: string | null
  binding_candidates?: string[]
  channels: Record<string, PumpChannelData>
  error?: string
}

export interface MicrowaveRealtimeData {
  device_id?: string
  connection_port?: string
  connection_binding_mode?: string
  binding_label?: string
  binding_resolved?: boolean
  binding_match_count?: number
  binding_error?: string | null
  binding_candidates?: string[]
  running?: boolean
  control_word?: number | null
  control_active?: boolean | null
  output_active?: boolean
  stop_confirmed?: boolean
  status_confirmed?: boolean
  mode?: string
  current_segment?: number
  material_temperature?: number | null
  temperature_source?: string
  power_percent?: number
  current?: number
  runtime_seconds?: number
  fault_code?: number
  faults?: string[]
  current_mode_code?: number
  allow_experiment_control?: boolean
  allow_real_hardware_writes?: boolean
  enable_control_writes?: boolean
  error?: string
}

export interface RealtimeData {
  sampled_at_ms?: number
  snapshot?: boolean
  valves: Record<string, ValveState>
  syringe_pumps: Record<string, SyringeState>
  type: string
  heaters: Record<string, HeaterRealtimeData>
  pumps: Record<string, PumpRealtimeData>
  microwaves: Record<string, MicrowaveRealtimeData>
}

const sharedData = ref<RealtimeData | null>(null)
const sharedConnected = ref(false)
const sharedFresh = ref(false)
// Read-only monitoring tolerates the measured 6–7s full-device sweep.
// Control consumers retain the existing 6s expiry; transport loss clears both.
const monitorData = ref<RealtimeData | null>(null)
const monitorFresh = ref(false)
const monitorHistory = reactive(createMonitorHistory())
const transportState = ref<'connecting' | 'open' | 'closed'>('connecting')
const receivedOnConnection = ref(false)
const monitorState = computed(() => transportState.value === 'connecting' ? 'connecting'
  : transportState.value === 'closed' ? 'disconnected'
  : !receivedOnConnection.value ? 'waiting'
  : monitorFresh.value ? 'live' : 'stale')
let monitorTimer: ReturnType<typeof setTimeout> | null = null
function invalidateMonitor() {
  if (monitorTimer) clearTimeout(monitorTimer)
  monitorTimer = null
  monitorFresh.value = false
  monitorData.value = null
  monitorHistory.interrupted = true
}
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let freshnessTimer: ReturnType<typeof setTimeout> | null = null
let refCount = 0
let latestSampleAt = 0

function invalidateData() {
  if (freshnessTimer) clearTimeout(freshnessTimer)
  freshnessTimer = null
  sharedFresh.value = false
  sharedData.value = null
}

function connect() {
  if (ws && ws.readyState !== WebSocket.CLOSED) {
    return
  }

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  transportState.value = 'connecting'
  receivedOnConnection.value = false
  const socket = new WebSocket(`${protocol}//${location.host}/ws`)
  ws = socket

  socket.onopen = () => {
    if (ws !== socket) return
    sharedConnected.value = true
    transportState.value = 'open'
  }

  socket.onclose = () => {
    if (ws !== socket) return
    sharedConnected.value = false
    transportState.value = 'closed'
    invalidateData()
    invalidateMonitor()
    ws = null
    if (refCount > 0) {
      reconnectTimer = setTimeout(connect, 3000)
    }
  }

  socket.onerror = (err) => {
    if (ws !== socket) return
    console.error('[WS] error', err)
    socket.close()
  }

  socket.onmessage = (event) => {
    if (ws !== socket) return
    try {
      const parsed = JSON.parse(event.data)
      if (parsed?.type === 'monitor_history') {
        if (Array.isArray(parsed.frames)) mergeMonitorFrames(monitorHistory, parsed.frames)
        return
      }
      if (parsed?.type !== 'realtime') return
      const now = Date.now()
      const at = parsed.sampled_at_ms ?? now // Compatibility with older servers.
      if (typeof at !== 'number' || !Number.isFinite(at)) return
      const frame: RealtimeData = {
        ...parsed,
        heaters: parsed.heaters ?? {},
        pumps: parsed.pumps ?? {},
        microwaves: parsed.microwaves ?? {},
        syringe_pumps: parsed.syringe_pumps ?? {},
        valves: parsed.valves ?? {},
      }
      recordMonitorFrame(monitorHistory, frame, at)
      if (at < latestSampleAt) return
      latestSampleAt = at
      const age = Math.max(0, now - at)
      receivedOnConnection.value = true
      if (monitorTimer) clearTimeout(monitorTimer)
      monitorTimer = null
      monitorFresh.value = age < MONITOR_FRESHNESS_MS
      monitorData.value = monitorFresh.value ? frame : null
      if (monitorFresh.value) monitorTimer = setTimeout(invalidateMonitor, MONITOR_FRESHNESS_MS - age)
      if (freshnessTimer) clearTimeout(freshnessTimer)
      freshnessTimer = null
      sharedFresh.value = age < 6000
      sharedData.value = sharedFresh.value ? frame : null
      if (sharedFresh.value) freshnessTimer = setTimeout(invalidateData, 6000 - age)
    } catch (e) {
      console.error('[WS] parse error:', e)
    }
  }
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
  sharedConnected.value = false
  transportState.value = 'closed'
  invalidateData()
  invalidateMonitor()
}

export function useWebSocket() {
  onMounted(() => {
    refCount++
    if (refCount === 1) {
      connect()
    }
  })

  onUnmounted(() => {
    refCount--
    if (refCount <= 0) {
      refCount = 0
      disconnect()
    }
  })

  return { data: sharedData, connected: sharedConnected, fresh: sharedFresh, monitorData, monitorFresh, monitorState, monitorHistory }
}
