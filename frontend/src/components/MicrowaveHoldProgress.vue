<template>
  <div v-if="activity?.wait_type === 'microwave_temperature_reached' && activity.stable_required_seconds != null" class="hold-progress">
    <strong>{{ activity.state === 'failed' ? '稳定到温未完成' : activity.state === 'completed' ? '稳定到温已确认' : activity.paused ? '已暂停，恢复后重新稳定计时' : '等待反应液连续稳定' }}</strong>
    <span>连续稳定 {{ value(activity.stable_seconds) }} / {{ value(activity.stable_required_seconds) }} 秒</span>
    <span v-for="reading in activity.readings || []" :key="reading.device_id">实际 {{ reading.read_ok ? value(reading.value) + '℃' : '温度未知' }} · 目标 {{ value(reading.target) }} ±{{ value(reading.tolerance) }}℃</span>
    <span>温度越界则重新累计；稳定达标后开始定时保温</span>
  </div>
  <div v-else-if="activity && (activity.hold_mode === 'timed' || activity.qualified_seconds != null)" class="hold-progress">
    <strong>{{ activity.state === 'failed' ? '保温未完成' : activity.state === 'completed' ? (activity.hold_mode === 'timed' ? '定时保温完成' : '有效保温完成') : activity.paused ? '已暂停，保温计时暂停' : activity.hold_mode === 'timed' ? (activity.remaining_seconds === 0 ? '等待设备状态确认' : activity.hold_in_band === false ? '温度偏离目标，计时继续' : '正在定时保温') : activity.hold_in_band === false ? '温度越界，暂停累计' : activity.hold_in_band === true ? '正在累计有效保温' : '等待温度确认' }}</strong>
    <span>{{ activity.hold_mode === 'timed' ? '定时保温 ' + value(activity.elapsed_seconds) : '有效保温 ' + value(activity.qualified_seconds) }} / {{ value(activity.duration_seconds) }} 秒</span>
    <span v-if="activity.hold_mode === 'timed'">剩余 {{ value(activity.remaining_seconds) }} 秒 · 实际暂停期间不计时</span>
    <span v-for="reading in activity.readings || []" :key="reading.device_id">实际 {{ reading.read_ok ? value(reading.value) + '℃' : '温度未知' }} · 目标 {{ value(reading.target) }} ±{{ value(reading.tolerance) }}℃</span>
    <span v-if="activity.hold_mode !== 'timed'">已等待 {{ value(activity.elapsed_seconds) }} 秒 · 上限 {{ value(activity.hold_timeout_seconds) }} 秒</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ activity?: {
  state?: string; paused?: boolean; wait_type?: string; stable_seconds?: number | null; stable_required_seconds?: number | null
  hold_mode?: 'timed' | 'qualified'; qualified_seconds?: number | null; duration_seconds?: number | null
  hold_in_band?: boolean | null; elapsed_seconds?: number | null; hold_timeout_seconds?: number | null
  remaining_seconds?: number | null
  readings?: { device_id: string; read_ok: boolean; value?: number | null; target?: number | null; tolerance?: number | null }[]
} | null }>()
function value(number: number | null | undefined) {
  return typeof number === 'number' && Number.isFinite(number) ? String(Math.round(number * 10) / 10) : '未知'
}
</script>

<style scoped>
.hold-progress{display:flex;flex-direction:column;gap:8px;padding:16px;background:#fff;border:1px solid #cfdfeb;border-radius:10px;line-height:1.5;overflow-wrap:anywhere}
.hold-progress span{font-size:13px}.hold-progress strong{font-size:15px;color:#346b69}
</style>
