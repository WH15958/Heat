import { FLOW_UNITS, TIME_UNITS, VOLUME_UNITS, PUMP_MODES, TUBE_MODELS, MICROWAVE_MODES } from '../api/devices'
import heater from '../assets/theme/heater.webp'
import pump from '../assets/theme/pump.webp'
import microwave from '../assets/theme/microwave.webp'
import valve from '../assets/theme/valve.webp'
import syringe from '../assets/theme/syringe-pump.webp'
import type { Step } from './document'

export interface Field {
  key: string; label: string; kind: 'text' | 'number' | 'select' | 'boolean' | 'device'
  required?: boolean; min?: number; max?: number; integer?: boolean
  options?: readonly { value: string | number; label: string }[]
}
export interface Action { type: string; label: string; group: string; position?: string }
export const groups = [
  { key: 'heater', label: '加热器', image: heater, devices: 'heaters' },
  { key: 'pump', label: '蠕动泵', image: pump, devices: 'pumps' },
  { key: 'microwave', label: '微波仪', image: microwave, devices: 'microwaves' },
  { key: 'syringe_pump', label: '注射泵', image: syringe, devices: 'syringe_pumps' },
  { key: 'valve', label: '三通阀', image: valve, devices: 'valves' },
  { key: 'general', label: '通用', image: '', devices: '' },
]
const names: Record<string, Record<string, string>> = {
  heater: { set_temperature: '设置温度', start: '启动加热', stop: '停止加热' },
  pump: { start: '启动泵通道', stop: '停止整台泵', stop_channel: '停止泵通道' },
  microwave: { configure_manual: '配置手动功率', configure_auto_power: '配置自动功率', configure_constant_rate: '配置恒速率', start: '启动微波', stop: '停止微波' },
  syringe_pump: { initialize: '初始化（会运动）', configure: '配置运动参数', move: '绝对定位', aspirate: '吸取', dispense: '排出', valve: '切换阀位', stop: '停止注射泵', resume: '继续 / 释放输入等待', io: '数字输出', program_load: '装载程序', program_store: '存储 EEPROM', program_run: '执行程序', repeat: '重复上次程序' },
  valve: { switch: '选择出液口（NO / NC）' },
  general: { wait: '等待', log: '记录日志', emergency_stop: '紧急停止' },
}
export const actions: Action[] = Object.entries(names).flatMap(([group, entries]) => Object.entries(entries).flatMap(([key, label]) => group === 'valve' ? [
  { group, label: '切到 NO 出口（断电）', type: 'valve.switch', position: 'NO' },
  { group, label: '切到 NC 出口（通电）', type: 'valve.switch', position: 'NC' },
] : [{ group, label, type: group === 'general' ? key : `${group}.${key}` }]))
export const actionLabel = (type: string, params?: Step['params']) => type === 'valve.switch'
  ? params?.position === 'NO' ? '公共口 → NO（断电）' : params?.position === 'NC' ? '公共口 → NC（通电）' : '三通阀：请选择目标出口'
  : actions.find(a => a.type === type)?.label || type
