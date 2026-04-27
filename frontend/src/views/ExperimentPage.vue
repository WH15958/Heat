<template>
  <div class="experiment-page">
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><span>可用实验</span></template>
          <div v-if="experiments.length === 0" style="color: #909399; text-align: center; padding: 20px">
            暂无实验，请在 experiments/ 目录下添加 YAML 文件
          </div>
          <div
            v-for="exp in experiments"
            :key="exp.filename"
            class="exp-item"
            :class="{ active: selectedFilename === exp.filename }"
            @click="selectExperiment(exp.filename)"
          >
            <div class="exp-name">{{ exp.name }}</div>
            <div class="exp-desc">{{ exp.description || '无描述' }}</div>
            <div class="exp-meta">{{ exp.steps_count }} 个步骤 · {{ exp.filename }}</div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-card shadow="hover" v-if="selectedExp">
          <template #header>
            <div class="card-header">
              <span>{{ selectedExp.name }}</span>
              <div>
                <el-button type="success" @click="startExperiment" :disabled="isRunning" :loading="starting">
                  启动实验
                </el-button>
                <el-button type="warning" @click="pauseExperiment" :disabled="!isRunning">
                  暂停
                </el-button>
                <el-button type="primary" @click="resumeExperiment" :disabled="!isPaused">
                  恢复
                </el-button>
                <el-button type="danger" @click="stopExperiment" :disabled="!isRunning && !isPaused">
                  停止
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="progress" class="progress-section">
            <div class="progress-header">
              <el-tag :type="stateTagType" size="large">{{ stateLabel }}</el-tag>
              <span class="progress-text">
                步骤 {{ progress.current_step + 1 }} / {{ progress.total_steps }}
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
                active: progress && idx === progress.current_step,
                completed: stepStatusMap[idx] === 'completed',
                failed: stepStatusMap[idx] === 'failed',
                skipped: stepStatusMap[idx] === 'skipped',
              }"
            >
              <span class="step-index">{{ idx + 1 }}</span>
              <span class="step-id">{{ step.id }}</span>
              <el-tag size="small" type="info">{{ step.type }}</el-tag>
              <el-tag v-if="step.wait_type !== 'none'" size="small" type="warning">
                等待: {{ step.wait_type }}
              </el-tag>
              <el-tag v-if="stepStatusMap[idx]" :type="stepTagType(stepStatusMap[idx])" size="small">
                {{ stepStatusLabel(stepStatusMap[idx]) }}
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

    <el-card shadow="hover" style="margin-top: 20px" v-if="selectedFilename">
      <template #header>
        <div class="card-header">
          <span>实验日志</span>
          <div>
            <el-tag v-if="currentRunId" type="info" size="small">Run: {{ currentRunId }}</el-tag>
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
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

interface ExperimentSummary {
  filename: string
  name: string
  description: string
  steps_count: number
}

