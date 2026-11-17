interface TemperatureReading {
  device_id: string
  read_ok: boolean
  value?: number | null
  sampled_at?: number | null
}

export function microwaveTemperatureDisplay(
  deviceId: string,
  program: { state: string; status_error?: string; activity?: { readings?: TemperatureReading[] } | null } | undefined,
  realtime: number | null | undefined,
  connected: boolean,
  now: number,
) {
  const active = program?.state === 'running' || program?.state === 'paused'
  const reading = program?.activity?.readings?.find(item => item.device_id === deviceId)
  const format = (value: number | null | undefined) =>
    typeof value === 'number' && Number.isFinite(value) && value >= 0 ? `${value.toFixed(1)}℃` : '温度未知'
  let text = reading?.read_ok ? format(reading.value) : '温度未知'
  if (active) {
    if (!connected || program?.status_error || !reading?.sampled_at || !reading.read_ok || text === '温度未知') text = '温度未知'
    else if (!Number.isFinite(reading.sampled_at) || now - reading.sampled_at * 1000 >= 6000
      || now < reading.sampled_at * 1000) text = '温度已过期'
  }
  return {
    top: active ? text : connected ? format(realtime) : '温度未知',
    reading: { device_id: deviceId, text, label: active ? '实际' : '最后采样温度' },
  }
}
