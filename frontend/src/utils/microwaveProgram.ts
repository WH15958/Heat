import type { MicrowaveMode, MicrowaveSegmentPayload } from '../api/devices'

export interface MicrowaveSegmentConfig {
  segment: number
  temperature: number
  powerPercent: number
  hours: number
  minutes: number
  seconds: number
}

export interface MicrowaveProgram {
  mode: MicrowaveMode
  usedSegments: number
  segments: Record<number, MicrowaveSegmentConfig>
  configuredProgramKey: string
}

export function microwaveProgramPayload(program: MicrowaveProgram): MicrowaveSegmentPayload[] {
  if (!['manual_power', 'auto_power', 'constant_rate'].includes(program.mode)) {
    throw new Error('微波仪模式不合法')
  }
  if (!Number.isInteger(program.usedSegments) || program.usedSegments < 1 || program.usedSegments > 5) {
    throw new Error('本次使用段数应为 1–5')
  }
  return Array.from({ length: program.usedSegments }, (_, index) => {
    const segment = program.segments[index + 1]
    const inRange = (value: number, max: number) => Number.isFinite(value) && value >= 0 && value <= max
    if (!segment || segment.segment !== index + 1 || !inRange(segment.temperature, 300)
        || ![segment.hours, segment.minutes, segment.seconds].every(Number.isInteger)
        || !inRange(segment.hours, 99) || !inRange(segment.minutes, 59) || !inRange(segment.seconds, 59)
        || (program.mode === 'manual_power' && (!Number.isInteger(segment.powerPercent) || !inRange(segment.powerPercent, 100)))) {
      throw new Error(`第 ${index + 1} 段参数不合法，请检查温度、功率和时间`)
    }
    return {
      segment: segment.segment,
      heating_temperature: segment.temperature,
      target_temperature: segment.temperature,
      holding_temperature: segment.temperature,
      holding_deviation: 0,
      hours: segment.hours,
      minutes: segment.minutes,
      seconds: segment.seconds,
      ramp_hours: 0,
      ramp_minutes: 0,
      ramp_seconds: 0,
      ...(program.mode === 'manual_power' ? {
        heating_power_percent: segment.powerPercent,
        holding_power_percent: segment.powerPercent,
      } : {}),
    }
  })
}

export function microwaveProgramKey(program: MicrowaveProgram): string {
  try {
    return JSON.stringify([program.mode, microwaveProgramPayload(program)])
  } catch {
    return ''
  }
}

export function microwaveProgramConfigured(program: MicrowaveProgram): boolean {
  return Boolean(program.configuredProgramKey) && program.configuredProgramKey === microwaveProgramKey(program)
}

export function hostedMicrowavePayload(program: MicrowaveProgram, requestId: string, confirmed = false) {
  const segments = microwaveProgramPayload(program)
  if (program.mode === 'constant_rate') throw new Error('电脑托管目前支持自动功率和手动功率模式')
  return {
    request_id: requestId, mode: program.mode, hardware_confirmed: confirmed,
    stages: segments.map(s => ({
      temperature: s.heating_temperature,
      hold_seconds: s.hours * 3600 + s.minutes * 60 + s.seconds,
      power_percent: s.heating_power_percent ?? 0,
    })),
  }
}