const num = (key: string, label: string, min?: number, max?: number, required = false, integer = false): Field => ({ key, label, kind: 'number', min, max, required, integer })
const select = (key: string, label: string, values: readonly { value: string | number; label: string }[], required = false): Field => ({ key, label, kind: 'select', options: values, required })
const options = (...values: string[]) => values.map(value => ({ value, label: value }))
const device: Field = { key: 'device_id', label: '设备', kind: 'device', required: true }
const channel = num('channel', '通道', 1, 4, true, true)
const timeout = num('timeout', '动作超时（秒，默认 120）', 0.001, 3600)
export function parameterFields(step: Step): Field[] {
  const type = step.type, p = step.params || {}
  const fields: Field[] = type.includes('.') ? [device] : []
  if (type === 'valve.switch') fields.push(select('position', '目标流路（保持至下次切换）', [{ value: 'NO', label: '公共口 → NO（断电）' }, { value: 'NC', label: '公共口 → NC（通电）' }], true))
  if (type === 'heater.set_temperature') fields.push(num('temperature', '目标温度（°C）', undefined, undefined, true))
  if (type === 'pump.stop_channel') fields.push(channel)
  if (type === 'pump.start') {
    fields.push(channel, select('mode', '模式（默认流量模式）', PUMP_MODES), num('flow_rate', '流速（省略时引擎使用 10）', 0.01, 9999), select('flow_unit', '流速单位（默认 mL/min）', FLOW_UNITS), select('direction', '方向（默认 CW）', options('CW', 'CCW')), select('tube_model', '软管型号', TUBE_MODELS))
    if (['TIME_QUANTITY', 'TIME_SPEED'].includes(p.mode)) fields.push(num('run_time', '运行时长', 0.1, 9999, true), select('time_unit', '时间单位（默认秒）', TIME_UNITS))
    if (['TIME_QUANTITY', 'QUANTITY_SPEED'].includes(p.mode)) fields.push(num('dispense_volume', '分装体积', 0.01, 9999, true), select('volume_unit', '体积单位（默认 mL）', VOLUME_UNITS))
    fields.push(num('repeat_count', '重复次数（0 无限；默认 1）', 0, 9999, false, true), num('interval_time', '重复间隔', 0, 999), select('interval_time_unit', '间隔单位（默认秒）', TIME_UNITS))
  }
  if (type === 'microwave.start') fields.push(select('mode', '微波模式', MICROWAVE_MODES, true))
  if (type.startsWith('syringe_pump.')) {
    const action = type.split('.')[1]
    fields.push({ ...timeout, required: ['program_run', 'program_load', 'program_store', 'repeat'].includes(action!) })
    if (action === 'initialize') fields.push(select('direction', '初始化方向（默认 Z）', [{ value: 'Z', label: 'Z：左吸右排' }, { value: 'Y', label: 'Y：右吸左排' }]), select('initialization_code', '初始化代码（默认 0）', [0, 1, 2, ...Array.from({ length: 31 }, (_, i) => i + 10)].map(value => ({ value, label: String(value) }))), { key: 'confirm', label: '确认实验执行时允许初始化运动', kind: 'boolean', required: true })
    if (['move', 'aspirate', 'dispense'].includes(action!)) fields.push(num('speed', '速度（Hz，默认 100）', 5, 5000, false, true))
    if (action === 'move') fields.push(num('position', '绝对位置（步）', 0, 48000, true, true))
    if (['aspirate', 'dispense'].includes(action!)) fields.push(num('volume', '吸排量', 0.000001, undefined, true), select('unit', '单位（默认 µL）', [{ value: 'uL', label: 'µL' }, { value: 'mL', label: 'mL' }, { value: 'steps', label: '步' }]))
    if (action === 'valve') fields.push(select('valve', '阀位（默认进液口）', [{ value: 'input', label: '进液口' }, { value: 'output', label: '排液口' }, { value: 'bypass', label: '旁路' }]))
    if (action === 'io') fields.push(num('output', '输出位掩码', 0, 7, true, true))
    if (['program_load', 'program_store'].includes(action!)) fields.push({ key: 'program', label: '程序（不含末尾 R）', kind: 'text', required: true }, { key: 'name', label: '程序名称', kind: 'text', required: action === 'program_store' })
    if (['program_store', 'program_run'].includes(action!)) fields.push(num('slot', 'EEPROM 槽位（执行时留空表示缓冲）', 0, 14, action === 'program_store', true))
    if (action === 'program_store') fields.push({ key: 'confirm', label: '确认实验执行时允许写入 EEPROM', kind: 'boolean', required: true })
  }
  if (type === 'log') fields.push({ key: 'message', label: '日志内容', kind: 'text' })
  return fields
}
export const settingsFields: Field[] = [
  num('start_speed', '启动速度', 50, 1000, false, true), num('speed', '运行速度', 5, 5000, false, true), num('stop_speed', '停止速度', 50, 2700, false, true), num('acceleration', '加速度代码', 1, 20, false, true), num('speed_code', '速度代码（不与运行速度同时设置）', 0, 40, false, true), select('microstep', '步进模式', [{ value: 0, label: '3000 步' }, { value: 1, label: '48000 步' }, { value: 2, label: '24000 步' }]), num('backlash', '回退间隙', 0, 31, false, true), num('dead_volume', '死区步数', 0, 80, false, true),
]
export const waitOptions = [
  { value: 'heater_pair_stable', label: '等待两路加热器温度稳定' },
  { value: 'microwave_monitored_hold', label: '微波保护保温（每秒监督，失败停止）' },
  { value: 'none', label: '不附加等待' }, { value: 'duration', label: '等待时长' }, { value: 'temperature_reached', label: '等待加热器到温' }, { value: 'pump_complete', label: '等待泵通道完成' }, { value: 'microwave_temperature_reached', label: '等待微波到温' }, { value: 'microwave_temperature_below', label: '等待微波反应液降至温度上限' }, { value: 'microwave_complete', label: '等待微波完成（需实机确认）' }, { value: 'syringe_pump_complete', label: '等待注射泵完成' },
]
export function waitFields(type = 'none'): Field[] {
  if (type === 'none') return []
  if (type === 'duration') return [num('seconds', '等待时长（秒）', 0, undefined, true)]
  if (type === 'heater_pair_stable') return [num('seconds', '连续稳定时长（秒）', 0.001, undefined, true), num('tolerance', '温度容差（°C）', 0), num('timeout', '等待超时（秒）', 0.001)]
  if (type === 'microwave_monitored_hold') return [device, num('seconds', '保护保温时长（整秒，失败停止）', 0, undefined, true, true)]
  const fields: Field[] = [device, num('timeout', '等待超时（秒，默认 3600）', type === 'syringe_pump_complete' ? 0.001 : 0, type === 'syringe_pump_complete' ? 3600 : undefined)]
  if (type === 'pump_complete') fields.push(channel)
  if (type.includes('temperature')) fields.push(num('tolerance', '温度容差（°C，默认 1）', 0))
  if (['microwave_temperature_reached', 'microwave_temperature_below'].includes(type)) fields.push(num('target_temperature', '目标温度（°C）', 0, undefined, true))
  return fields
}
export const heaterStableTargetFields: Field[] = [device, num('target_temperature', '目标温度（°C）', 0, undefined, true)]
export function segmentFields(type: string): Field[] {
  const fields = [num('segment', '段号', 1, 5, true, true)]
  if (type === 'microwave.configure_manual') fields.push(num('heating_temperature', '加热温度 °C', 0, 65535), num('heating_power_percent', '加热功率 %', 0, 100, false, true), num('holding_power_percent', '保温功率 %', 0, 100, false, true), num('holding_deviation', '保温偏差 °C', 0, 65535))
  else fields.push(num('target_temperature', '目标温度 °C', 0, 65535))
  fields.push(num('holding_temperature', '保温温度 °C', 0, 65535))
  if (type === 'microwave.configure_constant_rate') fields.push(...['hours', 'minutes', 'seconds'].map((key, i) => num(`ramp_${key}`, `升温${['时', '分', '秒'][i]}`, 0, 65535, false, true)))
  fields.push(...['hours', 'minutes', 'seconds'].map((key, i) => num(key, `保温${['时', '分', '秒'][i]}`, 0, 65535, false, true)))
  return fields
}
export function executionHint(step: Step) {
  if (step.wait?.type === 'microwave_monitored_hold') return '每秒监督微波温度、故障和控制状态；必须启用且失败停止。先配置一致的设备保温时长，到温后等待，结束后显式停止微波。'
  if (step.type === 'valve.switch') return '选择公共入口通向 NO 或 NC 出口：NO 断电，NC 通电；切换后保持该位置，直到下次明确切换。此动作不启动泵，实际出口需现场确认。'
  if (step.type.startsWith('syringe_pump.') && ['initialize', 'configure', 'move', 'aspirate', 'dispense', 'valve', 'program_run', 'repeat'].includes(step.type.split('.')[1]!)) return '动作完成后继续；暂停实验不打断已下发动作'
  if (['heater.start', 'pump.start', 'microwave.start'].includes(step.type)) return step.wait?.type && step.wait.type !== 'none' ? '启动后按附加等待条件继续' : '确认启动后继续，设备可能持续运行'
  return step.wait?.type && step.wait.type !== 'none' ? '动作后等待条件满足再继续' : '动作返回后继续'
}
export function fieldErrors(fields: Field[], values: Record<string, any>) {
  return fields.flatMap(f => {
    const v = values[f.key], missing = v === undefined || v === null || v === ''
    if (f.required && (missing || (f.kind === 'boolean' && v !== true))) return [`${f.label}：必填`]
    if (missing) return []
    if (f.kind === 'number' && (typeof v !== 'number' || !Number.isFinite(v) || (f.integer && !Number.isInteger(v)) || (f.min != null && v < f.min) || (f.max != null && v > f.max))) return [`${f.label}：数值超出范围或类型错误`]
    if (f.options && !f.options.some(o => o.value === v)) return [`${f.label}：未知选项 ${v}`]
    if (['text', 'device'].includes(f.kind) && typeof v !== 'string') return [`${f.label}：必须是文本`]
    return []
  })
}
