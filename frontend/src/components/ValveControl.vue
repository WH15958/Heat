<template>
  <el-card class="device-card">
    <template #header>
      <div class="card-header">
        <div class="device-heading"><img :src="valveArtwork" alt="" /><div><strong>三通阀</strong><div class="subtitle">{{ valveId }} · 继电器控制</div></div></div>
        <div class="badges">
          <el-tag type="info">串口 {{ state.connection_port || '--' }}</el-tag>
          <el-tag type="info">{{ state.binding_label }}</el-tag>
          <el-tag :type="state.binding_resolved ? 'success' : 'warning'">{{ state.binding_resolved ? '已匹配' : '待匹配' }}</el-tag>
          <el-tag :type="state.connected ? 'success' : 'info'">{{ state.connected ? '已连接' : '未连接' }}</el-tag>
        </div>
      </div>
    </template>
    <div class="controls">
      <div class="row"><span>连接控制</span>
        <el-button v-if="!state.connected" type="primary" :disabled="!state.binding_resolved || busy" @click="operate('connect')">连接设备</el-button>
        <el-button v-else :disabled="busy || state.experiment_owned" @click="operate('disconnect')">断开通讯（保持阀位）</el-button>
        <el-button :disabled="!state.connected || busy" @click="operate('status')">刷新状态</el-button>
      </div>
      <div class="row"><span>继电器状态</span><el-tag :type="state.read_ok ? 'success' : 'warning'">{{ position }}</el-tag></div>
      <div class="row"><span>流路切换</span>
        <el-button type="primary" :disabled="!state.connected || busy || state.experiment_owned" @click="switchPosition(false)">公共口 → NO（断电）</el-button>
        <el-button type="warning" :disabled="!state.connected || busy || state.experiment_owned" @click="switchPosition(true)">公共口 → NC（通电）</el-button>
      </div>
      <el-alert v-if="state.experiment_owned" title="实验占用中：切换和断开由实验控制" type="info" :closable="false" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <p class="hint">NO / NC 指阀体流体口；按 T 型阀及线圈接继电器 NO 回路标注。继电器读回不代表实际流路已确认。请用清水核对两个位置的出口；三通阀断电仍有一路连通。</p>
      <p class="hint">全局急停保持当前阀位，并报告流路停止未确认；断开通讯不会给阀门断电。</p>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import valveArtwork from '../assets/theme/valve.webp'
import { ElMessage, ElMessageBox } from 'element-plus'
import { devicesApi, type ValveState } from '../api/devices'

const props = defineProps<{ valveId: string; state: ValveState }>()
const emit = defineEmits<{ update: [id: string, state: ValveState] }>()
const busy = ref(false)
const error = ref('')
const position = computed(() => !props.state.read_ok || props.state.relay_energized === null
  ? '未知（请刷新）' : props.state.relay_energized ? '吸合 · NC（通电）' : '关闭 · NO（断电）')

async function operate(action: 'connect' | 'disconnect' | 'status' | 'switch', energized?: boolean) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await devicesApi.valveOperation(props.valveId, action, energized)
    if (!res.data.success) throw new Error('设备返回失败')
    emit('update', props.valveId, res.data)
    ElMessage.success(action === 'switch' ? '继电器目标状态读回已确认' : '操作完成')
  } catch (e: any) {
    error.value = e.response?.data?.detail || e.message
    emit('update', props.valveId, { ...props.state, read_ok: false, relay_energized: null })
    // Synchronize connection state after failures without accessing hardware.
    try {
      const res = await devicesApi.list()
      const state = res.data.valves?.[props.valveId]
      if (state) emit('update', props.valveId, state)
    } catch { /* Preserve the visible unknown state if the server is unavailable. */ }
    ElMessage.error(error.value)
  } finally {
    busy.value = false
  }
}

async function switchPosition(energized: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    await ElMessageBox.confirm(
      `确认切换 ${props.valveId}（${props.state.connection_port}）到公共口 → ${energized ? 'NC（通电）' : 'NO（断电）'}？请确认出口、接液容器和现场条件允许切换。`,
      '流路切换确认', { type: 'warning', confirmButtonText: '确认切换', cancelButtonText: '取消' },
    )
  } catch {
    busy.value = false
    return
  }
  busy.value = false
  await operate('switch', energized)
}
</script>

<style scoped>
.device-heading { display: flex; align-items: center; gap: 16px; }
.device-heading img { width: 80px; height: 72px; object-fit: contain; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.card-header strong { font-size: 22px; color: var(--el-color-primary); }
.subtitle, .hint { color: var(--el-text-color-secondary); font-size: 13px; }
.subtitle { margin-top: 6px; }
.badges { display: flex; gap: 8px; flex-wrap: wrap; }
.controls { display: grid; gap: 20px; }
.row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.row > span { width: 100px; color: var(--el-text-color-regular); }
.hint { margin: 0; line-height: 1.6; }
</style>
