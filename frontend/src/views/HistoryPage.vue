<template>
  <div class="history-page">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>实验历史记录</span>
          <div>
            <el-button size="small" type="danger" @click="deleteAll" :disabled="runs.length === 0" :loading="deleting">清空全部</el-button>
            <el-button size="small" @click="loadRuns" :loading="loading">刷新</el-button>
          </div>
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
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" size="small" link @click.stop="deleteRun(row)" :loading="deleting">删除</el-button>
          </template>
        </el-table-column>
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
          <el-button type="danger" size="small" @click="deleteFromDetail" :loading="deleting">删除此记录</el-button>
          <el-button type="primary" size="small" @click="exportRunLog">导出此记录</el-button>
        </div>

        <div v-if="hasSensorData" style="margin-top: 20px">
          <h4 style="margin: 0 0 12px">实验报告曲线</h4>
          <el-card shadow="never" v-if="hasHeaterData" style="margin-bottom: 16px">
            <template #header><span>温度曲线</span></template>
            <div ref="reportTempChartRef" style="width: 100%; height: 320px"></div>
          </el-card>
          <el-card shadow="never" v-if="hasPumpData" style="margin-bottom: 16px">
            <template #header><span>流量曲线</span></template>
            <div ref="reportFlowChartRef" style="width: 100%; height: 320px"></div>
          </el-card>
          <el-card shadow="never" v-if="hasPumpData">
            <template #header><span>累计体积曲线</span></template>
            <div ref="reportVolumeChartRef" style="width: 100%; height: 320px"></div>
          </el-card>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'

interface TimePoint {
  t: number
  v: number | null
}

interface HeaterSensorData {
  pv: TimePoint[]
  sv: TimePoint[]
}

interface ChannelSensorData {
  flow_rate: TimePoint[]
  volume: TimePoint[]
  flow_unit?: string
}

interface SensorData {
  heaters: Record<string, HeaterSensorData>
  pumps: Record<string, Record<string, ChannelSensorData>>
}

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
  sensor_data?: SensorData
}

const runs = ref<RunData[]>([])
const loading = ref(false)
const deleting = ref(false)
const detailVisible = ref(false)
const detailData = ref<RunData | null>(null)
const detailTitle = ref('')
const reportTempChartRef = ref<HTMLElement>()
const reportFlowChartRef = ref<HTMLElement>()
const reportVolumeChartRef = ref<HTMLElement>()
let reportTempChart: echarts.ECharts | null = null
let reportFlowChart: echarts.ECharts | null = null
let reportVolumeChart: echarts.ECharts | null = null

const FLOW_UNIT_LABELS: Record<string, string> = {
  ML_MIN: 'mL/min',
  UL_MIN: 'uL/min',
  L_MIN: 'L/min',
  RPM: 'RPM',
}

function flowUnitLabel(unit: string | undefined): string {
  return FLOW_UNIT_LABELS[unit || 'ML_MIN'] || 'mL/min'
}

const VOLUME_UNIT_MAP: Record<string, string> = {
  ML_MIN: 'mL',
  UL_MIN: 'uL',
  L_MIN: 'L',
  RPM: '',
}

function volumeUnitLabel(flowUnit: string | undefined): string {
  return VOLUME_UNIT_MAP[flowUnit || 'ML_MIN'] || 'mL'
}

function flowYAxisName(sd: SensorData): string {
  const units = new Set<string>()
  for (const pdata of Object.values(sd.pumps)) {
    for (const chdata of Object.values(pdata)) {
      if (chdata.flow_unit) units.add(chdata.flow_unit)
    }
  }
  if (units.size === 1) {
    return `流量(${flowUnitLabel([...units][0])})`
  }
  return '流量'
}

function volumeYAxisName(sd: SensorData): string {
  const units = new Set<string>()
  for (const pdata of Object.values(sd.pumps)) {
    for (const chdata of Object.values(pdata)) {
      if (chdata.flow_unit) units.add(chdata.flow_unit)
    }
  }
  if (units.size === 1) {
    const vu = volumeUnitLabel([...units][0])
    return vu ? `累计体积(${vu})` : '累计体积'
  }
  return '累计体积'
}

