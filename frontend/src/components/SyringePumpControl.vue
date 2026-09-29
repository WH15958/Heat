<template>
  <section class="syringe-panel" :aria-label="`${state.name}控制`">
    <div class="panel-heading">
      <div class="identity">
        <img :src="deviceArtwork" alt="" />
        <strong>{{ state.name }}</strong>
        <span>MSP1-CX · {{ state.capacity_ml }} mL · {{ state.connection_port || '串口待配置' }}</span>
        <el-tag size="small" :type="state.connected ? 'success' : 'info'">{{ state.connected ? '已连接' : state.configured ? '未连接' : '待配置' }}</el-tag>
      </div>
      <div class="toolbar">
        <el-button :disabled="state.connected || !state.configured || pending" @click="connect">连接</el-button>
        <el-button :disabled="!state.connected || !!state.owner || pending" @click="disconnect">断开</el-button>
        <el-button :disabled="!state.connected || pending" @click="refresh">刷新</el-button>
        <el-button type="danger" :disabled="!state.connected" @click="send({ action: 'stop' }, true)">停止</el-button>
      </div>
    </div>

    <el-alert v-if="state.connected && !state.read_ok" :title="state.read_error || '状态未知，控制已禁用'" type="warning" :closable="false" />
    <el-alert v-else-if="state.fault_code" :title="`${state.fault_code}：${state.fault_description}`" type="error" :closable="false" />
    <el-alert v-else-if="state.connected && !state.position_trusted && !state.busy" title="位置未确认。检查安装及液路后，在设备准备中初始化。" type="warning" :closable="false" />

    <div class="status-line" aria-live="polite">
      <div><span>位置</span><strong>{{ state.read_ok ? state.position ?? '运动中' : '未知' }}<small v-if="state.read_ok && state.position != null"> 步</small></strong></div>
      <div><span>理论筒内体积</span><strong>{{ state.read_ok && state.position_trusted && state.theoretical_volume_ul != null ? `${state.theoretical_volume_ul.toFixed(1)} µL` : '未知' }}</strong></div>
      <div><span>设备状态</span><strong>{{ !state.read_ok ? '未知' : state.busy ? '运行中' : state.fault_code ? '故障' : '空闲' }}</strong></div>
      <div><span>当前动作</span><strong>{{ state.read_ok ? syringeResult[state.action?.result || ''] || '无' : '状态未知' }}</strong></div>
    </div>
    <div v-if="state.action?.target != null || state.action?.error" class="action-detail">
      <span v-if="state.action?.target != null">目标 {{ state.action.target }} 步</span>
      <span v-if="state.action?.error">{{ state.action.error }}</span>
    </div>

    <el-tabs v-model="activeTab" class="pump-tabs">
      <el-tab-pane label="吸排液" name="operate">
        <div class="routine-controls">
          <div class="control-field">
            <label>吸排量</label>
            <div class="field-value"><el-input-number v-model="volume" :min="0.001" :controls="false" /><el-select v-model="unit" class="unit-select"><el-option label="µL" value="uL" /><el-option label="mL" value="mL" /><el-option label="步" value="steps" /></el-select></div>
          </div>
          <div class="control-field">
            <label>电机速度</label>
            <div class="field-value"><el-input-number v-model="speed" :min="5" :max="5000" :precision="0" :controls="false" /><span>Hz</span></div>
          </div>
          <div class="control-field compact-field">
            <label>动作超时</label>
            <div class="field-value"><el-input-number v-model="timeout" :min="1" :max="3600" :precision="0" :controls="false" /><span>秒</span></div>
          </div>
        </div>
        <div class="estimate-line">
          <span v-if="state.orientation">{{ state.orientation === 'Z' ? '左吸右排' : '右吸左排' }}</span>
          <span v-if="state.read_ok && state.position_trusted && state.position != null">约 {{ roundedSteps }} 步 · 吸取目标 {{ state.position + roundedSteps }} · 排出目标 {{ state.position - roundedSteps }}</span>
          <span v-else>当前位置未确认，暂不计算目标</span>
          <span v-if="theoreticalRate != null">约 {{ theoreticalRate.toFixed(1) }} µL/s（理论活塞速度）</span>
        </div>
        <div class="primary-actions">
          <el-button type="primary" :disabled="!canControl || !canAspirate" @click="send({ action: 'aspirate', volume, unit, speed, timeout })">吸取</el-button>
          <el-button :disabled="!canControl || !canDispense" @click="send({ action: 'dispense', volume, unit, speed, timeout })">排出</el-button>
        </div>

        <el-collapse v-model="basicSections" class="setup-collapse">
          <el-collapse-item name="setup">
            <template #title>设备准备 <el-tag v-if="state.connected && !state.position_trusted" size="small" type="warning" class="setup-tag">待确认位置</el-tag></template>
            <div class="setup-controls">
              <div class="control-field">
                <label>初始化方向</label>
                <el-select v-model="direction"><el-option label="Z：左吸右排" value="Z" /><el-option label="Y：右吸左排" value="Y" /></el-select>
              </div>
              <div class="control-field">
                <label>初始化代码</label>
                <el-select v-model="initCode"><el-option v-for="code in [0, 1, 2, ...Array.from({ length: 31 }, (_, i) => i + 10)]" :key="code" :label="String(code)" :value="code" /></el-select>
              </div>
              <el-button type="warning" :disabled="!canInitialize" @click="initialize">初始化（会运动）</el-button>
            </div>
            <p>{{ state.capacity_ml }} mL 注射器预选代码 {{ defaultInitCode }}。初始化会移动活塞并切阀；过载原因须先查明。</p>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>

      <el-tab-pane label="高级操作" name="advanced">
        <el-collapse v-model="advancedSections" class="advanced-collapse">
          <el-collapse-item title="定位、阀位与硬件暂停" name="motion">
            <div class="advanced-row">
              <label>绝对位置</label><el-input-number v-model="position" :min="0" :max="fullSteps" :precision="0" />
              <el-button :disabled="!canControl || !motionInputsValid" @click="send({ action: 'move', position, speed, timeout })">移动</el-button>
            </div>
            <div class="advanced-row">
              <span>三口 Y 型阀</span>
              <el-button v-for="port in valveOptions" :key="port.value" :disabled="!canControl || !validTimeout" @click="send({ action: 'valve', valve: port.value, timeout })">{{ port.label }}</el-button>
            </div>
            <div class="advanced-row">
              <el-button :disabled="!state.busy || !!state.owner || pending" @click="send({ action: 'pause' })">硬件暂停</el-button>
              <el-button :disabled="!(state.action?.result === 'paused' || (state.action?.waits_input && ['accepted', 'running'].includes(state.action?.result || ''))) || !!state.owner || pending" @click="send({ action: 'resume' })">继续 / 释放输入等待</el-button>
            </div>
          </el-collapse-item>
          <el-collapse-item title="运动参数" name="settings">
            <div class="advanced-row">
              <el-select v-model="setting" class="setting-select"><el-option v-for="s in settingOptions" :key="s.key" :label="s.label" :value="s.key" /></el-select>
              <el-input-number v-model="settingValue" :precision="0" />
              <el-button :disabled="!canControl" @click="send({ action: 'configure', settings: { [setting]: settingValue } })">应用参数</el-button>
            </div>
            <p>步进模式仅能在零位切换；0 / 1 / 2 分别为 3000 / 48000 / 24000 步。</p>
          </el-collapse-item>
          <el-collapse-item title="程序与数字 I/O" name="program">
            <el-input v-model="program" type="textarea" :rows="4" maxlength="120" placeholder="例如 IP120OD120" />
            <div class="advanced-row">
              <el-input v-model="programName" placeholder="程序名称" maxlength="80" class="program-name" />
              <span>EEPROM槽位</span><el-input-number v-model="slot" :min="0" :max="14" :precision="0" />
            </div>
            <div class="advanced-row">
              <el-button :disabled="!canControl" @click="send({ action: 'program_validate', program })">校验</el-button>
              <el-button :disabled="!canControl" @click="send({ action: 'program_load', program, name: programName, timeout })">装载缓冲</el-button>
              <el-button :disabled="!canControl" @click="send({ action: 'program_run', timeout })">执行缓冲</el-button>
              <el-button :disabled="!canControl" @click="storeProgram">存储 EEPROM</el-button>
              <el-button :disabled="!canControl" @click="send({ action: 'program_run', slot, timeout })">执行槽位</el-button>
              <el-button :disabled="!canControl" @click="send({ action: 'repeat', timeout })">重复上次程序</el-button>
              <el-button @click="loadPrograms">查看登记程序</el-button>
            </div>
            <div class="advanced-row">
              <span>输出位掩码</span><el-input-number v-model="output" :min="0" :max="7" :precision="0" />
              <el-button :disabled="!canControl" @click="send({ action: 'io', output })">设置输出</el-button>
            </div>
            <p>程序不含末尾 R；存储不会执行。EEPROM内容不能可靠读回，重连后须重新登记。</p>
          </el-collapse-item>
          <el-collapse-item title="诊断" name="diagnostics">
            <div class="advanced-row"><el-button :disabled="!state.connected || pending" @click="diagnose">读取诊断</el-button><span>{{ state.read_at || '尚未有效读取' }}</span></div>
            <pre>{{ details }}</pre>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>
    </el-tabs>
    <p v-if="state.owner" class="owner-note">实验占用中。暂停实验不会打断当前已下发的动作；需要立即中断请使用停止。</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { syringeApi, syringeResult, type SyringeState } from '../api/syringePumps'
