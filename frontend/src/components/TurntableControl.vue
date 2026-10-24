<template>
  <section class="turntable-panel" :aria-label="`${state.name}控制`">
    <div class="panel-heading">
      <div class="identity"><img :src="turntableArtwork" alt="" /><strong>{{ state.name }}</strong><span>CL-01A</span><el-tag size="small" :type="state.connected ? 'success' : 'info'">{{ state.connected ? '已连接' : state.configured ? '未连接' : '待配置' }}</el-tag></div>
      <DeviceConnectionControls :device-key="'turntable:'+state.device_id" :connected="state.connected" :loading="pending > 0" :connect-disabled="!state.configured || state.binding_resolved === false" :disconnect-disabled="state.busy !== false || !state.read_ok || actionActive || state.motion_blocked" @connect="connect" @disconnect="disconnect" />
    </div>
    <div class="toolbar"><el-button :disabled="!state.connected || pending > 0" @click="refresh">刷新状态</el-button><el-button type="danger" plain :loading="stopping > 0" :disabled="!state.connected" @click="send({ action: 'stop' })">{{ stopping > 0 ? '正在确认停止…' : '停止' }}</el-button></div>
    <p v-if="stopping > 0" role="status" aria-live="polite">停止请求已提交，正在等待控制器确认。</p>
    <el-alert v-if="state.binding_error" :title="state.binding_error" type="warning" :closable="false" />
    <el-alert v-else-if="!state.connected && state.connection_error" :title="'连接失败：' + state.connection_error" type="error" :closable="false" />
    <el-alert v-else-if="state.connected && !state.read_ok" :title="state.read_error || '状态未知或已过期，请刷新后操作。停止仍可用。'" type="warning" :closable="false" />
    <div class="status-line" aria-live="polite">
      <div><span>当前瓶位</span><strong>{{ currentBottle === null ? '未确认' : `${currentBottle}号瓶` }}</strong></div>
      <div><span>运行状态</span><strong>{{ state.read_ok ? turntableWorkState[state.state_name] || '未知' : '未知' }}</strong></div>
      <div><span>停止确认</span><strong>{{ stopping > 0 ? '确认中' : state.read_ok ? state.stop_confirmed ? '已确认' : '未确认' : '未知' }}</strong></div>
      <div><span>当前动作</span><strong>{{ state.read_ok ? turntableResult[state.action?.result || ''] || '无' : '未知' }}</strong></div>
    </div>
    <p v-if="state.action?.error" class="action-error">{{ state.action.error }}</p>
    <div class="bottle-actions actions">
      <el-button :disabled="!canHomeBottle" title="机械回零，回到1号瓶" @click="send({ action: 'home_bottle' })">回原点</el-button>
      <el-button type="primary" :disabled="!canNextBottle" :title="currentBottle !== null && state.next_bottle != null ? `下一瓶：${state.next_bottle}号瓶` : '按瓶号顺序前进一格'" @click="nextBottle">下一瓶</el-button>
    </div>
    <p v-if="bottleConfigured">共{{ state.bottle_count }}个瓶位，1号瓶为机械原点。瓶号顺时针标记，切换下一瓶时转盘逆时针转动；最后一瓶之后返回1号。</p>
    <p v-if="!bottleConfigured" class="disabled-reason">尚未配置瓶位标定，常用换瓶操作不可用。</p>
    <p v-else-if="state.connected && state.read_ok && currentBottle === null && !actionActive" class="disabled-reason">{{ state.bottle_error || '当前瓶位未确认，请先回到1号瓶。' }}</p>
    <p v-if="state.read_ok && actionActive && state.action?.target_bottle != null" role="status" aria-live="polite">正在前往{{ state.action.target_bottle }}号瓶，完成后更新当前瓶位。</p>
    <details class="advanced-controls">
      <summary>高级操作</summary>
      <p>手动脉冲移动和连续运行会使当前瓶位失效，之后需回到1号瓶重新确认。停止中断或通信异常后也需重新确认。</p>
    <div class="motion-settings">
      <div class="control-field"><label>运动速度</label><div class="field-value"><el-input-number v-model="speed" :min="400" :max="40000" :precision="0" :controls="false" /><span>脉冲/秒</span></div></div>
      <div class="control-field"><label>连续运行时长</label><div class="field-value"><el-input-number v-model="duration" :min="1" :max="60" :precision="0" :controls="false" /><span>秒</span></div></div>
    </div>
    <div class="actions"><el-button type="primary" :disabled="!canMove || !validDuration" @click="send({ action: 'run', direction: 'positive', duration_seconds: duration, speed })">正向运行</el-button><el-button :disabled="!canMove || !validDuration" @click="send({ action: 'run', direction: 'negative', duration_seconds: duration, speed })">反向运行</el-button></div>
    <p>连续运行到时由后台发送停止。方向以控制器正向、反向为准。</p>
    <el-divider />
    <p v-if="!state.position_encoding_verified" class="disabled-reason">定位参数尚未验证，定量移动与回程序零暂不可用。</p>
    <div class="motion-settings">
      <div class="control-field"><label>相对移动量（正负脉冲）</label><el-input-number v-model="steps" :min="-9999999" :max="99999999" :precision="0" :controls="false" /><el-button :disabled="!canPosition || !validPosition(steps) || steps === 0" @click="send({ action: 'move_relative', steps, speed })">相对移动</el-button></div>
      <div class="control-field"><label>绝对坐标（脉冲）</label><el-input-number v-model="position" :min="-9999999" :max="99999999" :precision="0" :controls="false" /><el-button :disabled="!canPosition || !validPosition(position)" @click="send({ action: 'move_absolute', position, speed })">绝对定位</el-button></div>
    </div>
    <div class="actions"><el-button :disabled="!canPosition" @click="send({ action: 'move_absolute', position: 0, speed })">回程序零</el-button></div>
    <p>程序零是控制器坐标 0；上电坐标清零不代表机械回零完成。</p>
    <el-divider />
    <div class="actions"><span>机械回零方向</span><el-select v-model="homeDirection" class="direction-select"><el-option label="正向" value="positive" /><el-option label="反向" value="negative" /></el-select><el-button type="warning" :disabled="!canMove || !state.home_enabled" @click="send({ action: 'home', direction: homeDirection, speed })">机械回零</el-button></div>
    <p v-if="!state.home_enabled" class="disabled-reason">原点传感器及回零方向尚未确认，机械回零暂不可用。</p>
    <p v-else>本次连接回零：{{ state.read_ok && state.homed ? '已完成' : '未确认' }}。</p>
    <div class="device-details"><strong>设备详情与输入状态</strong><p>控制器坐标 {{ state.read_ok ? state.position ?? '未知' : '未知' }} 脉冲</p><p>设备 {{ state.device_id }} · 串口 {{ state.connection_port || '待匹配' }}</p><p>正限位 {{ inputLabel('positive_limit') }} · 原点 {{ inputLabel('home') }} · 负限位 {{ inputLabel('negative_limit') }} · 输入4 {{ inputLabel('input4') }}</p><p>速度原始值 {{ state.read_ok ? state.speed_raw ?? '未知' : '未知' }} · 输入原始值 {{ state.read_ok ? state.input_raw ?? '未知' : '未知' }} · 工作状态值 {{ state.read_ok ? state.work_state ?? '未知' : '未知' }}</p><p>最后有效读取 {{ state.read_at || '无' }}</p></div>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import DeviceConnectionControls from './DeviceConnectionControls.vue'