const hasSensorData = computed(() => {
  const sd = detailData.value?.sensor_data
  if (!sd) return false
  return hasHeaterData.value || hasPumpData.value
})

const hasHeaterData = computed(() => {
  const sd = detailData.value?.sensor_data
  if (!sd?.heaters) return false
  return Object.keys(sd.heaters).length > 0
})

const hasPumpData = computed(() => {
  const sd = detailData.value?.sensor_data
  if (!sd?.pumps) return false
  return Object.keys(sd.pumps).length > 0
})

function renderReportCharts() {
  nextTick(() => {
    const sd = detailData.value?.sensor_data
    if (!sd) return

    if (sd.heaters && Object.keys(sd.heaters).length > 0 && reportTempChartRef.value) {
      if (reportTempChart) reportTempChart.dispose()
      reportTempChart = echarts.init(reportTempChartRef.value)
      const series: echarts.SeriesOption[] = []
      const legend: string[] = []
      for (const [hid, hdata] of Object.entries(sd.heaters)) {
        if (hdata.pv?.length) {
          legend.push(`${hid} PV`)
          series.push({
            name: `${hid} PV`,
            type: 'line',
            data: hdata.pv.map((p: TimePoint) => [p.t, p.v]),
            smooth: true,
            showSymbol: false,
          })
        }
        if (hdata.sv?.length) {
          legend.push(`${hid} SV`)
          series.push({
            name: `${hid} SV`,
            type: 'line',
            data: hdata.sv.map((p: TimePoint) => [p.t, p.v]),
            lineStyle: { type: 'dashed' },
            showSymbol: false,
          })
        }
      }
      reportTempChart.setOption({
        tooltip: { trigger: 'axis', formatter: (params: any) => {
          const t = params[0]?.data?.[0]
          let s = `时间: ${t}s<br/>`
          for (const p of params) {
            s += `${p.seriesName}: ${p.data[1]?.toFixed(1)}°C<br/>`
          }
          return s
        }},
        legend: { data: legend, top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'value', name: '时间(s)' },
        yAxis: { type: 'value', name: '温度(°C)' },
        series,
      })
    }

    if (sd.pumps && Object.keys(sd.pumps).length > 0 && reportFlowChartRef.value) {
      if (reportFlowChart) reportFlowChart.dispose()
      reportFlowChart = echarts.init(reportFlowChartRef.value)
      const series: echarts.SeriesOption[] = []
      const legend: string[] = []
      const colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c']
      for (const [pid, pdata] of Object.entries(sd.pumps)) {
        for (const [chid, chdata] of Object.entries(pdata)) {
          if (chdata.flow_rate?.length) {
            const name = `${pid} CH${chid}`
            legend.push(name)
            const colorIdx = (parseInt(chid) - 1) % colors.length
            series.push({
              name,
              type: 'line',
              data: chdata.flow_rate.map((p: TimePoint) => [p.t, p.v]),
              smooth: true,
              showSymbol: false,
              lineStyle: { color: colors[colorIdx] },
              itemStyle: { color: colors[colorIdx] },
              areaStyle: { opacity: 0.1 },
            })
          }
        }
      }
      reportFlowChart.setOption({
        tooltip: { trigger: 'axis', formatter: (params: any) => {
          const t = params[0]?.data?.[0]
          let s = `时间: ${t}s<br/>`
          for (const p of params) {
            s += `${p.seriesName}: ${p.data[1]?.toFixed(2)}<br/>`
          }
          return s
        }},
        legend: { data: legend, top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'value', name: '时间(s)' },
        yAxis: { type: 'value', name: flowYAxisName(sd) },
        series,
      })
    }

    if (sd.pumps && Object.keys(sd.pumps).length > 0 && reportVolumeChartRef.value) {
      if (reportVolumeChart) reportVolumeChart.dispose()
      reportVolumeChart = echarts.init(reportVolumeChartRef.value)
      const series: echarts.SeriesOption[] = []
      const legend: string[] = []
      const colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c']
      const channelVolumeUnits: Record<string, string> = {}
      for (const [pid, pdata] of Object.entries(sd.pumps)) {
        for (const [chid, chdata] of Object.entries(pdata)) {
          if (chdata.flow_rate?.length) {
            const name = `${pid} CH${chid}`
            legend.push(name)
            const colorIdx = (parseInt(chid) - 1) % colors.length
            channelVolumeUnits[name] = volumeUnitLabel(chdata.flow_unit)
            const cumulative: [number, number][] = []
            let vol = 0.0
            for (let i = 0; i < chdata.flow_rate.length; i++) {
              const cur = chdata.flow_rate[i]
              if (i > 0) {
                const prev = chdata.flow_rate[i - 1]
                const dt = (cur.t - prev.t) / 60.0
                const avgRate = ((prev.v ?? 0) + (cur.v ?? 0)) / 2.0
                vol += avgRate * dt
              }
              cumulative.push([cur.t, parseFloat(vol.toFixed(4))])
            }
            series.push({
              name,
              type: 'line',
              data: cumulative,
              smooth: true,
              showSymbol: false,
              lineStyle: { color: colors[colorIdx] },
              itemStyle: { color: colors[colorIdx] },
              areaStyle: { opacity: 0.08 },
            })
          }
        }
      }
      reportVolumeChart.setOption({
        tooltip: { trigger: 'axis', formatter: (params: any) => {
          const t = params[0]?.data?.[0]
          let s = `时间: ${t}s<br/>`
          for (const p of params) {
            const vu = channelVolumeUnits[p.seriesName] || 'mL'
            const unitStr = vu ? ` ${vu}` : ''
            s += `${p.seriesName}: ${p.data[1]?.toFixed(2)}${unitStr}<br/>`
          }
          return s
        }},
        legend: { data: legend, top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'value', name: '时间(s)' },
        yAxis: { type: 'value', name: volumeYAxisName(sd) },
        series,
      })
    }
  })
}

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
    renderReportCharts()
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

