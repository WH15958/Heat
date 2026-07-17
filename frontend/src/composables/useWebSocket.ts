import { ref, onMounted, onUnmounted } from 'vue'

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
  running: boolean
  flow_rate: number
  volume: number
  direction: string | null
  flow_unit: string
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
  type: string
  heaters: Record<string, HeaterRealtimeData>
  pumps: Record<string, PumpRealtimeData>
  microwaves: Record<string, MicrowaveRealtimeData>
}

const sharedData = ref<RealtimeData | null>(null)
const sharedConnected = ref(false)
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let refCount = 0

function connect() {
  if (ws && ws.readyState !== WebSocket.CLOSED) {
    return
  }

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${protocol}//${location.host}/ws`)

  ws.onopen = () => {
    sharedConnected.value = true
  }

  ws.onclose = () => {
    sharedConnected.value = false
    ws = null
    if (refCount > 0) {
      reconnectTimer = setTimeout(connect, 3000)
    }
  }

  ws.onerror = (err) => {
    console.error('[WS] error', err)
    ws?.close()
  }

  ws.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data)
      if (parsed?.type !== 'realtime') return
      sharedData.value = {
        ...parsed,
        heaters: parsed.heaters ?? {},
        pumps: parsed.pumps ?? {},
        microwaves: parsed.microwaves ?? {},
      }
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

  return { data: sharedData, connected: sharedConnected }
}
