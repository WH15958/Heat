<template>
  <div class="experiment-page">
    <div v-if="syringeData?.valves" style="margin-bottom: 12px">
      <el-tag v-for="(valve, id) in syringeData.valves" :key="id" style="margin-right: 8px">
        {{ id }}：{{ !syringeConnected || !valve.read_ok ? '状态未知' : valve.relay_energized ? '公共口 → NC（通电）' : '公共口 → NO（断电）' }}
        {{ valve.experiment_owned ? ' · 实验占用' : '' }}
      </el-tag>
    </div>
    <el-alert title="三通阀在暂停、停止、结束或失败时保持当前阀位；仅由明确的阀门步骤切换。显示位置来自继电器读回，实际流路仍需实物确认。" type="info" :closable="false" style="margin-bottom: 12px" />
    <div v-if="syringeData?.syringe_pumps" style="margin-bottom: 12px">
      <el-tag v-for="(pump, id) in syringeData.syringe_pumps" :key="id" style="margin-right: 8px">
        {{ pump.name }}：{{ !syringeConnected || !pump.read_ok ? '状态未知' : syringeResult[pump.action?.result || ''] || (pump.busy ? '运行中' : '空闲') }}
        · 目标 {{ pump.action?.target ?? '—' }} 步
      </el-tag>
    </div>
    <el-alert title="注射泵实验暂停：当前已下发动作/有限程序继续完成，不再下发后续动作；立即停止请使用停止或全局急停。" type="info" :closable="false" style="margin-bottom: 12px" />
    <el-row :gutter="20">
      <el-col :xs="24" :md="8">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>可用实验</span>
              <el-button size="small" type="primary" @click="router.push('/experiment/editor')">新建实验</el-button>
              <el-button size="small" :loading="experimentsLoading" @click="loadExperiments">
                刷新
              </el-button>
            </div>
          </template>
          <div v-if="experiments.length === 0" style="color: #909399; text-align: center; padding: 20px">
            暂无实验，点击“新建实验”编排，或在 experiments/ 目录下添加 YAML 文件
          </div>
          <button
            v-for="(exp, index) in experiments"
            :key="exp.filename"
            type="button"
            class="exp-item"
            :class="{ active: selectedFilename === exp.filename }"
            @click="previewExperiment(exp.filename)"
          >
            <span class="exp-number">{{ index + 1 }}</span>
            <span class="exp-name">{{ exp.name }}</span>
          </button>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="16">
        <el-card shadow="hover" v-if="selectedExp">
          <template #header>
            <div class="card-header">
              <span>{{ selectedExp.name }}</span>
              <div class="card-header-actions">
                <el-button @click="router.push({ path: '/experiment/editor', query: { filename: selectedFilename } })">编辑此实验</el-button>
                <el-switch
                  v-model="saveLog"
                  active-text="保存日志"
                  inactive-text=""
                  style="margin-right: 12px"
                />
                <el-button type="success" @click="startExperiment" :disabled="isRunning" :loading="starting">
                  启动实验
                </el-button>
                <el-button type="warning" @click="pauseExperiment" :disabled="!isRunning" :loading="pausing">
                  暂停
                </el-button>
                <el-button type="primary" @click="resumeExperiment" :disabled="!isPaused" :loading="resuming">
                  恢复
                </el-button>
                <el-button type="danger" @click="stopExperiment" :disabled="!isRunning && !isPaused" :loading="stopping">
                  停止
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="progress" class="progress-section">
            <div class="progress-header">
              <el-tag :type="stateTagType" size="large">{{ stateLabel }}</el-tag>
              <span class="progress-text">
                步骤 {{ progressStepText }}
                <span v-if="progress.step_id"> · {{ progress.step_id }}</span>
              </span>
              <span class="elapsed">{{ formatElapsed(progress.elapsed) }}</span>
            </div>
            <el-progress
              :percentage="progressPercentage"
              :status="progressStatus"
              :stroke-width="20"
              style="margin: 10px 0"
            />
          </div>

          <div class="steps-list">
            <div
              v-for="(step, idx) in selectedExp.steps"
              :key="step.id"
              class="step-item"
              :class="{
                active: progress && ['running', 'paused'].includes(progress.state) && step.id === progress.step_id,
                completed: stepStatusMap[step.id] === 'completed',
                failed: stepStatusMap[step.id] === 'failed',
                skipped: stepStatusMap[step.id] === 'skipped',
              }"
            >
              <span class="step-index">{{ idx + 1 }}</span>
              <span class="step-id">{{ step.id }}</span>
              <el-tag size="small" type="info">{{ step.type }}</el-tag>
              <el-tag v-if="step.wait_type !== 'none'" size="small" type="warning">
                等待: {{ step.wait_type }}
              </el-tag>
              <el-tag v-if="stepStatusMap[step.id]" :type="stepTagType(stepStatusMap[step.id])" size="small">
                {{ stepStatusLabel(stepStatusMap[step.id]) }}
              </el-tag>
            </div>
          </div>
        </el-card>

        <el-card v-else shadow="hover">
          <div style="text-align: center; padding: 40px; color: #909399">
            请从左侧选择一个实验
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="previewVisible" title="实验详情" class="experiment-preview" width="min(960px, 92vw)" top="5vh">
      <div v-loading="previewLoading" class="preview-content">
        <el-alert v-if="previewError" :title="previewError" type="error" :closable="false" />
        <template v-if="previewExp">
          <h2 class="preview-title">{{ previewExp.name }}</h2>
          <p class="preview-filename">{{ previewFilename }} · {{ previewExp.steps.length }} 个步骤</p>
          <p class="preview-description">{{ previewExp.description || '无描述' }}</p>
          <el-descriptions v-if="Object.keys(previewExp.metadata || {}).length" :column="1" border size="small">
            <el-descriptions-item v-for="(value, key) in previewExp.metadata" :key="key" :label="String(key)">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</el-descriptions-item>
          </el-descriptions>
          <h3 class="preview-steps-title">实验步骤</h3>
          <div class="preview-step-list">
            <div v-for="(step, index) in previewExp.steps" :key="index" class="preview-step">
              <div class="preview-step-heading"><span class="preview-step-number">{{ index + 1 }}</span><strong>{{ step.id }}</strong><el-tag v-if="step.enabled === false" type="info" size="small">已禁用</el-tag></div>
              <div class="preview-step-details"><span>{{ step.type }}</span><span v-if="step.wait_type && step.wait_type !== 'none'">等待：{{ step.wait_type }}</span></div>
              <pre v-if="Object.keys(step.params || {}).length" class="preview-params">{{ JSON.stringify(step.params, null, 2) }}</pre>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button :disabled="previewLoading" @click="router.push({ path: '/experiment/editor', query: { filename: previewFilename } })">编辑此实验</el-button>
        <el-button @click="previewVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!previewExp || previewLoading || isRunning || isPaused || starting" @click="choosePreviewExperiment">选择此实验</el-button>
      </template>
    </el-dialog>

    <el-card shadow="hover" style="margin-top: 20px" v-if="selectedFilename">
      <template #header>
        <div class="card-header">
          <span>实验日志</span>
          <div>
            <el-tag v-if="currentRunId" type="info" size="small">Run: {{ currentRunId }}</el-tag>
            <el-tag v-if="currentSampleId" type="success" size="small">Sample: {{ currentSampleId }}</el-tag>
            <el-tag
              v-for="item in metadataSummary"
              :key="item.key"
              type="warning"
              size="small"
            >
              {{ item.label }}: {{ item.value }}
            </el-tag>
            <el-button size="small" @click="clearLogs">清空</el-button>
            <el-button size="small" type="primary" @click="exportLogs" :disabled="logEntries.length === 0">
              导出日志
            </el-button>
          </div>
        </div>
      </template>
      <div class="log-container" ref="logContainer">
        <div v-if="logEntries.length === 0" class="log-empty">暂无日志，启动实验后自动记录</div>
        <div
          v-for="(entry, idx) in logEntries"
          :key="idx"
          class="log-entry"
          :class="'log-' + entry.level"
        >
          <span class="log-time">{{ entry.time }}</span>
          <el-tag :type="logTagType(entry.level)" size="small" class="log-tag">{{ entry.label }}</el-tag>
          <span class="log-msg">{{ entry.message }}</span>
          <span v-if="entry.detail" class="log-detail">{{ entry.detail }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebSocket } from '../composables/useWebSocket'
