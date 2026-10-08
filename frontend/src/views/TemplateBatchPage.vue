<template>
  <div class="batch-page">
    <header><div><h2>高级模板参数设计</h2><p>从已有实验生成多组条件，保留真实设备动作和固定步骤。</p></div><el-button @click="router.push('/experiment/batch')">返回引导式实验</el-button></header>
    <el-alert title="当前可生成、校验和保存单组实验；外部分流阀、圆盘收集及跨组自动调度尚未接入，不提供整批启动。" type="info" :closable="false" />
    <section>
      <h3>1. 选择固定流程</h3>
      <div class="controls"><label>现有实验<select v-model="filename" :disabled="busy" @change="loadTemplate"><option value="">请选择</option><option v-for="item in templates" :key="item.filename" :value="item.filename">{{ item.name }} · {{ item.filename }}</option></select></label><label>新批次名称<input v-model="batch" :disabled="busy" placeholder="例如 batch_001" /></label></div>
      <p v-if="source">已读取 {{ filename }} 的版本 {{ revision.slice(0, 10) }}。以下步骤直接来自文件，不补入假设的清洗或收集动作。</p>
      <ol class="flow"><li v-for="step in steps" :key="step.id"><strong>{{ actionLabel(step.type) }}</strong><span>{{ step.id }} · {{ step.params?.device_id || '通用' }}{{ step.enabled === false ? ' · 已禁用' : '' }}</span></li></ol>
      <el-button v-if="filename" @click="router.push({ path: '/experiment/editor', query: { filename } })">在现有编辑器维护固定流程</el-button>
    </section>
    <section v-if="source">
      <h3>2. 设置本批变量</h3>
      <p>只提取模板已有的加热器目标温度、注射泵吸排量和定时等待。其他参数保持原样。吸取与排出量分别对应原步骤，请核对两者关系；等待时长只有在原流程如此定义时才代表保温时间。</p>
      <p v-if="!axes.length">此模板没有可提取的变量，可先在编辑器中完善流程。</p>
      <div v-for="axis in axes" :key="axis.key" class="axis">
        <label class="axis-name">{{ axis.label }}</label>
        <select v-model="axis.mode" :disabled="busy"><option value="fixed">固定值</option><option value="range">范围与间隔</option><option value="list">指定数值</option></select>
        <template v-if="axis.mode !== 'list'"><label>{{ axis.mode === 'fixed' ? '数值' : '起点' }}<input v-model.number="axis.start" :disabled="busy" type="number" step="any" /></label></template>
        <template v-if="axis.mode === 'range'"><label>终点<input v-model.number="axis.end" :disabled="busy" type="number" step="any" /></label><label>间隔<input v-model.number="axis.interval" :disabled="busy" type="number" step="any" /></label></template>
        <label v-if="axis.mode === 'list'">用逗号分隔<input v-model="axis.list" :disabled="busy" placeholder="输入数值列表" /></label>
      </div>
      <p>范围按间隔递增，不超过终点；不能整除时不会额外插入终点。全部独立变量做笛卡尔组合，最多 200 组。</p>
    </section>
    <el-alert v-if="error || plan.error" :title="error || plan.error" type="error" :closable="false" />
    <section v-if="source && !plan.error">
      <h3>3. 条件预览 · {{ plan.rows.length }} 组</h3>
      <p v-for="total in totals" :key="total.device">{{ total.device }}：整批理论排出量 {{ total.volume }} mL（仅统计模板的显式注射泵排出动作，不含程序内部动作、清洗或预灌消耗）。</p>
      <p v-if="!generated">请填写有效批次名称：1–60 位字母、数字、下划线或短横线。</p>
      <p>组号是计划顺序，不代表圆盘已经具备定位能力。此处不会连接或启动设备。</p>
      <div class="table-wrap"><table><thead><tr><th>组号</th><th v-for="axis in axes" :key="axis.key">{{ axis.label }}</th><th>文件</th></tr></thead><tbody><tr v-for="(row, i) in plan.rows" :key="i" :class="{ selected: selected === i }" @click="selectRow(i)"><td>{{ i + 1 }}</td><td v-for="(value, j) in row" :key="j">{{ value }}</td><td><button :disabled="busy" @click.stop="selectRow(i)">查看第 {{ i + 1 }} 组</button></td></tr></tbody></table></div>
      <div class="actions"><el-button :loading="busy" :disabled="!generated" @click="validateAll">校验全部组合</el-button><el-button :disabled="busy || !generated" @click="saveSelected">校验并另存所选组</el-button></div>
      <p v-if="report" role="status">{{ report }}</p>
      <p v-if="saved">已保存 {{ saved }}。<router-link :to="{ path: '/experiment/editor', query: { filename: saved } }">打开现有编辑器审阅</router-link></p>
      <p>文件校验验证现有解析规则，不代表液路、容量、设备就绪或实机验收通过。保存只创建新文件，不覆盖已有实验。</p>
      <details open><summary>第 {{ selected + 1 }} 组 · 真实 YAML</summary><pre>{{ generated }}</pre></details>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { editorApi } from '../api/experimentEditor'
import { actionLabel } from '../experiment/catalog'
import { inspectSource, stepsFrom } from '../experiment/document'
import { combinations, generateSource, variablesFrom, type Axis } from '../experiment/batch'

