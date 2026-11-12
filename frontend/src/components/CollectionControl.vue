<template>
  <section class="collection-panel" aria-label="四圈接样手动控制">
    <header class="collection-overview">
      <div class="position-summary" aria-live="polite">
        <div><span>当前圈</span><strong>{{ ringLabel }}</strong></div>
        <div><span>当前瓶</span><strong>{{ currentBottle != null ? `${currentBottle}号瓶` : '未确认' }}</strong></div>
      </div>
      <el-button type="danger" plain :loading="stopping" :disabled="!axes.some(a => a.connected)" @click="stopAll">停止接样系统</el-button>
    </header>
    <div class="axis-grid">
      <section v-for="axis in axes" :key="axis.device_id" class="axis-card" :aria-label="axis.name">
        <header class="axis-heading">
          <img :src="axis.collection_axis === 'radial' ? platformIcon : turntableIcon" alt="" />
          <div><h2>{{ axis.collection_axis === 'radial' ? '移动平台' : '接样转盘' }}</h2><span>{{ axis.collection_axis === 'radial' ? 'YX-HA02C' : 'CL-01A' }}</span></div>
          <el-tag :type="!axis.read_ok ? 'info' : axis.busy ? 'warning' : 'success'" effect="light">{{ statusLabel(axis) }}</el-tag>
        </header>
        <div class="card-body">
          <div class="connection-row"><span>{{ axis.connection_port || '串口待匹配' }}</span>
            <DeviceConnectionControls :device-key="'turntable:'+axis.device_id" :connected="axis.connected" :loading="pending > 0" :connect-disabled="!axis.configured || axis.binding_resolved === false" :disconnect-disabled="!idle(axis)" @connect="connect(axis)" @disconnect="disconnect(axis)" />
          </div>
          <el-alert v-if="axis.action?.error || axis.read_error || axis.connection_error || axis.binding_error" :title="axis.action?.error || axis.read_error || axis.connection_error || axis.binding_error || ''" type="error" :closable="false" show-icon />
          <div class="axis-toolbar">
            <span class="reference-label">沿用标定坐标</span>
            <el-button :disabled="!axis.connected || pending > 0" @click="refresh(axis)">刷新</el-button>
            <el-button type="danger" plain :disabled="!axis.connected" @click="send(axis, { action: 'stop' })">停止</el-button>
          </div>
          <div class="primary-controls">
            <template v-if="axis.collection_axis === 'rotation'">
              <div class="bottle-row">
                <el-select v-model="bottle" aria-label="当前圈瓶位" :disabled="!canBottle"><el-option v-for="n in bottles" :key="n" :label="`${n}号瓶`" :value="n" /></el-select>
                <el-button type="primary" :disabled="!canBottle || !bottles.includes(bottle)" @click="send(axis, { action: 'select_bottle', bottle, expected_position: axis.position! })">定位</el-button>
              </div>
              <div class="home-row">
                <el-button :disabled="!canStart" @click="send(axis, { action: 'return_start', expected_position: axis.position! })">回归本圈零点</el-button>
                <el-button :disabled="!canHome" @click="send(axis, { action: 'home', direction: 'negative', speed: 1000 })">机械回零</el-button>
              </div>
            </template>
            <template v-else>
              <div class="rings"><el-button v-for="(name, index) in ringNames" :key="name" :class="{ 'current-ring': ring === index }" :aria-pressed="ring === index" :disabled="!canRing" @click="send(axis, { action: 'select_ring', ring: index + 1, expected_position: axis.position! })">{{ name }}<span v-if="ring === index" class="ring-mark" aria-hidden="true">●</span></el-button></div>

            </template>
            <p class="blocked-reason" role="status">{{ blockedReason(axis) || '\u00a0' }}</p>
          </div>
          <details class="advanced"><summary>高级操作</summary>
            <div class="diagnostics"><span>当前坐标 <b>{{ axis.read_ok ? axis.position : '未知' }}</b></span><span v-if="axis.action?.target != null">目标 {{ axis.action.target }}</span><span>速度 {{ axis.read_ok ? axis.speed_raw : '未知' }}</span><span>输入 {{ axis.read_ok ? axis.input_raw : '未知' }}</span></div>
            <p v-if="axis.action">{{ turntableResult[axis.action.result] || axis.action.result }}<span v-if="axis.action.position_error != null"> · 到位偏差 {{ axis.action.position_error }} 计数</span></p>
            <template v-if="axis.collection_axis === 'radial'">
              <p>原始计数 · 范围 {{ platformMinimum }} 至 0 · 固定低速</p>
              <label class="advanced-row"><span>目标坐标</span><el-input-number v-model="absolutePosition" :min="platformMinimum" :max="0" :precision="0" aria-label="平台目标坐标" /><el-button :disabled="!canRing || !validPlatformTarget(false)" @click="movePlatform(axis, false)">定位</el-button></label>
              <label class="advanced-row"><span>相对位移</span><el-input-number v-model="relativeSteps" :min="platformMinimum" :max="-platformMinimum" :precision="0" aria-label="平台相对位移" /><el-button :disabled="!canRing || !validPlatformTarget(true)" @click="movePlatform(axis, true)">移动</el-button></label>
              <p>负向向内；调整后可用圈位按钮返回标定位置。</p>
            </template>
            <template v-else>
              <p>单次微调1–500计数 · 固定低速</p><el-input-number v-model="jog" :min="1" :max="500" :precision="0" aria-label="微调计数" />
              <div class="home-row"><el-button :disabled="!canJog(axis)" @click="send(axis, { action: 'move_relative', steps: -jog, speed: 1000 })">负向微调</el-button><el-button :disabled="!canJog(axis)" @click="send(axis, { action: 'move_relative', steps: jog, speed: 1000 })">正向微调</el-button></div>
            </template>
          </details>
        </div>
      </section>
    </div>
    <details class="commissioning"><summary><span class="commissioning-dot"></span>调试中 <span>操作说明</span></summary><p>四圈定位抽查已通过；平台偶发通信超时、跨圈路径与水测仍待验收。两轴停止后，可从当前角度直接选瓶或换圈。操作前确认停泵、NC废液位并完成滴液等待；每次到位观察瓶口对准。直接沿用固定装置的标定坐标；若控制器坐标被清零或装置关系改变，请先重新定位校正。机械回零仅用于校正，不是日常操作前置条件。</p></details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import turntableIcon from '../assets/theme/turntable.svg'
