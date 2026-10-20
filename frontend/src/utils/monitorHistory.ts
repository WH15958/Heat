import type { HeaterRealtimeData, MicrowaveRealtimeData, RealtimeData } from '../composables/useWebSocket'

export const MONITOR_FRESHNESS_MS = 15000
const MAX_POINTS = 1800
export type MonitorPoint = [number, number | null]

export interface MonitorFrame {
  sampled_at_ms: number
  heaters?: Record<string, Partial<HeaterRealtimeData>>
  microwaves?: Record<string, Partial<MicrowaveRealtimeData>>
  pumps?: RealtimeData['pumps']
}

interface TrendFrame {
  sampled_at_ms: number
  heaters: Record<string, { pv: number | null; sv: number | null }>
  microwaves: Record<string, { material_temperature: number | null }>
  pumps: Record<string, { channels: Record<string, number | null> }>
  interruptedAfter?: number
}

export function createMonitorHistory() {
  return {
    lastReceivedAt: 0,
    revision: 0,
    interrupted: false,
    frames: [] as TrendFrame[],
    heaters: {} as Record<string, { pv: MonitorPoint[]; sv: MonitorPoint[] }>,
    microwaves: {} as Record<string, { temperature: MonitorPoint[] }>,
    pumps: {} as Record<string, { channels: Record<string, MonitorPoint[]> }>,
    lastHeaters: {} as Record<string, Partial<HeaterRealtimeData>>,
    lastMicrowaves: {} as Record<string, MicrowaveRealtimeData>,
  }
}

export type MonitorHistory = ReturnType<typeof createMonitorHistory>

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function trendFrame(data: MonitorFrame): TrendFrame {
  const frame: TrendFrame = { sampled_at_ms: data.sampled_at_ms, heaters: {}, microwaves: {}, pumps: {} }
  for (const [id, heater] of Object.entries(data.heaters ?? {})) {
    frame.heaters[id] = { pv: heater.error ? null : finite(heater.pv), sv: heater.error ? null : finite(heater.sv) }
  }
  for (const [id, microwave] of Object.entries(data.microwaves ?? {})) {
    frame.microwaves[id] = { material_temperature: microwave.error ? null : finite(microwave.material_temperature) }
  }
  for (const [id, pump] of Object.entries(data.pumps ?? {})) {
    const channels: Record<string, number | null> = {}
    for (const [channel, reading] of Object.entries(pump.error ? {} : pump.channels ?? {})) {
      let flow: number | null = null
      if (reading.read_ok === true && typeof reading.running === 'boolean') {
        if (!reading.running) flow = 0
        else if (finite(reading.flow_rate) !== null) {
          const factor = { UL_MIN: .001, ML_MIN: 1, L_MIN: 1000 }[reading.flow_unit || '']
          if (factor !== undefined) flow = reading.flow_rate! * factor
        }
      }
      channels[channel] = flow
    }
    frame.pumps[id] = { channels }
  }
  return frame
}

function append(points: MonitorPoint[], at: number, value: number | null, interrupted: boolean) {
  const last = points.at(-1)
  if (value === null && (!last || last[1] === null)) return
  if (value !== null && last?.[1] != null && (interrupted || at - last[0] > MONITOR_FRESHNESS_MS)) {
    points.push([at - 1, null])
  }
  points.push([at, value])
  if (points.length > MAX_POINTS) points.splice(0, points.length - MAX_POINTS)
}