const router = useRouter()
const templates = ref<{ filename: string; name: string }[]>([])
const filename = ref(''), source = ref(''), revision = ref(''), batch = ref('batch_001')
const axes = ref<Axis[]>([]), selected = ref(0), busy = ref(false), error = ref(''), report = ref(''), saved = ref('')
const steps = computed(() => source.value ? stepsFrom(inspectSource(source.value).doc) : [])
const plan = computed(() => {
  try { return { rows: source.value ? combinations(axes.value) : [], error: '' } }
  catch (e) { return { rows: [] as number[][], error: String(e) } }
})
const generated = computed(() => {
  const row = plan.value.rows[selected.value]
  if (!source.value || !row) return ''
  try { return generateSource(source.value, axes.value, row, batch.value, selected.value) }
  catch { return '' }
})
const totals = computed(() => {
  const sums = new Map<string, number>()
  for (const row of plan.value.rows) {
    steps.value.forEach((step, index) => {
      const p = step.params || {}
      if (step.enabled === false || step.type !== 'syringe_pump.dispense' || !['uL', 'mL', undefined].includes(p.unit)) return
      const axis = axes.value.findIndex(a => a.key === `${index}-volume`)
      const amount = axis < 0 ? p.volume : row[axis]
      if (typeof amount !== 'number' || !Number.isFinite(amount)) return
      const device = String(p.device_id)
      sums.set(device, (sums.get(device) || 0) + amount / (p.unit === 'mL' ? 1 : 1000))
    })
  }
  return [...sums].map(([device, volume]) => ({ device, volume: Number(volume.toPrecision(10)) }))
})
watch([axes, batch], () => { selected.value = 0; report.value = ''; saved.value = ''; error.value = '' }, { deep: true })
function selectRow(i: number) { if (!busy.value) { selected.value = i; saved.value = '' } }
function message(e: any) { return String(e.response?.data?.detail || e.message || e) }
async function loadTemplate() {
  source.value = ''; axes.value = []; error.value = ''; report.value = ''; saved.value = ''; selected.value = 0
  if (!filename.value) return
  busy.value = true
  try {
    const { data } = await editorApi.read(filename.value)
    const variables = variablesFrom(data.content)
    axes.value = variables.map(v => ({ ...v, mode: 'fixed', start: v.value, end: v.value, interval: 1, list: String(v.value) }))
    source.value = data.content; revision.value = data.revision
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
async function validateAll() {
  busy.value = true; error.value = ''; report.value = ''
  try {
    const warnings: string[] = []
    for (const [i, row] of plan.value.rows.entries()) {
      const content = generateSource(source.value, axes.value, row, batch.value, i)
      const { data } = await editorApi.validate(content)
      if (!data.valid) throw new Error(`第 ${i + 1} 组：${data.errors.map(e => e.message).join('；')}`)
      warnings.push(...data.warnings.map(w => `第 ${i + 1} 组：${w.message}`))
      report.value = `已校验 ${i + 1} / ${plan.value.rows.length} 组`
      if (data.warnings.length) report.value += `；提示：${data.warnings.map(w => w.message).join('；')}`
    }
    report.value = `已校验 ${plan.value.rows.length} 组；未运行设备。${warnings.length ? warnings.join('；') : '无额外提示。'}`
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
async function saveSelected() {
  busy.value = true; error.value = ''; saved.value = ''
  try {
    const content = generated.value
    if (!content) throw new Error('请检查批次名称与变量')
    const { data } = await editorApi.validate(content)
    if (!data.valid) throw new Error(data.errors.map(e => e.message).join('；'))
    const name = `${batch.value}_${String(selected.value + 1).padStart(3, '0')}.yaml`
    await editorApi.save(name, content, null)
    saved.value = name
    report.value = data.warnings.map(w => w.message).join('；') || '文件校验通过，尚未运行。'
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}
onMounted(async () => {
  try { templates.value = (await axios.get('/api/experiments/')).data }
  catch (e) { error.value = `读取实验失败：${message(e)}` }
})
</script>

<style scoped>
.batch-page { max-width: 1400px; margin: auto; padding: 12px; color: #243547; }
header, .controls, .axis, .actions { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
header { justify-content: space-between; margin-bottom: 20px; }
h2 { margin: 0; } h3 { margin-top: 0; } p { color: #5a6c7d; line-height: 1.7; }
section { margin-top: 20px; padding: 24px; background: var(--el-bg-color, white); border: 1px solid #dce4eb; border-radius: 12px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
input, select { padding: 9px; border: 1px solid #bccbd7; border-radius: 6px; max-width: 100%; }
.axis { padding: 12px 0; border-bottom: 1px solid #edf1f5; } .axis-name { flex: 1; min-width: 230px; } .axis input { width: 115px; }
.flow { display: flex; flex-wrap: wrap; gap: 12px; padding-left: 24px; } .flow li { padding: 8px; } .flow span { display: block; font-size: 12px; color: #65798b; }
.table-wrap { overflow: auto; max-height: 400px; } table { border-collapse: collapse; width: 100%; font-size: 13px; } th, td { text-align: left; padding: 12px; border-bottom: 1px solid #dce4eb; } th { background: #f2f6fa; } .selected { background: #eaf4ff; } .actions { margin-top: 20px; }
pre { overflow: auto; max-height: 420px; padding: 18px; background: #142333; color: #dce8f3; border-radius: 8px; } summary { cursor: pointer; }
</style>