import platformIcon from '../assets/theme/collection-platform.webp'
import DeviceConnectionControls from './DeviceConnectionControls.vue'
import { turntableApi, turntableResult, type TurntableCommand, type TurntableState } from '../api/turntables'
const props = defineProps<{ states: Record<string, TurntableState> }>()
const emit = defineEmits<{ update: [state: TurntableState] }>()
const axes = computed(() => Object.values(props.states).filter(a => a.collection_axis && a.collection_axis !== 'legacy'))
const rotation = computed(() => axes.value.find(a => a.collection_axis === 'rotation'))
const radial = computed(() => axes.value.find(a => a.collection_axis === 'radial'))
const pending = ref(0), stopping = ref(false), jog = ref(50), bottle = ref(1)
const absolutePosition = ref(0), relativeSteps = ref(-500)
const ringNames = ['最外圈', '第二圈', '第三圈', '最内圈']
function idle(a?: TurntableState) { return !!a && a.connected && a.read_ok && a.busy === false && a.stop_confirmed && !a.motion_blocked && !['accepted', 'running', 'unknown', 'stop_unconfirmed'].includes(a.action?.result || '') }
const bothIdle = computed(() => pending.value === 0 && idle(rotation.value) && idle(radial.value))
const ring = computed(() => idle(radial.value) ? (radial.value?.ring_positions || []).findIndex(position => Math.abs(position - radial.value!.position!) <= (radial.value?.position_tolerance ?? 0)) : -1)
const bottles = computed(() => { if (ring.value < 0) return []; const counts = radial.value?.ring_counts || []; const first = 1 + counts.slice(0, ring.value).reduce((a, b) => a + b, 0); return Array.from({ length: counts[ring.value] || 0 }, (_, i) => first + i) })
watch(bottles, values => { if (!values.includes(bottle.value)) bottle.value = values[0] || 1 })
const canStart = computed(() => bothIdle.value)
const platformMinimum = computed(() => radial.value?.ring_positions?.[3] ?? -444103)
const ringLabel = computed(() => !radial.value?.connected || !radial.value.read_ok ? '未确认' : radial.value.busy ? '移动中' : ring.value >= 0 ? ringNames[ring.value] : idle(radial.value) ? '圈间位置' : '未确认')
const canBottle = computed(() => bothIdle.value && ring.value >= 0)
const canRing = computed(() => bothIdle.value)
const canHome = computed(() => pending.value === 0 && idle(radial.value) && rotation.value?.connected && rotation.value.read_ok && !rotation.value.motion_blocked && (idle(rotation.value) || rotation.value.work_state === 0))
const currentBottle = computed(() => { if (!bothIdle.value || !rotation.value || ring.value < 0) return null; const rev = rotation.value.counts_per_revolution!; const offset = ((rotation.value.position! % rev) + rev) % rev; const i = bottles.value.findIndex((_, i) => Math.round(i * rev / bottles.value.length) === offset); return i < 0 ? null : bottles.value[i] })
function canJog(a: TurntableState) { return bothIdle.value && a.collection_axis === 'rotation' }
function statusLabel(a: TurntableState) {
  return !a.connected ? '未连接' : !a.read_ok ? '状态未知' : a.busy ? '运动中' : a.stop_confirmed ? '已停止' : '确认中'
}
function blockedReason(a: TurntableState) {
  if (!rotation.value?.connected || !radial.value?.connected) return '请先连接两台设备'
  if (!rotation.value.read_ok || !radial.value.read_ok) return '状态未知，请刷新或检查通信'
  if (!bothIdle.value) return '等待两轴停止确认'
  if (a.collection_axis === 'rotation' && ring.value < 0) return '平台在圈间，请先选择目标圈'
  return ''
}
function validPlatformTarget(relative: boolean) {
  const input = relative ? relativeSteps.value : absolutePosition.value
  const position = radial.value?.position
  if (!Number.isSafeInteger(input) || position == null || (relative && input === 0)) return false
  const target = relative ? position + input : input
  return target >= platformMinimum.value && target <= 0
}
async function movePlatform(a: TurntableState, relative: boolean) {
  if (!canRing.value || !validPlatformTarget(relative) || a.position == null) return
  await send(a, relative
    ? { action: 'platform_relative', steps: relativeSteps.value, expected_position: a.position }
    : { action: 'platform_absolute', position: absolutePosition.value, expected_position: a.position })
}
function failure(e: any) { ElMessage.error(typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '请求失败') }
async function refresh(a: TurntableState) { try { emit('update', (await turntableApi.read(a.device_id)).data) } catch (e) { emit('update', { ...a, read_ok: false }); failure(e) } }
async function connect(a: TurntableState) { pending.value++; try { emit('update', (await turntableApi.connect(a.device_id)).data) } catch (e) { failure(e) } finally { pending.value-- } }
async function disconnect(a: TurntableState) { pending.value++; try { emit('update', (await turntableApi.disconnect(a.device_id)).data) } catch (e) { failure(e) } finally { pending.value-- } }
async function send(a: TurntableState, body: TurntableCommand) {
  if (body.action !== 'stop') {
    if (pending.value > 0) return
    if (body.action === 'home' ? !canHome.value
      : body.action === 'select_bottle' ? !canBottle.value
      : body.action === 'return_start' ? !canStart.value
      : ['select_ring', 'platform_absolute', 'platform_relative'].includes(body.action) ? !canRing.value
      : !canJog(a)) return
  }
  pending.value++; try { const result = (await turntableApi.command(a.device_id, body)).data; if (result.state) emit('update', result.state); if (result.result?.result === 'failed') ElMessage.error(result.result.error || '动作失败') } catch (e) { failure(e); await refresh(a) } finally { pending.value-- } }