import { syringeResult } from '../api/syringePumps'
const { data: syringeData, connected: syringeConnected } = useWebSocket()
const route = useRoute(), router = useRouter()

interface ExperimentSummary {
  filename: string
  name: string
  description: string
  steps_count: number
}

interface ExperimentDetail {
  name: string
  description: string
  metadata?: Record<string, any>
  steps: { id: string; type: string; params: any; wait_type: string; enabled: boolean }[]
}

interface ExperimentProgress {
  state: string
  current_step: number
  total_steps: number
  step_id: string
  elapsed: number
}

interface LogEntry {
  time: string
  level: string
  label: string
  message: string
  detail?: string
}

const experiments = ref<ExperimentSummary[]>([])
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewFilename = ref('')
const previewExp = ref<ExperimentDetail | null>(null)
let previewRequest = 0
const selectedExp = ref<ExperimentDetail | null>(null)
const selectedFilename = ref('')
const experimentsLoading = ref(false)
const progress = ref<ExperimentProgress | null>(null)
const starting = ref(false)
const pausing = ref(false)
const resuming = ref(false)
const stopping = ref(false)
const saveLog = ref(true)
const currentRunId = ref('')
const currentSampleId = ref('')
const currentMetadata = ref<Record<string, any>>({})
const logEntries = ref<LogEntry[]>([])
const stepStatusMap = ref<Record<string, string>>({})
const logContainer = ref<HTMLElement | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
let ws: WebSocket | null = null
let wsClosed = false