import turntableArtwork from '../assets/theme/turntable.svg'
import { turntableApi, turntableResult, turntableWorkState, type TurntableState, type TurntableCommand, type TurntableDirection } from '../api/turntables'
const props = defineProps<{ state: TurntableState }>()
const emit = defineEmits<{ update: [state: TurntableState] }>()
const pending = ref(0), stopping = ref(0), speed = ref(400), duration = ref(10), steps = ref(100), position = ref(0)
const homeDirection = ref<TurntableDirection>('negative')
const actionActive = computed(() => ['accepted', 'running', 'stop_requested', 'unknown', 'stop_unconfirmed'].includes(props.state.action?.result || ''))
const canControl = computed(() => props.state.connected && props.state.read_ok && props.state.busy === false && !props.state.motion_blocked && !actionActive.value && pending.value === 0)
const canMove = computed(() => canControl.value && Number.isInteger(speed.value) && speed.value >= 400 && speed.value <= 40000)
const bottleConfigured = computed(() => Number.isInteger(props.state.bottle_count) && (props.state.bottle_count ?? 0) > 1 && Number.isInteger(props.state.pulses_per_bottle) && (props.state.pulses_per_bottle ?? 0) > 0)
const currentBottle = computed(() => {
  const value = props.state.current_bottle
  return pending.value === 0 && props.state.connected && props.state.read_ok && props.state.busy === false && props.state.stop_confirmed && !props.state.motion_blocked && !actionActive.value && props.state.bottle_ready && bottleConfigured.value && Number.isInteger(value) && value != null && value >= 1 && value <= props.state.bottle_count! ? value : null
})
const canHomeBottle = computed(() => canControl.value && bottleConfigured.value && props.state.home_enabled && props.state.position_encoding_verified)
const canNextBottle = computed(() => canControl.value && currentBottle.value !== null && props.state.position_encoding_verified && Number.isInteger(props.state.next_bottle) && props.state.next_bottle! >= 1 && props.state.next_bottle! <= props.state.bottle_count! && props.state.position != null && validPosition(props.state.position) && typeof props.state.bottle_token === 'string' && props.state.bottle_token.length > 0)
const canPosition = computed(() => canMove.value && props.state.position_encoding_verified)
const validDuration = computed(() => Number.isFinite(duration.value) && duration.value >= 1 && duration.value <= 60)
function validPosition(value: number) { return Number.isInteger(value) && value >= -9999999 && value <= 99999999 }
function inputLabel(key: keyof NonNullable<TurntableState['inputs']>) { return !props.state.read_ok || props.state.inputs?.[key] == null ? '未知' : props.state.inputs[key] ? '有效' : '无效' }
function error(e: any) { ElMessage.error(typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '请求失败') }
async function nextBottle() {
  if (!canNextBottle.value || props.state.position == null || !props.state.bottle_token) return
  await send({ action: 'next_bottle', expected_position: props.state.position, expected_bottle_token: props.state.bottle_token })
}
async function refresh() {
  try { emit('update', (await turntableApi.read(props.state.device_id)).data) }
  catch (e) { emit('update', { ...props.state, read_ok: false }); error(e) }
}
async function send(body: TurntableCommand) {
  if (!props.state.connected) return
  if (body.action === 'home_bottle') { if (!canHomeBottle.value) return }
  else if (body.action === 'next_bottle') {
    if (!canNextBottle.value || body.expected_position !== props.state.position || body.expected_bottle_token !== props.state.bottle_token) return
  } else if (body.action !== 'stop' && !canMove.value) return
  if (body.action === 'move_relative' && (!canPosition.value || !validPosition(body.steps) || body.steps === 0)) return
  if (body.action === 'move_absolute' && (!canPosition.value || !validPosition(body.position))) return
  if (body.action === 'home' && !props.state.home_enabled) return
  if (body.action === 'run' && (!Number.isFinite(body.duration_seconds) || body.duration_seconds < 1 || body.duration_seconds > 60)) return
  pending.value++
  if (body.action === 'stop') stopping.value++
  try {
    const result = (await turntableApi.command(props.state.device_id, body)).data
    const outcome = result.result?.result || result.state?.action?.result
    if (result.state) emit('update', result.state)
    if (['failed', 'unknown', 'stop_unconfirmed'].includes(outcome)) ElMessage.error(turntableResult[outcome] || '动作未确认')
    else ElMessage.info(turntableResult[outcome] || '请求已处理，请查看状态')
    await refresh()
  } catch (e) { error(e); await refresh() }
  finally { pending.value--; if (body.action === 'stop') stopping.value-- }
}
async function connect() {
  pending.value++
  try {
    const response = (await turntableApi.connect(props.state.device_id)).data
    if (response.success !== true) throw new Error('设备返回连接失败')
    emit('update', response)
    await refresh()
  } catch (e) { error(e); await refresh() } finally { pending.value-- }
}
async function disconnect() {
  pending.value++
  try {
    emit('update', (await turntableApi.disconnect(props.state.device_id)).data)
    await refresh()
  } catch (e) { error(e) } finally { pending.value-- }
}
</script>

