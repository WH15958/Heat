export const phaseNames = ['准备 / 进料', '启动及等待到温', '保温计时', '停机 / 冷却 / 切阀', '收集', '清洗', '其他 / 步骤间隔']
export const phaseColors = ['#8796aa', '#ed9e37', '#3586c6', '#78b8b0', '#9767b0', '#7eab65', '#c3cbd4']

export interface BatchChartRun {
  index: number
  runId: string
  start: string
  end: string
  total: number | null
  phases: number[]
  intervals: { phase: number; start: number; end: number }[]
  target: number | null
  temperature: { id: string; points: [number, number | null][] }[]
}
