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

export function useWebSocket() {
  const data = ref<RealtimeData | null>(null)
  const connected = ref(false)
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${protocol}//${location.host}/ws`)

    ws.onopen = () => {
      connected.value = true
      console.log('WebSocket connected')
    }

    ws.onclose = () => {
      connected.value = false
      console.log('WebSocket disconnected, reconnecting in 3s...')
      reconnectTimer = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws?.close()
    }

    ws.onmessage = (event) => {
      try {
        data.value = JSON.parse(event.data)
      } catch (e) {
        console.error('Failed to parse WebSocket data:', e)
      }
    }
  }

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    ws?.close()
    if (reconnectTimer) clearTimeout(reconnectTimer)
  })

  return { data, connected }
}
