const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const validRow = (row: unknown): row is number[] => Array.isArray(row) && row.length === 6 && row.every(finite)
export const hasGuidedAxes = (request: any): boolean => Array.isArray(request?.axes) && request.axes.length === 6 &&
  request.axes.every((axis: unknown) => Array.isArray(axis) && axis.length > 0 && axis.every(finite))

export function guidedHistoryGroups(batch: any, plan: any) {
  const saved = plan?.batch_id === batch?.batch_id ? plan : null
  const request = batch?.request ?? saved?.request
  return Array.from({length: batch?.total_groups || 0}, (_, i) => {
    const recorded = batch.groups?.find((group: any) => group.index === i + 1)
    const recipe = saved?.recipes?.find((r: any, index: number) => (r.metadata?.sample_index ?? index + 1) === i + 1)
    let parameters = recorded?.parameters
    let conditionSource = '执行记录中的设定条件'
    if (!validRow(parameters)) {
      parameters = recipe?.metadata?.guided_parameters
      conditionSource = recorded && recorded.state !== 'pending' ? '计划条件（执行条件未记录）' : '计划条件（未执行）'
      if (!validRow(parameters) && hasGuidedAxes(request) && Number.isInteger(request.repeats) && request.repeats > 0) {
        let index = Math.floor(i / request.repeats)
        const row = Array<number>(6)
        for (let axis = 5; axis >= 0; axis--) {
          const values = request.axes[axis]
          row[axis] = values[index % values.length]
          index = Math.floor(index / values.length)
        }
        if (index === 0) parameters = row
      }
    }
    return {...recorded, index: i + 1, state: recorded?.state || 'pending',
      parameters: validRow(parameters) ? parameters : null,
      conditionSource: validRow(parameters) ? conditionSource : '条件未记录'}
  })
}

// Copy input parameters only. Execution identity, confirmations and priming eligibility never enter a draft.
export function guidedHistoryDraft(request: any, sourceName: string) {
  if (!hasGuidedAxes(request)) throw new Error('历史条件缺失或格式无效，无法复用，请手动新建实验。')
  const copy: Record<string, any> = {axes: request.axes.map((axis: number[]) => [...axis])}
  for (const key of ['repeats', 'speed_a', 'speed_b', 'drain_flow', 'product_drain_seconds', 'clean_drain_seconds',
    'clean_volume', 'clean_flow', 'clean_dwell', 'clean_cycles', 'turntable_drip_seconds', 'prime_heat_minutes',
    'prime_volume_a', 'prime_volume_b', 'prime_cycles', 'prime_drain_flow', 'prime_drain_seconds',
    'reactor_available_ml', 'source_available_a_ml', 'source_available_b_ml', 'waste_available_ml']) {
    copy[key] = finite(request[key]) ? request[key] : null
  }
  for (const key of ['drain_direction', 'clean_direction']) {
    if (['CW', 'CCW'].includes(request[key])) copy[key] = request[key]
  }
  for (const key of ['initialization_a', 'initialization_b']) {
    if (request[key]) copy[key] = {direction: request[key].direction, initialization_code: request[key].initialization_code}
  }
  return {version: 1, kind: 'guided-history', sourceName, request: copy}
}