const isRunning = computed(() => progress.value?.state === 'running')
const isPaused = computed(() => progress.value?.state === 'paused')
const terminalStates = new Set(['completed', 'failed', 'stopped'])

const metadataSummary = computed(() => {
  const labels: Record<string, string> = {
    batch_id: 'Batch',
    condition_id: 'Condition',
    material_system: 'Material',
    operator: 'Operator',
  }
  return Object.keys(labels)
    .map(key => ({ key, label: labels[key], value: currentMetadata.value?.[key] }))
    .filter(item => item.value !== undefined && item.value !== null && item.value !== '')
})

const stateLabel = computed(() => {
  const map: Record<string, string> = {
    idle: '空闲', running: '运行中', paused: '已暂停',
    completed: '已完成', failed: '失败', stopped: '已停止',
  }
  return map[progress.value?.state || 'idle'] || '空闲'
})

const stateTagType = computed(() => {
  const map: Record<string, string> = {
    idle: 'info', running: 'success', paused: 'warning',
    completed: 'success', failed: 'danger', stopped: 'info',
  }
  return map[progress.value?.state || 'idle'] as any || 'info'
})

const progressPercentage = computed(() => {
  if (!progress.value || progress.value.total_steps <= 0) return 0
  const current = Math.max(0, Math.min(progress.value.current_step, progress.value.total_steps))
  return Math.round((current / progress.value.total_steps) * 100)
})

const progressStepText = computed(() => {
  if (!progress.value || progress.value.total_steps <= 0) return '0 / 0'
  if (progress.value.state === 'idle') return `0 / ${progress.value.total_steps}`
  const shownStep = Math.min(progress.value.current_step + 1, progress.value.total_steps)
  return `${shownStep} / ${progress.value.total_steps}`
})

const progressStatus = computed(() => {
  if (!progress.value) return ''
  if (progress.value.state === 'completed') return 'success'
  if (progress.value.state === 'failed') return 'exception'
  return ''
})

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}分${s}秒`
}

function now(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function stepTagType(status: string): string {
  const map: Record<string, string> = { completed: 'success', failed: 'danger', skipped: 'warning', running: 'primary' }
  return map[status] || 'info'
}

function stepStatusLabel(status: string): string {
  const map: Record<string, string> = { completed: '完成', failed: '失败', skipped: '跳过', running: '执行中' }
  return map[status] || status
}

function logTagType(level: string): string {
  const map: Record<string, string> = { info: 'info', success: 'success', warning: 'warning', error: 'danger' }
  return map[level] || 'info'
}

function addLog(level: string, label: string, message: string, detail?: string) {
  logEntries.value.push({ time: now(), level, label, message, detail })
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

function normalizeProgress(data: any, fallback: ExperimentProgress | null = progress.value): ExperimentProgress {
  const state = String(data?.state ?? fallback?.state ?? 'idle')
  const totalRaw = Number(data?.total_steps ?? fallback?.total_steps ?? selectedExp.value?.steps.filter(step => step.enabled).length ?? 0)
  const totalSteps = Number.isFinite(totalRaw) ? Math.max(0, totalRaw) : 0
  const currentRaw = Number(data?.current_step ?? fallback?.current_step ?? 0)
  let currentStep = Number.isFinite(currentRaw) ? Math.max(0, currentRaw) : 0
  if (state === 'completed') {
    currentStep = totalSteps
  }
  currentStep = Math.min(currentStep, totalSteps)
  const elapsedRaw = Number(data?.elapsed ?? fallback?.elapsed ?? 0)

  return {
    state,
    current_step: currentStep,
    total_steps: totalSteps,
    step_id: data?.step_id ?? fallback?.step_id ?? '',
    elapsed: Number.isFinite(elapsedRaw) ? elapsedRaw : 0,
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function clearLogs() {
  logEntries.value = []
  stepStatusMap.value = {}
}

function exportLogs() {
  const lines = logEntries.value.map(e => {
    const base = `[${e.time}] [${e.label}] ${e.message}`
    return e.detail ? `${base} | ${e.detail}` : base
  })
  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `experiment_log_${currentRunId.value || 'unknown'}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

