import { editSource, inspectSource, stepsFrom, type Path } from './document'

export interface Variable { key: string; label: string; paths: Path[]; value: number }
export interface Axis extends Variable { mode: 'fixed' | 'range' | 'list'; start: number; end: number; interval: number; list: string }
export const MAX_RUNS = 200

// Only expose quantities with understood semantics; never infer a new device action.
export function variablesFrom(source: string): Variable[] {
  const state = inspectSource(source)
  if (!state.editable) throw new Error(state.errors.join('；') || state.restriction)
  const result: Variable[] = []
  const add = (key: string, label: string, path: Path, value: unknown) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return
    result.push({ key, label, paths: [path], value })
  }
  stepsFrom(state.doc).forEach((s, i) => {
    if (s.enabled === false) return
    const p = s.params || {}, prefix = `${s.id} · ${p.device_id || ''}`
    if (s.type === 'heater.set_temperature') add(`${i}-temperature`, `${prefix} 目标温度（°C）`, ['steps', i, 'params', 'temperature'], p.temperature)
    if (['syringe_pump.aspirate', 'syringe_pump.dispense'].includes(s.type)) {
      add(`${i}-volume`, `${prefix} ${s.type.endsWith('aspirate') ? '吸取' : '排出'}量（${p.unit || 'uL'}）`, ['steps', i, 'params', 'volume'], p.volume)
    }
    if (s.wait?.type === 'duration') add(`${i}-duration`, `${s.id} 等待时长（秒）`, ['steps', i, 'wait', 'seconds'], s.wait.seconds)
  })
  return result
}

export function valuesFor(axis: Axis): number[] {
  let values: number[]
  if (axis.mode === 'list') {
    const tokens = axis.list.trim().split(/[,，\s]+/)
    if (!axis.list.trim()) throw new Error(`${axis.label}：请填写数值列表`)
    values = tokens.map(Number)
  } else if (axis.mode === 'range') {
    const { start, end, interval } = axis
    if (![start, end, interval].every(Number.isFinite) || interval <= 0 || end < start) throw new Error(`${axis.label}：范围必须递增，间隔必须大于 0`)
    const count = Math.floor((end - start) / interval + 1e-9) + 1
    if (count > MAX_RUNS) throw new Error(`每个变量最多 ${MAX_RUNS} 个取值`)
    values = Array.from({ length: count }, (_, i) => Number((start + i * interval).toPrecision(12)))
  } else values = [axis.start]
  if (!values.length || values.length > MAX_RUNS || values.some(v => !Number.isFinite(v))) throw new Error(`${axis.label}：请输入有限数值，最多 ${MAX_RUNS} 项`)
  return [...new Set(values)]
}

export function combinations(axes: Axis[]): number[][] {
  let rows: number[][] = [[]]
  for (const axis of axes) {
    const values = valuesFor(axis)
    if (rows.length * values.length > MAX_RUNS) throw new Error(`组合超过 ${MAX_RUNS} 组，请缩小范围`)
    rows = rows.flatMap(row => values.map(value => [...row, value]))
  }
  return rows
}

export function generateSource(source: string, axes: Axis[], values: number[], batch: string, index: number): string {
  if (!/^[A-Za-z0-9_-]{1,60}$/.test(batch)) throw new Error('批次名称限 1–60 位字母、数字、下划线或短横线')
  if (axes.length !== values.length || values.some(v => !Number.isFinite(v))) throw new Error('条件与变量不匹配')
  return editSource(source, doc => {
    axes.forEach((axis, i) => axis.paths.forEach(path => doc.setIn(path, values[i])))
    if (!doc.get('metadata')) doc.set('metadata', {})
    doc.setIn(['metadata', 'batch_id'], batch)
    doc.setIn(['metadata', 'condition_id'], `condition_${index + 1}`)
    doc.setIn(['metadata', 'sample_index'], index + 1)
    doc.deleteIn(['metadata', 'sample_id'])
    doc.set('name', `${doc.get('name') || '实验'} · ${batch} / ${index + 1}`)
  })
}
