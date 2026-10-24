<template>
  <section aria-label="接样转盘设备">
    <TurntableControl v-for="(state, id) in states" :key="id" :state="state" @update="update" />
  </section>
</template>
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { turntableApi, type TurntableState } from '../api/turntables'
import { useWebSocket } from '../composables/useWebSocket'
import TurntableControl from './TurntableControl.vue'
const states = ref<Record<string, TurntableState>>({})
const emit = defineEmits<{ devices: [states: Record<string, TurntableState>] }>()
watch(states, value => emit('devices', value), { deep: true })
const { data, fresh } = useWebSocket()
const expiry = new Map<string, ReturnType<typeof setTimeout>>()
let mounted = false
function hasRevision(state: TurntableState): state is TurntableState & { state_session: string; state_revision: number } {
  return typeof state.state_session === 'string' && Number.isFinite(Date.parse(state.state_session))
    && typeof state.state_revision === 'number' && Number.isSafeInteger(state.state_revision) && state.state_revision > 0
}
function update(state: TurntableState) {
  if (!mounted) return
  const current = states.value[state.device_id]
  if (current && hasRevision(current)) {
    if (!hasRevision(state) || state.state_session < current.state_session) return
    if (state.state_session === current.state_session && state.state_revision <= current.state_revision) {
      // Local HTTP failures may invalidate the current snapshot, never revive it.
      if (state.state_revision === current.state_revision && !state.read_ok) current.read_ok = false
      return
    }
  } else if (current && !hasRevision(state)) {
    const previousRead = Date.parse(current.read_at || '')
    const incomingRead = Date.parse(state.read_at || '')
    if (Number.isFinite(previousRead) && Number.isFinite(incomingRead) && incomingRead < previousRead) return
  }
  clearTimeout(expiry.get(state.device_id))
  const readAt = Date.parse(state.read_at || '')
  const remaining = Number.isFinite(readAt) ? Math.max(0, 6000 - Math.max(0, Date.now() - readAt)) : 0
  states.value[state.device_id] = { ...state, read_ok: state.read_ok && remaining > 0 }
  expiry.set(state.device_id, setTimeout(() => {
    if (states.value[state.device_id]) states.value[state.device_id]!.read_ok = false
    expiry.delete(state.device_id)
  }, remaining))
}
defineExpose({ update })
watch(data, value => { if (value?.turntables) for (const state of Object.values(value.turntables)) update(state) })
watch(fresh, value => { if (!value) for (const state of Object.values(states.value)) state.read_ok = false })
onMounted(async () => {
  mounted = true
  try { for (const state of Object.values((await turntableApi.list()).data.turntables || {})) update(state) }
  catch { ElMessage.error('接样转盘列表读取失败') }
})
onUnmounted(() => { mounted = false; for (const timer of expiry.values()) clearTimeout(timer); expiry.clear() })
</script>
