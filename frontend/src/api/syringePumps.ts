import axios from 'axios'

export interface SyringeState {
  device_id: string
  name: string
  connected: boolean
  configured: boolean
  connection_port?: string
  binding_resolved?: boolean
  binding_error?: string
  capacity_ml: number
  address: number
  orientation?: 'Z' | 'Y' | null
  microstep?: number | null
  read_ok: boolean
  busy?: boolean | null
  initialized?: boolean | null
  position?: number | null
  position_trusted: boolean
  theoretical_volume_ul?: number | null
  valve_position?: number | null
  fault_code?: number | null
  fault_description?: string | null
  read_error?: string | null
  read_at?: string | null
  owner?: string | null
  stop_confirmed?: boolean
  action?: { action?: string; result?: string; target?: number; error?: string; waits_input?: boolean }
}

export const syringeApi = {
  list: () => axios.get('/api/devices'),
  connect: (id: string) => axios.post(`/api/syringe_pump/${id}/connect`),
  disconnect: (id: string) => axios.post(`/api/syringe_pump/${id}/disconnect`),
  read: (id: string) => axios.get<SyringeState>(`/api/syringe_pump/${id}/status`),
  diagnostics: (id: string) => axios.get(`/api/syringe_pump/${id}/diagnostics`),
  programs: (id: string) => axios.get(`/api/syringe_pump/${id}/programs`),
  command: (id: string, body: Record<string, unknown>) => axios.post(`/api/syringe_pump/${id}/command`, body),
}

export const syringeResult: Record<string, string> = {
  accepted: '指令已接受', running: '运行中', completed: '设备确认完成',
  failed: '失败', unknown: '结果未知', stopped: '已请求停止', paused: '硬件暂停',
  sent_unverified: '已发送，未完整验证', stop_requested: '停止已请求',
  stop_unconfirmed: '停止未确认',
}
