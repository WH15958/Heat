import { turntableBottleLabel } from './guidedProgress'

export function collectionCapacity(config: any): number {
  if (config?.collection_axis === 'rotation') {
    return JSON.stringify(config.ring_counts) === '[28,20,16,8]' ? 72 : 0
  }
  return Number.isInteger(config?.bottle_count) && config.bottle_count > 0 ? config.bottle_count : 0
}

export function collectionConfigError(axes: Record<string, any>): string {
  const rotation = axes.turntable1
  if (!rotation || rotation.configured === false || rotation.enabled === false) return '固定转盘 turntable1 未配置或未启用'
  if (!collectionCapacity(rotation)) return '接样瓶位配置无效'
  if (!rotation.home_enabled || !rotation.position_encoding_verified) return '转盘机械回零或定位功能尚未启用'
  if (rotation.collection_axis === 'rotation') {
    const platform = axes[rotation.collection_peer]
    if (!platform || platform.collection_axis !== 'radial' || platform.collection_peer !== 'turntable1'
      || platform.configured === false || platform.enabled === false || !platform.position_encoding_verified
      || JSON.stringify(platform.ring_positions) !== JSON.stringify(rotation.ring_positions)
      || JSON.stringify(platform.ring_counts) !== JSON.stringify(rotation.ring_counts)) return '移动平台配对或标定配置未完成'
  } else if (!Number.isInteger(rotation.pulses_per_bottle) || rotation.pulses_per_bottle <= 0) return '转盘瓶位配置无效'
  return ''
}

export function collectionLocationLabel(location: any): string {
  const bottle = turntableBottleLabel(location?.bottle_number)
  return Number.isInteger(location?.collection_ring) && location.collection_ring >= 1 && location.collection_ring <= 4
    ? `第${location.collection_ring}圈 · ${bottle}${Number.isInteger(location.ring_bottle_number) ? `（圈内${location.ring_bottle_number}号）` : ''}` : bottle
}
