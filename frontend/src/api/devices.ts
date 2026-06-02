import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const PUMP_MODES = [
  { value: 'FLOW_MODE', label: '流量模式', desc: '设置流速持续运行' },
  { value: 'TIME_QUANTITY', label: '定时定量', desc: '设定时间后定量分装' },
  { value: 'TIME_SPEED', label: '定时定速', desc: '设定时间后定速运行' },
  { value: 'QUANTITY_SPEED', label: '定量定速', desc: '设定总量后定速运行' },
] as const

export const TUBE_MODELS = [
  { value: 0, label: '1×1', maxFlow: 7.55 },
  { value: 1, label: '2×1', maxFlow: 27.52 },
  { value: 2, label: '2.4×0.86', maxFlow: 38.13 },
  { value: 3, label: '3×1', maxFlow: 48.38 },
  { value: 4, label: '0.13×0.86', maxFlow: 0.29 },
  { value: 5, label: '0.19×0.86', maxFlow: 0.44 },
  { value: 6, label: '0.25×0.86', maxFlow: 0.76 },
  { value: 7, label: '0.51×0.86', maxFlow: 2.00 },
  { value: 8, label: '0.89×0.86', maxFlow: 4.47 },
  { value: 9, label: '1.14×0.86', maxFlow: 9.16 },
  { value: 10, label: '1.42×0.86', maxFlow: 18.75 },
  { value: 11, label: '1.52×0.86', maxFlow: 22.0 },
  { value: 12, label: '2.06×0.86', maxFlow: 29.60 },
  { value: 13, label: '2.79×0.86', maxFlow: 42.86 },
] as const

export const FLOW_UNITS = [
  { value: 0, label: 'uL/min' },
  { value: 1, label: 'mL/min' },
  { value: 2, label: 'L/min' },
  { value: 3, label: 'RPM' },
] as const

export const TIME_UNITS = [
  { value: 0, label: '秒(sec)' },
  { value: 1, label: '分(min)' },
  { value: 2, label: '时(hour)' },
] as const

export const VOLUME_UNITS = [
  { value: 0, label: 'uL' },
  { value: 1, label: 'mL' },
  { value: 2, label: 'L' },
] as const

export type PumpMode = typeof PUMP_MODES[number]['value']

export const devicesApi = {
  list: () => api.get('/devices'),

  connectHeater: (id: string) => api.post(`/heater/${id}/connect`),
  disconnectHeater: (id: string) => api.post(`/heater/${id}/disconnect`),
  readHeaterData: (id: string) => api.get(`/heater/${id}/data`),
  setTemperature: (id: string, temperature: number) =>
    api.post(`/heater/${id}/set_temperature`, { temperature }),
  startHeater: (id: string) => api.post(`/heater/${id}/start`),
  stopHeater: (id: string) => api.post(`/heater/${id}/stop`),

  connectPump: (id: string) => api.post(`/pump/${id}/connect`),
  disconnectPump: (id: string) => api.post(`/pump/${id}/disconnect`),
  readPumpStatus: (id: string) => api.get(`/pump/${id}/status`),
  startPump: (
    id: string,
    channel: number,
    flowRate: number,
    direction = 'CW',
    mode: PumpMode = 'FLOW_MODE',
    runTime?: number,
    dispenseVolume?: number,
    tubeModel?: number,
    flowUnit?: number,
    timeUnit?: number,
    volumeUnit?: number,
    repeatCount?: number,
    intervalTime?: number,
    intervalTimeUnit?: number,
  ) =>
    api.post(`/pump/${id}/start`, {
      channel,
      flow_rate: flowRate,
      direction,
      mode,
      run_time: runTime ?? null,
      dispense_volume: dispenseVolume ?? null,
      tube_model: tubeModel ?? null,
      flow_unit: flowUnit ?? null,
      time_unit: timeUnit ?? null,
      volume_unit: volumeUnit ?? null,
      repeat_count: repeatCount ?? null,
      interval_time: intervalTime ?? null,
      interval_time_unit: intervalTimeUnit ?? null,
    }),
  stopPump: (id: string, channel?: number) =>
    api.post(`/pump/${id}/stop`, { channel: channel ?? null }),

  emergencyStop: () => api.post('/emergency_stop'),
}
