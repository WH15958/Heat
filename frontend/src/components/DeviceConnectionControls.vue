<template>
  <div class="device-connection">
    <el-button v-if="!connected" type="primary" size="default" :loading="working" :disabled="locked || connectDisabled" @click="emit('connect')">{{ working ? '连接中…' : '连接设备' }}</el-button>
    <el-button v-else size="default" :loading="working" :disabled="locked || disconnectDisabled" @click="emit('disconnect')">{{ working ? '处理中…' : '断开连接' }}</el-button>
    <small v-if="hint">{{ hint }}</small>
  </div>
</template>
<script setup lang="ts">
import { computed, inject, onUnmounted, watch } from 'vue'
import { connectionBatchKey } from '../composables/connectionBatch'
const props = defineProps<{ deviceKey: string; connected: boolean; loading?: boolean; connectDisabled?: boolean; disconnectDisabled?: boolean; hint?: string }>()
const emit = defineEmits<{ connect: []; disconnect: [] }>()
const batch = inject(connectionBatchKey, undefined)
const token = Symbol('connection-control')
watch(() => props.loading, value => { if (value) batch?.pending.add(token); else batch?.pending.delete(token) }, { immediate: true, flush: 'sync' })
onUnmounted(() => batch?.pending.delete(token))
const locked = computed(() => Boolean(props.loading || batch?.running.value))
const working = computed(() => Boolean(props.loading || batch?.current.value === props.deviceKey))
</script>
<style scoped>
.device-connection { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; flex-shrink: 0; }
.device-connection .el-button { min-width: 112px; margin: 0; filter: none; transform: none; }
.device-connection small { max-width: 180px; font-size: 12px; color: var(--el-text-color-secondary); }
.device-connection .el-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 3px; }
@media (max-width: 700px) { .device-connection { align-items: flex-start; width: 100%; } }
</style>