function consume(history: MonitorHistory, frame: TrendFrame) {
  const at = frame.sampled_at_ms
  const interrupted = frame.interruptedAfter !== undefined
  for (const id of new Set([...Object.keys(history.heaters), ...Object.keys(frame.heaters)])) {
    const heater = frame.heaters[id]
    if (!history.heaters[id] && heater?.pv == null && heater?.sv == null) continue
    const series = history.heaters[id] ??= { pv: [], sv: [] }
    append(series.pv, at, heater?.pv ?? null, interrupted)
    append(series.sv, at, heater?.sv ?? null, interrupted)
    if (heater?.pv != null || heater?.sv != null) {
      const last = history.lastHeaters[id] ??= {}
      if (heater.pv != null) last.pv = heater.pv
      if (heater.sv != null) last.sv = heater.sv
    }
  }
  for (const id of new Set([...Object.keys(history.microwaves), ...Object.keys(frame.microwaves)])) {
    const temperature = frame.microwaves[id]?.material_temperature ?? null
    if (!history.microwaves[id] && temperature === null) continue
    const series = history.microwaves[id] ??= { temperature: [] }
    append(series.temperature, at, temperature, interrupted)
    if (temperature !== null) history.lastMicrowaves[id] = { material_temperature: temperature }
  }
  for (const id of new Set([...Object.keys(history.pumps), ...Object.keys(frame.pumps)])) {
    const channels = frame.pumps[id]?.channels ?? {}
    const series = history.pumps[id] ??= { channels: {} }
    for (const channel of new Set([...Object.keys(series.channels), ...Object.keys(channels)])) {
      append(series.channels[channel] ??= [], at, channels[channel] ?? null, interrupted)
    }
  }
}

function rebuild(history: MonitorHistory) {
  // Keep the maps themselves: Dashboard holds references to these reactive maps.
  for (const map of [history.heaters, history.microwaves, history.pumps, history.lastHeaters, history.lastMicrowaves]) {
    for (const id of Object.keys(map)) delete map[id]
  }
  for (const frame of history.frames) consume(history, frame)
  history.lastReceivedAt = history.frames.at(-1)?.sampled_at_ms ?? 0
}

export function mergeMonitorFrames(history: MonitorHistory, frames: MonitorFrame[]) {
  const incoming = frames.filter(frame => Number.isFinite(frame.sampled_at_ms) && frame.sampled_at_ms >= 0)
  if (!incoming.length) return
  const previousLast = history.lastReceivedAt
  const byTime = new Map(history.frames.map(frame => [frame.sampled_at_ms, { ...frame }]))
  for (const frame of incoming) byTime.set(frame.sampled_at_ms, trendFrame(frame))
  const times = incoming.map(frame => frame.sampled_at_ms)
  for (const frame of byTime.values()) {
    if (frame.interruptedAfter !== undefined && times.some(at => at > frame.interruptedAfter! && at <= frame.sampled_at_ms)) {
      delete frame.interruptedAfter
    }
  }
  const merged = [...byTime.values()].sort((a, b) => a.sampled_at_ms - b.sampled_at_ms).slice(-MAX_POINTS)
  if (times.some(at => at >= previousLast)) history.interrupted = false
  if (JSON.stringify(merged) === JSON.stringify(history.frames)) return
  history.frames = merged
  rebuild(history)
  history.revision++
}

export function recordMonitorFrame(history: MonitorHistory, data: RealtimeData, at: number) {
  if (!Number.isFinite(at) || at < 0) return
  const frame = trendFrame({ ...data, sampled_at_ms: at })
  const last = history.frames.at(-1)
  const newer = !last || at > last.sampled_at_ms
  if (history.interrupted && last && newer) frame.interruptedAfter = history.lastReceivedAt
  if (newer) {
    history.frames.push(frame)
    if (history.frames.length > MAX_POINTS) history.frames.splice(0, history.frames.length - MAX_POINTS)
    consume(history, frame)
    history.lastReceivedAt = at
  } else {
    const byTime = new Map(history.frames.map(saved => [saved.sampled_at_ms, saved]))
    const previous = byTime.get(at)
    if (previous?.interruptedAfter !== undefined) frame.interruptedAfter = previous.interruptedAfter
    byTime.set(at, frame)
    const merged = [...byTime.values()].sort((a, b) => a.sampled_at_ms - b.sampled_at_ms).slice(-MAX_POINTS)
    if (JSON.stringify(merged) === JSON.stringify(history.frames)) return
    history.frames = merged
    rebuild(history)
  }
  if (newer) history.interrupted = false
  history.revision++
}