function handleWsMessage(event: MessageEvent) {
  try {
    const msg = JSON.parse(event.data)
    if (msg.type === 'experiment_progress' && msg.filename === selectedFilename.value) {
      progress.value = normalizeProgress(msg)
      if (terminalStates.has(progress.value.state)) stopPolling()
    } else if (msg.type === 'experiment_log' && msg.filename === selectedFilename.value) {
      const evt = msg.event
      const data = msg.data

      if (evt === 'run_started') {
        currentRunId.value = data.run_id
        currentMetadata.value = data.metadata || currentMetadata.value
        currentSampleId.value = data.metadata?.sample_id || currentSampleId.value
        stepStatusMap.value = {}
        addLog('success', '实验启动', `${data.experiment_name} (${data.run_id})`, `共 ${data.total_steps} 个步骤`)
      } else if (evt === 'step_started') {
        stepStatusMap.value[data.step_id] = 'running'
        addLog('info', '步骤开始', `[${data.step_index + 1}] ${data.step_id}`, `动作: ${data.action_type}`)
      } else if (evt === 'step_finished') {
        stepStatusMap.value[data.step_id] = data.status
        const level = data.status === 'completed' ? 'success' : 'error'
        const label = data.status === 'completed' ? '步骤完成' : '步骤失败'
        const dur = data.duration ? ` 耗时 ${data.duration.toFixed(1)}s` : ''
        addLog(level, label, `[${data.step_index + 1}] ${data.step_id}${dur}`, data.error || undefined)
      } else if (evt === 'step_skipped') {
        stepStatusMap.value[data.step_id] = 'skipped'
        addLog('warning', '步骤跳过', `[${data.step_index + 1}] ${data.step_id}`, data.error || '')
      } else if (evt === 'run_paused') {
        addLog('warning', '实验暂停', `Run: ${data.run_id}`)
      } else if (evt === 'run_resumed') {
        addLog('info', '实验恢复', `Run: ${data.run_id}`)
      } else if (evt === 'run_finished') {
        const persistenceFailed = data.persistence_status === 'error'
        const level = persistenceFailed ? 'error' : data.status === 'completed' ? 'success' : data.status === 'failed' ? 'error' : 'warning'
        const label = persistenceFailed
          ? '实验执行结束，但追踪记录失败'
          : data.status === 'completed' ? '实验完成' : data.status === 'failed' ? '实验失败' : '实验停止'
        const dur = data.total_duration ? ` 总耗时 ${data.total_duration.toFixed(1)}s` : ''
        addLog(level, label, `${data.experiment_name}${dur}`,
          persistenceFailed
            ? `持久化错误: ${(data.persistence_errors || []).join('; ') || 'unknown'}`
            : `完成: ${data.completed_steps} 失败: ${data.failed_steps}`)
        const totalSteps = progress.value?.total_steps ?? selectedExp.value?.steps.filter(step => step.enabled).length ?? 0
        progress.value = normalizeProgress({
          state: data.status,
          current_step: data.status === 'completed' ? totalSteps : progress.value?.current_step,
          total_steps: totalSteps,
          elapsed: data.total_duration ?? progress.value?.elapsed,
          step_id: '',
        })
        stopPolling()
      }
    }
  } catch {
    // ignore non-JSON messages
  }
}

