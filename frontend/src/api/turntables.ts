import axios from 'axios'

export interface TurntableState {
  device_id: string
  name: string
  configured: boolean
  connected: boolean
  state_session?: string
  state_revision?: number
  connection_port?: string
  connection_error?: string | null
  connection_binding_mode?: string
  binding_label?: string
  binding_resolved?: boolean
  binding_match_count?: number
  binding_error?: string | null
  binding_candidates?: string[]
  read_ok: boolean
  read_at?: string | null
  read_error?: string | null
  busy: boolean | null
  position: number | null
  speed_raw: number | null
  input_raw: number | null
  inputs: { positive_limit: boolean | null; home: boolean | null; negative_limit: boolean | null; input4: boolean | null } | null
  work_state: number | null
  state_name: string
  stop_confirmed: boolean
  motion_blocked: boolean
  homed: boolean
  home_enabled: boolean
  position_encoding_verified: boolean
  bottle_count?: number
  pulses_per_bottle?: number
  current_bottle?: number | null
  next_bottle?: number | null
  bottle_ready?: boolean
  bottle_error?: string | null
  bottle_token?: string | null
  action?: { action: string; result: string; target?: number; error?: string; duration_seconds?: number; requested_speed?: number; target_bottle?: number; from_bottle?: number } | null
}

export type TurntableDirection = 'positive' | 'negative'
export type TurntableCommand =
  | { action: 'stop' }
  | { action: 'home_bottle' }
  | { action: 'next_bottle'; expected_position: number; expected_bottle_token: string }
  | { action: 'move_relative'; steps: number; speed: number }
  | { action: 'move_absolute'; position: number; speed: number }
  | { action: 'run'; direction: TurntableDirection; duration_seconds: number; speed: number }
  | { action: 'home'; direction: TurntableDirection; speed: number }

export const turntableApi = {
  list: () => axios.get<{ turntables?: Record<string, TurntableState> }>('/api/devices'),
  connect: (id: string) => axios.post(`/api/turntable/${id}/connect`),
  disconnect: (id: string) => axios.post(`/api/turntable/${id}/disconnect`),
  read: (id: string) => axios.get<TurntableState>(`/api/turntable/${id}/status`),
  command: (id: string, body: TurntableCommand) => axios.post(`/api/turntable/${id}/command`, body),
}

export const turntableResult: Record<string, string> = {
  accepted: '请求已接受，等待确认', running: '运行中', completed: '控制器确认完成',
  failed: '失败', unknown: '结果未知', stopped: '停止已确认',
  stop_requested: '停止已请求', stop_unconfirmed: '停止未确认',
}

export const turntableWorkState: Record<string, string> = {
  unknown: '未知', reset: '复位状态', positioning: '定位中', manual: '连续运行中', homing: '机械回零中', stopped: '已停止',
}