interface ExperimentDetail {
  name: string
  description: string
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
const selectedExp = ref<ExperimentDetail | null>(null)
const selectedFilename = ref('')
const progress = ref<ExperimentProgress | null>(null)
const starting = ref(false)
const currentRunId = ref('')
const logEntries = ref<LogEntry[]>([])
const stepStatusMap = ref<Record<number, string>>({})
const logContainer = ref<HTMLElement | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null
let ws: WebSocket | null = null

const isRunning = computed(() => progress.value?.state === 'running')
const isPaused = computed(() => progress.value?.state === 'paused')

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
  if (!progress.value || progress.value.total_steps === 0) return 0
  return Math.round((progress.value.current_step / progress.value.total_steps) * 100)
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
    if (msg.type === 'experiment_log' && msg.filename === selectedFilename.value) {
      const evt = msg.event
      const data = msg.data

      if (evt === 'run_started') {
        currentRunId.value = data.run_id
        stepStatusMap.value = {}
        addLog('success', '实验启动', `${data.experiment_name} (${data.run_id})`, `共 ${data.total_steps} 个步骤`)
      } else if (evt === 'step_started') {
        stepStatusMap.value[data.step_index] = 'running'
        addLog('info', '步骤开始', `[${data.step_index + 1}] ${data.step_id}`, `动作: ${data.action_type}`)
      } else if (evt === 'step_finished') {
        stepStatusMap.value[data.step_index] = data.status
        const level = data.status === 'completed' ? 'success' : 'error'
        const label = data.status === 'completed' ? '步骤完成' : '步骤失败'
        const dur = data.duration ? ` 耗时 ${data.duration.toFixed(1)}s` : ''
        addLog(level, label, `[${data.step_index + 1}] ${data.step_id}${dur}`, data.error || undefined)
      } else if (evt === 'step_skipped') {
        stepStatusMap.value[data.step_index] = 'skipped'
        addLog('warning', '步骤跳过', `[${data.step_index + 1}] ${data.step_id}`, data.error || '')
      } else if (evt === 'run_paused') {
        addLog('warning', '实验暂停', `Run: ${data.run_id}`)
      } else if (evt === 'run_resumed') {
        addLog('info', '实验恢复', `Run: ${data.run_id}`)
      } else if (evt === 'run_finished') {
        const level = data.status === 'completed' ? 'success' : data.status === 'failed' ? 'error' : 'warning'
        const label = data.status === 'completed' ? '实验完成' : data.status === 'failed' ? '实验失败' : '实验停止'
        const dur = data.total_duration ? ` 总耗时 ${data.total_duration.toFixed(1)}s` : ''
        addLog(level, label, `${data.experiment_name}${dur}`,
          `完成: ${data.completed_steps} 失败: ${data.failed_steps}`)
      }
    }
  } catch {
    // ignore non-JSON messages
  }
}

function connectWs() {
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
      setTimeout(connectWs, 5000)
    }
  } catch (error) {
    console.error('Failed to connect WebSocket:', error)
    setTimeout(connectWs, 5000)
  }
}

async function loadExperiments() {
  try {
    const res = await axios.get('/api/experiments/')
    experiments.value = res.data
  } catch (e) {
    console.error('Failed to load experiments:', e)
  }
}

async function selectExperiment(filename: string) {
  selectedFilename.value = filename
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
    const res = await axios.post(`/api/experiments/${selectedFilename.value}/start`)
    currentRunId.value = res.data.run_id || ''
    ElMessage.success('实验已启动')
    startPolling()
  } catch (e: any) {
    ElMessage.error(`启动失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    starting.value = false
  }
}

async function pauseExperiment() {
  try {
    await axios.post(`/api/experiments/${selectedFilename.value}/pause`)
    ElMessage.warning('实验已暂停')
  } catch (e: any) {
    ElMessage.error(`暂停失败: ${e.response?.data?.detail || e.message}`)
  }
}

async function resumeExperiment() {
  try {
    await axios.post(`/api/experiments/${selectedFilename.value}/resume`)
    ElMessage.success('实验已恢复')
  } catch (e: any) {
    ElMessage.error(`恢复失败: ${e.response?.data?.detail || e.message}`)
  }
}

async function stopExperiment() {
  try {
    await ElMessageBox.confirm('确定要停止实验吗？', '确认停止', {
      confirmButtonText: '停止', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }

  try {
    await axios.post(`/api/experiments/${selectedFilename.value}/stop`)
    ElMessage.info('实验已停止')
  } catch (e: any) {
    ElMessage.error(`停止失败: ${e.response?.data?.detail || e.message}`)
  }
}

async function pollProgress() {
  if (!selectedFilename.value) return
  try {
    const res = await axios.get(`/api/experiments/${selectedFilename.value}/progress`)
    progress.value = res.data
  } catch (e) {
    // ignore
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(pollProgress, 1000)
}

onMounted(() => {
  loadExperiments()
  startPolling()
  connectWs()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (ws) ws.close()
})
</script>

<style scoped>
.experiment-page { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.exp-item {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.exp-item:hover { border-color: #409eff; background: #f0f7ff; }
.exp-item.active { border-color: #409eff; background: #ecf5ff; }
.exp-name { font-weight: 600; font-size: 15px; margin-bottom: 4px; }
.exp-desc { color: #909399; font-size: 13px; margin-bottom: 4px; }
.exp-meta { color: #c0c4cc; font-size: 12px; }
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
