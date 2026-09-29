<template>
  <section aria-label="注射泵设备">
    <SyringePumpControl v-for="(state, id) in states" :key="id" :state="state" @update="update" />
  </section>
</template>
<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { syringeApi, type SyringeState } from '../api/syringePumps'
import { useWebSocket } from '../composables/useWebSocket'
import SyringePumpControl from './SyringePumpControl.vue'
const states = ref<Record<string, SyringeState>>({})
const emit = defineEmits<{ devices: [states: Record<string, SyringeState>] }>()
watch(states, value => emit('devices', value), { deep: true })
const { data, connected } = useWebSocket()
function update(state: SyringeState) { states.value[state.device_id] = state }
watch(data, value => { if (value?.syringe_pumps) states.value = value.syringe_pumps })
watch(connected, value => { if (!value) for (const state of Object.values(states.value)) state.read_ok = false })
onMounted(async () => { try { states.value = (await syringeApi.list()).data.syringe_pumps ?? {} } catch { ElMessage.error('注射泵列表读取失败') } })
</script>