<style scoped>
.turntable-panel { margin-bottom:16px; padding:16px 18px; border:1px solid var(--el-border-color-light); border-radius:6px; background:var(--el-bg-color); }
.panel-heading,.identity,.toolbar,.motion-settings,.field-value,.actions { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.panel-heading { justify-content:space-between; margin-bottom:12px; }.identity strong { font-size:16px; }.identity>span { color:var(--el-text-color-secondary); font-size:13px; }.identity img { width:66px; height:52px; object-fit:contain; pointer-events:none; flex-shrink:0; }
.toolbar,.actions { margin:12px 0; }.bottle-actions { margin-top:18px; }.advanced-controls { margin-top:20px; padding-top:14px; border-top:1px solid var(--el-border-color-light); }.advanced-controls>summary { cursor:pointer; color:var(--el-text-color-regular); font-size:14px; font-weight:600; }.toolbar :deep(.el-button + .el-button),.actions :deep(.el-button + .el-button) { margin-left:0; }
.status-line { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:12px; padding:12px; background:#f0f6fd; border-radius:10px; }.status-line span,.status-line strong { display:block; overflow-wrap:anywhere; }.status-line span { color:var(--el-text-color-secondary); font-size:12px; }.status-line strong { margin-top:3px; font-size:16px; font-weight:600; color:#245483; }.status-line small { font-weight:normal; }
.bottle-actions :deep(.el-button) { min-width:102px; }
.motion-settings { align-items:flex-start; gap:16px 24px; margin-top:16px; }.control-field { display:flex; flex-direction:column; gap:8px; }.control-field label { color:var(--el-text-color-regular); font-size:13px; }.field-value { flex-wrap:nowrap; }.control-field :deep(.el-input-number) { width:160px; }.direction-select { width:110px; }
p { color:var(--el-text-color-secondary); font-size:12px; line-height:1.6; }.disabled-reason { color:#91601f; }.action-error { color:var(--el-color-danger); }.device-details { margin:16px 0 0; padding:12px; background:#f5f8fc; border-radius:8px; font-size:13px; }.device-details summary { cursor:pointer; color:#425b73; }
@media(max-width:760px) { .turntable-panel { padding:12px; }.panel-heading { align-items:flex-start; }.status-line { grid-template-columns:repeat(2,minmax(0,1fr)); }.motion-settings { gap:14px; } }
</style>
