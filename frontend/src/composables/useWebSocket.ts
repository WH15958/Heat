import { ref, onMounted, onUnmounted } from 'vue'

export interface HeaterRealtimeData {
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
}

export interface PumpRealtimeData {
  device_id: string
  channels: Record<string, PumpChannelData>
  error?: string
}

export interface RealtimeData {
  type: string
  heaters: Record<string, HeaterRealtimeData>
  pumps: Record<string, PumpRealtimeData>
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
      sharedData.value = JSON.parse(event.data)
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