async function stopAll() { stopping.value = true; try { await Promise.all(axes.value.filter(a => a.connected).map(a => send(a, { action: 'stop' }))) } finally { stopping.value = false } }
</script>

<style scoped>
.collection-panel { container-type: inline-size; color: #294763; }
.collection-overview { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 16px; margin-bottom: 12px; border: 1px solid #dceaf7; border-radius: 14px; background: #f5faffed; }
.position-summary { display: flex; gap: 36px; }
.position-summary > div { display: flex; align-items: baseline; gap: 8px; }
.position-summary span { color: #71859b; font-size: 12px; }
.position-summary strong { font-size: 18px; color: #245c92; }
.axis-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: start; }
.axis-card { min-width: 0; border: 1px solid #d8e7f5; border-radius: 16px; background: #ffffffed; box-shadow: 0 5px 20px #326da10c; overflow: hidden; }
.axis-heading { display: flex; align-items: center; gap: 12px; min-height: 72px; padding: 10px 16px; background: linear-gradient(110deg,#edf7ff,#ffffff); border-bottom: 1px solid #e5eff8; }
.axis-heading img { width: 76px; height: 54px; object-fit: contain; }
.axis-heading h2 { font-size: 18px; margin: 0 0 4px; }
.axis-heading span { font-size: 12px; color: #71859b; }
.axis-heading .el-tag { margin-left: auto; flex-shrink: 0; }
.card-body { padding: 12px 16px; }
.connection-row, .axis-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.connection-row { justify-content: space-between; color: #71859b; font-size: 12px; }
.reference-label { margin-right: auto; font-size: 12px; color: #60788f; }
.axis-toolbar { margin-top: 16px; }
.collection-panel :deep(.el-button + .el-button) { margin-left: 0; }
.primary-controls { min-height: 124px; }
.bottle-row { display: grid; grid-template-columns: minmax(0,1fr) 80px; gap: 10px; }
.home-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.rings { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; margin-bottom: 12px; }
.rings .el-button { height: 40px; margin: 0; }
.rings .current-ring { border-color: #70b0ef; background: #edf6ff; color: #1875ca; }
.ring-mark { font-size: 8px; margin-left: 8px; }
.blocked-reason { color: #7a8da1; font-size: 12px; min-height: 18px; margin: 12px 0 0; }
.advanced { border-top: 1px solid #e5eff8; padding-top: 14px; font-size: 12px; color: #60788f; }
summary { cursor: pointer; user-select: none; }
.advanced[open] summary { margin-bottom: 14px; }
.diagnostics { display: flex; gap: 8px 16px; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.advanced-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.advanced-row > span { width: 50px; }
p { line-height: 1.6; }
.commissioning { font-size: 12px; color: #7a8da1; margin-top: 14px; padding: 0 4px; }
.commissioning summary span:last-child { margin-left: 10px; }
.commissioning-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #dda44a; margin-right: 6px; }
@container (max-width: 760px) { .axis-grid { grid-template-columns: minmax(0,1fr); } }
@media (max-width: 480px) { .collection-overview { padding: 12px; gap: 12px; flex-wrap: wrap; } .position-summary { gap: 24px; } .axis-heading { padding: 14px; gap: 8px; } .axis-heading img { width: 60px; } .card-body { padding: 14px; } }
</style>
