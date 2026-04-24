import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const PUMP_MODES = [
  { value: 'FLOW_MODE', label: '流量模式', desc: '设置流速持续运行' },
  { value: 'TIME_QUANTITY', label: '定时定量', desc: '设定时间后定量分装' },
  { value: 'TIME_SPEED', label: '定时定速', desc: '设定时间后定速运行' },
  { value: 'QUANTITY_SPEED', label: '定量定速', desc: '设定总量后定速运行' },
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
  ) =>
    api.post(`/pump/${id}/start`, {
      channel,
      flow_rate: flowRate,
      direction,
      mode,
      run_time: runTime ?? null,
      dispense_volume: dispenseVolume ?? null,
    }),
  stopPump: (id: string, channel?: number) =>
    api.post(`/pump/${id}/stop`, { channel: channel ?? null }),

  emergencyStop: () => api.post('/emergency_stop'),
}
