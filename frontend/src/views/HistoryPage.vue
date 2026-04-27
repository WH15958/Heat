<template>
  <div class="history-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>实验历史记录</span>
          <el-button size="small" @click="loadRuns" :loading="loading">刷新</el-button>
        </div>
      </template>

      <div v-if="runs.length === 0 && !loading" class="empty-state">
        暂无历史记录，运行实验后自动保存
      </div>

      <el-table :data="runs" stripe style="width: 100%" @row-click="showDetail" v-else>
        <el-table-column prop="run_id" label="Run ID" width="220" />
        <el-table-column prop="experiment_name" label="实验名称" width="200" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.started_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="total_duration" label="总耗时" width="100">
          <template #default="{ row }">
            {{ row.total_duration ? row.total_duration.toFixed(1) + 's' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="步骤" width="120">
          <template #default="{ row }">
            <span style="color: #67c23a">{{ row.completed_steps || 0 }}</span>
            <span style="color: #909399"> / </span>
            <span>{{ row.total_steps || 0 }}</span>
            <span v-if="row.failed_steps" style="color: #f56c6c; margin-left: 4px">
              ({{ row.failed_steps }} 失败)
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="experiment_file" label="文件" />
      </el-table>
    </el-card>

    <el-dialog v-model="detailVisible" :title="detailTitle" width="70%" top="5vh">
      <div v-if="detailData">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
          <el-descriptions-item label="Run ID">{{ detailData.run_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(detailData.status)" size="small">{{ statusLabel(detailData.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="总耗时">{{ detailData.total_duration?.toFixed(1) }}s</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(detailData.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(detailData.finished_at) }}</el-descriptions-item>
          <el-descriptions-item label="步骤统计">
            完成 {{ detailData.completed_steps }} / 失败 {{ detailData.failed_steps }} / 共 {{ detailData.total_steps }}
          </el-descriptions-item>
        </el-descriptions>

        <h4 style="margin: 12px 0 8px">步骤详情</h4>
        <el-table :data="detailData.steps || []" stripe size="small" max-height="400">
          <el-table-column prop="step_index" label="#" width="50" />
          <el-table-column prop="step_id" label="步骤ID" width="150" />
          <el-table-column prop="action_type" label="动作" width="180" />
          <el-table-column prop="status" label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="duration" label="耗时" width="80">
            <template #default="{ row }">
              {{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="started_at" label="开始" width="160">
            <template #default="{ row }">
              {{ formatTime(row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="error" label="错误">
            <template #default="{ row }">
              <span v-if="row.error" style="color: #f56c6c">{{ row.error }}</span>
              <span v-else style="color: #c0c4cc">-</span>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 16px; text-align: right">
          <el-button type="primary" size="small" @click="exportRunLog">导出此记录</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface RunData {
  run_id: string
  experiment_name: string
  experiment_file: string
  status: string
  started_at: string
  finished_at: string
  total_duration: number
  total_steps: number
  completed_steps: number
  failed_steps: number
  steps: any[]
  log_file: string
}

const runs = ref<RunData[]>([])
const loading = ref(false)
const detailVisible = ref(false)
const detailData = ref<RunData | null>(null)
const detailTitle = ref('')

function statusTagType(status: string): string {
  const map: Record<string, string> = {
    completed: 'success', failed: 'danger', stopped: 'warning',
    running: 'primary', paused: 'warning',
  }
  return map[status] || 'info'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    completed: '已完成', failed: '失败', stopped: '已停止',
    running: '运行中', paused: '已暂停',
  }
  return map[status] || status
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

async function loadRuns() {
  loading.value = true
  try {
    const res = await axios.get('/api/experiments/history/runs')
    runs.value = res.data
  } catch (e: any) {
    ElMessage.error(`加载历史记录失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function showDetail(row: RunData) {
  try {
    const res = await axios.get(`/api/experiments/history/runs/${row.run_id}`)
    detailData.value = res.data
    detailTitle.value = `${res.data.experiment_name} - ${res.data.run_id}`
    detailVisible.value = true
  } catch (e: any) {
    ElMessage.error(`加载详情失败: ${e.message}`)
  }
}

function exportRunLog() {
  if (!detailData.value) return
  const data = detailData.value
  const lines: string[] = []
  lines.push(`实验记录: ${data.experiment_name}`)
  lines.push(`Run ID: ${data.run_id}`)
  lines.push(`状态: ${statusLabel(data.status)}`)
  lines.push(`开始: ${formatTime(data.started_at)}`)
  lines.push(`结束: ${formatTime(data.finished_at)}`)
  lines.push(`总耗时: ${data.total_duration?.toFixed(1)}s`)
  lines.push(`步骤: 完成 ${data.completed_steps} / 失败 ${data.failed_steps} / 共 ${data.total_steps}`)
  lines.push('')
  lines.push('--- 步骤详情 ---')
  for (const step of data.steps || []) {
    lines.push(`[${step.step_index + 1}] ${step.step_id} | ${step.action_type} | ${statusLabel(step.status)} | 耗时: ${step.duration?.toFixed(1) || '-'}s${step.error ? ' | 错误: ' + step.error : ''}`)
  }
  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `experiment_${data.run_id}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadRuns()
})

onUnmounted(() => {
  detailVisible.value = false
})
</script>

<style scoped>
.history-page { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.empty-state { text-align: center; padding: 40px; color: #909399; }
</style>