import deviceArtwork from '../assets/theme/syringe-pump.webp'
const props = defineProps<{ state: SyringeState }>()
const emit = defineEmits<{ update: [state: SyringeState] }>()
const pending = ref(false)
const activeTab = ref('operate')
const basicSections = ref<string[]>([]), advancedSections = ref<string[]>([])
const defaultInitCode = props.state.capacity_ml >= 2.5 ? 0 : props.state.capacity_ml >= 0.5 ? 1 : 2
const direction = ref('Z'), initCode = ref(defaultInitCode), speed = ref(100), volume = ref(100), unit = ref('uL')
const position = ref(0), timeout = ref(120), program = ref(''), programName = ref(''), slot = ref(0), output = ref(0)
const details = ref(''), setting = ref('speed'), settingValue = ref(100)
const fullSteps = computed(() => ({ 0: 3000, 1: 48000, 2: 24000 }[props.state.microstep ?? 0] ?? 3000))
const roundedSteps = computed(() => Math.round(unit.value === 'steps' ? volume.value : volume.value * (unit.value === 'mL' ? 1000 : 1) / (props.state.capacity_ml * 1000) * fullSteps.value))
const theoreticalRate = computed(() => props.state.read_ok && props.state.position_trusted && props.state.microstep != null && Number.isFinite(speed.value) ? speed.value / fullSteps.value * props.state.capacity_ml * 1000 : null)
const canInitialize = computed(() => props.state.connected && props.state.read_ok && props.state.busy === false && !['accepted', 'running', 'paused'].includes(props.state.action?.result || '') && !props.state.owner && !pending.value)
const canControl = computed(() => canInitialize.value && props.state.position_trusted && props.state.fault_code === 0 && !['failed', 'unknown', 'stopped'].includes(props.state.action?.result || ''))
const validTimeout = computed(() => Number.isFinite(timeout.value) && timeout.value > 0 && timeout.value <= 3600)
const motionInputsValid = computed(() => validTimeout.value && Number.isFinite(speed.value) && speed.value >= 5 && speed.value <= 5000)
const canAspirate = computed(() => motionInputsValid.value && roundedSteps.value > 0 && props.state.position != null && props.state.position + roundedSteps.value <= fullSteps.value)
const canDispense = computed(() => motionInputsValid.value && roundedSteps.value > 0 && props.state.position != null && props.state.position - roundedSteps.value >= 0)
watch([() => props.state.connected, () => props.state.position_trusted], ([connected, trusted]) => {
  if (connected && !trusted && props.state.busy === false) basicSections.value = ['setup']
  else if (trusted) basicSections.value = []
}, { immediate: true })
const valveOptions = [{ value: 'input', label: '进液口' }, { value: 'output', label: '排液口' }, { value: 'bypass', label: '旁路' }]
const settingOptions = [{ key: 'start_speed', label: '启动速度 50..1000' }, { key: 'speed', label: '运行速度 5..5000' }, { key: 'stop_speed', label: '停止速度 50..2700' }, { key: 'acceleration', label: '加速度代码 1..20' }, { key: 'speed_code', label: '速度代码 0..40' }, { key: 'microstep', label: '步进模式 0/1/2' }, { key: 'backlash', label: '回退间隙 0..31' }, { key: 'dead_volume', label: '死区步数 0..80' }]
watch(setting, key => {
  settingValue.value = { start_speed: 100, speed: 100, stop_speed: 50, acceleration: 14, speed_code: 11, microstep: 0, backlash: 0, dead_volume: 20 }[key] ?? 0
})
function error(e: any) { ElMessage.error(typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '请求失败') }
async function refresh() { try { emit('update', (await syringeApi.read(props.state.device_id)).data) } catch (e) { emit('update', { ...props.state, read_ok: false }); error(e) } }
async function send(body: Record<string, unknown>, stop = false) {
  if (pending.value && !stop) return
  pending.value = true
  try {
    const result = (await syringeApi.command(props.state.device_id, body)).data
    details.value = JSON.stringify(result, null, 2)
    if (result.result === 'stop_unconfirmed') ElMessage.error('停止未确认，请现场检查')
    else ElMessage.info(syringeResult[result.result] || '请求已处理，请查看反馈')
    await refresh()
  } catch (e) { error(e) } finally { pending.value = false }
}
async function connect() { pending.value = true; try { await syringeApi.connect(props.state.device_id); await refresh() } catch (e) { error(e) } finally { pending.value = false } }
async function disconnect() { pending.value = true; try { await syringeApi.disconnect(props.state.device_id); await refresh() } catch (e) { error(e) } finally { pending.value = false } }
async function initialize() {
  try { await ElMessageBox.confirm('初始化会将活塞移向上端并切阀。请确认安装、液路和现场看护，过载原因已排除。', '初始化确认', { type: 'warning' }) }
  catch { return }
  await send({ action: 'initialize', direction: direction.value, initialization_code: initCode.value, confirm: true, timeout: timeout.value })
}
async function storeProgram() {
  try { await ElMessageBox.confirm(`写入EEPROM槽位 ${slot.value} 会覆盖该槽位；确认上电自动运行已按现场要求禁用。`, '存储确认', { type: 'warning' }) }
  catch { return }
  await send({ action: 'program_store', program: program.value, name: programName.value, slot: slot.value, confirm: true, timeout: timeout.value })
}
async function diagnose() { try { details.value = JSON.stringify((await syringeApi.diagnostics(props.state.device_id)).data, null, 2) } catch (e) { error(e) } }
async function loadPrograms() { try { details.value = JSON.stringify((await syringeApi.programs(props.state.device_id)).data, null, 2); ElMessage.info('登记程序已显示在诊断区') } catch (e) { error(e) } }
</script>

