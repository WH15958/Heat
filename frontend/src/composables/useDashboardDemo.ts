import { computed, reactive, ref, onMounted, onUnmounted } from 'vue'
import type { RealtimeData } from './useWebSocket'
import { createMonitorHistory, recordMonitorFrame, MONITOR_FRESHNESS_MS } from '../utils/monitorHistory'

/** Development-only dashboard source. Never opens sockets or calls device APIs. */
export function useDashboardDemo() {
  const data = ref<RealtimeData | null>(null)
  const fresh = ref(false)
  const paused = ref(false)
  const monitorHistory = reactive(createMonitorHistory())
  const monitorState = computed(() => !data.value ? 'waiting' : fresh.value ? 'live' : 'stale')
  const devices = {
    heaters: { heater1: { name: '加热器 1', connected: true }, heater2: { name: '加热器 2', connected: true } },
    microwaves: { microwave1: { name: '微波仪 1', connected: true } },
    pumps: {}, syringe_pumps: {}, valves: {}, turntables: {},
  }
  let timer: ReturnType<typeof setInterval> | undefined
  let tick = 0
  let missed = 0
  function emit() {
    if (paused.value) { if (++missed >= MONITOR_FRESHNESS_MS / 1000) fresh.value = false; return }
    missed = 0
    tick++
    const temperature = (target: number, offset = 0) => Math.min(target, 25 + tick * 1.8 + offset) + Math.sin(tick / 5 + offset) * .4
    data.value = {
      type: 'realtime', heaters: {
        heater1: { pv: temperature(80), sv: 80, mv: tick < 31 ? 85 : 18, alarms: [], run_status: 'RUN' },
        heater2: { pv: temperature(75, -3), sv: 75, mv: tick < 31 ? 80 : 15, alarms: [], run_status: 'RUN' },
      }, microwaves: { microwave1: { material_temperature: temperature(120), power_percent: 40, current: 1.2, runtime_seconds: tick, current_segment: 1, mode: 'auto_power', fault_code: 0, control_active: true, output_active: true } },
      pumps: {}, syringe_pumps: {}, valves: {}, turntables: {},
    }
    fresh.value = true
    recordMonitorFrame(monitorHistory, data.value!, Date.now())
  }
  onMounted(() => { emit(); timer = setInterval(emit, 1000) })
  onUnmounted(() => { if (timer) clearInterval(timer) })
  return { data, fresh, paused, devices, monitorState, monitorHistory }
}
