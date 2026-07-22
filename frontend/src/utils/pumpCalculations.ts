export function calculateDeadVolumeMl(innerDiameterMm: number, lengthsCm: Array<number | null>): number {
  if (!Number.isFinite(innerDiameterMm) || innerDiameterMm <= 0) return 0

  const totalLengthCm = lengthsCm.reduce<number>((total, lengthCm) => {
    return total + (typeof lengthCm === 'number' && Number.isFinite(lengthCm) && lengthCm > 0 ? lengthCm : 0)
  }, 0)

  return Math.PI * (innerDiameterMm / 2) ** 2 * totalLengthCm / 100
}

export function convertFlowToMlMin(flowRate: number, flowUnit: number): number | null {
  if (!Number.isFinite(flowRate) || flowRate <= 0 || flowUnit === 3) return null
  if (flowUnit === 0) return flowRate / 1000
  if (flowUnit === 2) return flowRate * 1000
  return flowUnit === 1 ? flowRate : null
}

export function calculatePrimingTimeSeconds(deadVolumeMl: number, flowMlMin: number | null): number | null {
  if (!Number.isFinite(deadVolumeMl) || deadVolumeMl <= 0 || flowMlMin === null || flowMlMin <= 0) return null
  return deadVolumeMl / flowMlMin * 60
}

export function normalizeTubeSegmentLengths(value: unknown): Array<number | null> {
  if (!Array.isArray(value)) return [null]
  const lengths = value.filter(
    (length): length is number => typeof length === 'number' && Number.isFinite(length) && length > 0,
  )
  return lengths.length > 0 ? lengths : [null]
}