async function deleteRun(row: RunData) {
  if (deleting.value) return
  try {
    await ElMessageBox.confirm(
      `确定要删除实验记录 "${row.experiment_name}" (${row.run_id}) 吗？`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }

  deleting.value = true
  try {
    await axios.delete(`/api/experiments/history/runs/${row.run_id}`)
    ElMessage.success('已删除')
    loadRuns()
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    deleting.value = false
  }
}

async function deleteFromDetail() {
  if (!detailData.value || deleting.value) return
  try {
    await ElMessageBox.confirm(
      `确定要删除此实验记录 (${detailData.value.run_id}) 吗？`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }

  deleting.value = true
  try {
    await axios.delete(`/api/experiments/history/runs/${detailData.value.run_id}`)
    detailVisible.value = false
    ElMessage.success('已删除')
    loadRuns()
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    deleting.value = false
  }
}

async function deleteAll() {
  if (deleting.value) return
  try {
    await ElMessageBox.confirm(
      '确定要清空所有实验历史记录吗？此操作不可恢复！',
      '确认清空',
      { confirmButtonText: '清空', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }

  deleting.value = true
  try {
    await axios.delete('/api/experiments/history/runs')
    ElMessage.success('已清空全部记录')
    loadRuns()
  } catch (e: any) {
    ElMessage.error(`清空失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  loadRuns()
})

onUnmounted(() => {
  detailVisible.value = false
  reportTempChart?.dispose()
  reportFlowChart?.dispose()
  reportVolumeChart?.dispose()
  reportTempChart = null
  reportFlowChart = null
  reportVolumeChart = null
})
</script>

<style scoped>
.history-page { padding: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.empty-state { text-align: center; padding: 40px; color: #909399; }
</style>
