// Theoretical transport estimate only; no physical empty-state inference.
export function estimateDrainSeconds(volumeMl: number, flowMlPerMinute: number): number {
  if (!Number.isFinite(volumeMl) || volumeMl <= 0 || !Number.isFinite(flowMlPerMinute) || flowMlPerMinute <= 0) {
    throw new Error('体积与抽液流量必须为有限正数')
  }
  const seconds = volumeMl / flowMlPerMinute * 60
  if (!Number.isFinite(seconds) || seconds <= 0) throw new Error('抽液时间超出有效范围')
  return Number(seconds.toPrecision(10))
}