function connectWs() {
  if (wsClosed) return
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${protocol}//${location.host}/ws`
  try {
    ws = new WebSocket(url)
    ws.onmessage = handleWsMessage
    ws.onerror = () => {
      console.error('WebSocket error: connection failed')
      ElMessage.warning({ message: '实验日志实时推送连接失败，正在重连...', duration: 3000 })
    }
    ws.onclose = () => {
      if (!wsClosed) {
        setTimeout(connectWs, 5000)
      }
    }
  } catch (error) {
    console.error('Failed to connect WebSocket:', error)
    if (!wsClosed) {
      setTimeout(connectWs, 5000)
    }
  }
}

async function loadExperiments() {
  experimentsLoading.value = true
  try {
    const res = await axios.get('/api/experiments/')
    experiments.value = res.data
  } catch (e: any) {
    console.error('Failed to load experiments:', e)
    ElMessage.error(`实验列表刷新失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    experimentsLoading.value = false
  }
}

async function previewExperiment(filename: string) {
  const request = ++previewRequest
  previewFilename.value = filename
  previewExp.value = null
  previewError.value = ''
  previewLoading.value = true
  previewVisible.value = true
  try {
    const res = await axios.get(`/api/experiments/${filename}`)
    if (request === previewRequest) previewExp.value = res.data
  } catch (e: any) {
    if (request === previewRequest) previewError.value = `加载失败: ${e.response?.data?.detail || e.message}`
  } finally {
    if (request === previewRequest) previewLoading.value = false
  }
}

async function choosePreviewExperiment() {
  if (!previewExp.value || previewLoading.value || isRunning.value || isPaused.value || starting.value) return
  await selectExperiment(previewFilename.value)
  previewVisible.value = false
}

async function selectExperiment(filename: string) {
  selectedFilename.value = filename
  progress.value = null
  currentRunId.value = ''
  currentSampleId.value = ''
  currentMetadata.value = {}
  try {
    const res = await axios.get(`/api/experiments/${filename}`)
    selectedExp.value = res.data
  } catch (e: any) {
    ElMessage.error(`加载失败: ${e.response?.data?.detail || e.message}`)
  }
  await pollProgress()
}

async function startExperiment() {
  try {
    await ElMessageBox.confirm(
      `确定要启动实验 "${selectedExp.value?.name}" 吗？`,
      '确认启动',
      { confirmButtonText: '启动', cancelButtonText: '取消', type: 'info' },
    )
  } catch { return }

  starting.value = true
  try {
    const res = await axios.post(`/api/experiments/${selectedFilename.value}/start`, {
      save_log: saveLog.value,
    })
    currentRunId.value = res.data.run_id || ''
    currentSampleId.value = res.data.sample_id || ''
    currentMetadata.value = res.data.metadata || {}
    ElMessage.success(currentSampleId.value ? `实验已启动，Sample: ${currentSampleId.value}` : '实验已启动')
    await pollProgress()
    startPolling()
  } catch (e: any) {
    const detail = e.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : JSON.stringify(detail || e.message)
    ElMessage.error(`启动失败: ${msg}`)
  } finally {
    starting.value = false
  }
}

async function pauseExperiment() {
  pausing.value = true
  try {
    await axios.post(`/api/experiments/${selectedFilename.value}/pause`)
    ElMessage.warning('实验已暂停')
  } catch (e: any) {
    ElMessage.error(`暂停失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    pausing.value = false
  }
}

async function resumeExperiment() {
  resuming.value = true
  try {
    await axios.post(`/api/experiments/${selectedFilename.value}/resume`)
    ElMessage.success('实验已恢复')
  } catch (e: any) {
    ElMessage.error(`恢复失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    resuming.value = false
  }
}

async function stopExperiment() {
  try {
    await ElMessageBox.confirm('确定要停止实验吗？', '确认停止', {
      confirmButtonText: '停止', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }

  stopping.value = true
  try {
    const res = await axios.post(`/api/experiments/${selectedFilename.value}/stop`)
    if (!res.data.success) {
      ElMessage.error('停止未确认：至少一个设备停止或清理失败')
      return
    }
    ElMessage.info('实验已停止')
  } catch (e: any) {
    ElMessage.error(`停止失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    stopping.value = false
  }
}

async function pollProgress() {
  if (!selectedFilename.value) return
  try {
    const res = await axios.get(`/api/experiments/${selectedFilename.value}/progress`)
    const nextProgress = normalizeProgress(res.data)
    if (nextProgress.state === 'idle' && progress.value && terminalStates.has(progress.value.state)) {
      return
    }
    progress.value = nextProgress
    if (terminalStates.has(progress.value.state)) stopPolling()
  } catch (e) {
    // ignore
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollProgress, 1000)
}

onMounted(() => {
  loadExperiments()
  if (typeof route.query.filename === 'string') previewExperiment(route.query.filename)
  startPolling()
  connectWs()
})

onUnmounted(() => {
  wsClosed = true
  stopPolling()
  if (ws) ws.close()
})
</script>

<style scoped>
.experiment-page { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.card-header-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.exp-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  padding: 12px;
  border: 0;
  border-bottom: 1px solid #ebeef5;
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: all 0.2s;
}
.exp-item:hover { border-color: #409eff; background: #f0f7ff; }
.exp-item.active { border-color: #409eff; background: #ecf5ff; }
.exp-item:focus-visible { outline: 2px solid #409eff; outline-offset: -2px; }
.exp-number { flex: 0 0 24px; color: #909399; font-size: 13px; }
.exp-name { min-width: 0; font-weight: 600; font-size: 15px; overflow-wrap: anywhere; }
.preview-content { min-height: 100px; }
.preview-title { font-size: 20px; line-height: 1.5; margin: 0 0 8px; overflow-wrap: anywhere; }
.preview-filename { font-size: 12px; color: #909399; overflow-wrap: anywhere; }
.preview-description { white-space: pre-wrap; line-height: 1.7; overflow-wrap: anywhere; }
.preview-steps-title { font-size: 15px; margin: 18px 0 10px; }
.preview-step-list { max-height: 50vh; overflow-y: auto; border-top: 1px solid var(--el-border-color-light); }
.preview-step { padding: 12px 0; border-bottom: 1px solid var(--el-border-color-light); }
.preview-step-heading, .preview-step-details { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; overflow-wrap: anywhere; }
.preview-step-number { flex: 0 0 22px; color: var(--el-text-color-secondary); font-size: 12px; }
.preview-step-details { padding-left: 32px; color: var(--el-text-color-secondary); font-size: 13px; }
.preview-params { white-space: pre-wrap; overflow-wrap: anywhere; margin: 8px 0 0 32px; color: var(--el-text-color-regular); font-size: 12px; }
.experiment-page :deep(.experiment-preview .el-descriptions__content) { overflow-wrap: anywhere; }
@media (max-width: 991px) {
  .experiment-page > .el-row { row-gap: 16px; }
  .step-item { flex-wrap: wrap; }
  .card-header-actions :deep(.el-button + .el-button) { margin-left: 0; }
}
.progress-section { margin-bottom: 16px; }
.progress-header { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.progress-text { font-size: 14px; color: #606266; }
.elapsed { margin-left: auto; color: #909399; font-size: 13px; }
.steps-list { max-height: 300px; overflow-y: auto; }
.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-left: 3px solid transparent;
  border-bottom: 1px solid #f5f5f5;
}
.step-item.active { border-left-color: #409eff; background: #f0f7ff; }
.step-item.completed { border-left-color: #67c23a; opacity: 0.6; }
.step-item.failed { border-left-color: #f56c6c; background: #fef0f0; }
.step-item.skipped { border-left-color: #e6a23c; opacity: 0.6; }
.step-index {
  width: 24px; height: 24px; border-radius: 50%;
  background: #f0f0f0; text-align: center; line-height: 24px;
  font-size: 12px; color: #909399; flex-shrink: 0;
}
.step-item.active .step-index { background: #409eff; color: #fff; }
.step-item.completed .step-index { background: #67c23a; color: #fff; }
.step-item.failed .step-index { background: #f56c6c; color: #fff; }
.step-id { font-weight: 500; min-width: 100px; }

.log-container {
  max-height: 350px;
  overflow-y: auto;
  background: #1e1e1e;
  border-radius: 6px;
  padding: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
}
.log-empty {
  color: #666;
  text-align: center;
  padding: 30px;
}
.log-entry {
  padding: 4px 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  line-height: 1.6;
}
.log-time { color: #6a9955; flex-shrink: 0; }
.log-tag { flex-shrink: 0; }
.log-msg { color: #d4d4d4; }
.log-detail { color: #9cdcfe; margin-left: 4px; }
.log-info .log-msg { color: #d4d4d4; }
.log-success .log-msg { color: #6a9955; }
.log-warning .log-msg { color: #dcdcaa; }
.log-error .log-msg { color: #f44747; }
.log-error .log-detail { color: #ce9178; }
</style>
