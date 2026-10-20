<template>
  <div v-if="activity?.qualified_seconds != null" class="hold-progress">
    <strong>{{ activity.state === 'failed' ? '保温未完成' : activity.state === 'completed' ? '有效保温完成' : activity.paused ? '已暂停，保温计时暂停' : activity.hold_in_band === false ? '温度越界，暂停累计' : activity.hold_in_band === true ? '正在累计有效保温' : '等待温度确认' }}</strong>
    <span>有效保温 {{ value(activity.qualified_seconds) }} / {{ value(activity.duration_seconds) }} 秒</span>
    <span v-for="reading in activity.readings || []" :key="reading.device_id">实际 {{ reading.read_ok ? value(reading.value) + '℃' : '温度未知' }} · 目标 {{ value(reading.target) }} ±{{ value(reading.tolerance) }}℃</span>
    <span>已等待 {{ value(activity.elapsed_seconds) }} 秒 · 上限 {{ value(activity.hold_timeout_seconds) }} 秒</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ activity?: {
  state?: string; paused?: boolean; qualified_seconds?: number | null; duration_seconds?: number | null
  hold_in_band?: boolean | null; elapsed_seconds?: number | null; hold_timeout_seconds?: number | null
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