<style scoped>
.syringe-panel { margin-bottom: 16px; padding: 16px 18px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.panel-heading, .identity, .toolbar, .routine-controls, .field-value, .primary-actions, .setup-controls, .advanced-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.panel-heading { justify-content: space-between; margin-bottom: 12px; }
.identity img { width: 66px; height: 52px; object-fit: contain; pointer-events: none; flex-shrink: 0; }
.identity strong { font-size: 16px; }
.identity span { color: var(--el-text-color-secondary); font-size: 13px; }
.toolbar { gap: 6px; }
.toolbar :deep(.el-button + .el-button), .advanced-row :deep(.el-button + .el-button) { margin-left: 0; }
.status-line { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding: 11px 0; border-block: 1px solid var(--el-border-color-lighter); }
.status-line > div { min-width: 0; }
.status-line span, .status-line strong { display: block; overflow-wrap: anywhere; }
.status-line span { color: var(--el-text-color-secondary); font-size: 12px; }
.status-line strong { margin-top: 3px; font-size: 14px; font-weight: 600; }
.status-line small { font-weight: normal; }
.action-detail, .estimate-line { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--el-text-color-secondary); font-size: 12px; }
.action-detail { margin-top: 8px; }
.pump-tabs { margin-top: 10px; }
.routine-controls { align-items: flex-end; gap: 12px 20px; }
.control-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.control-field label { color: var(--el-text-color-regular); font-size: 13px; }
.field-value { flex-wrap: nowrap; white-space: nowrap; }
.field-value :deep(.el-input-number) { width: 140px; }
.unit-select { width: 80px; }
.compact-field .field-value :deep(.el-input-number) { width: 85px; }
.estimate-line { margin: 12px 0; }
.primary-actions { gap: 10px; margin-bottom: 12px; }
.primary-actions :deep(.el-button) { min-width: 102px; }
.primary-actions :deep(.el-button + .el-button) { margin-left: 0; }
.setup-tag { margin-left: 8px; }
.setup-controls, .advanced-row { margin: 10px 0; }
.setup-controls .control-field :deep(.el-select) { width: 180px; }
.advanced-row :deep(.el-input-number) { width: 145px; }
.setting-select { width: 240px; max-width: 100%; }
.program-name { width: 190px; max-width: 100%; }
p { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; }
.owner-note { margin-bottom: 0; }
pre { max-height: 320px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .syringe-panel { padding: 12px; }
  .panel-heading { align-items: flex-start; }
  .status-line { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .routine-controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .routine-controls .control-field:first-child { grid-column: 1 / -1; }
  .field-value :deep(.el-input-number) { width: min(140px, 100%); }
}
</style>
