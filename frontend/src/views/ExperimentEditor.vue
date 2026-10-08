<template>
  <div class="experiment-editor" v-loading="loading">
    <header class="editor-top">
      <div><h2>实验编排</h2><span>{{ dirty ? '有未保存修改' : '已与打开的版本一致' }}</span></div>
      <div class="tools">
        <el-button @click="router.push('/experiment/batch')">引导式实验</el-button>
        <el-button @click="router.push({ path: '/experiment', query: loadedFilename ? { filename: loadedFilename } : {} })">返回实验</el-button>
        <el-button :disabled="cursor === 0" @click="undo">撤销</el-button>
        <el-button :disabled="cursor >= history.length - 1" @click="redo">重做</el-button>
        <el-button @click="fileInput?.click()">导入 YAML</el-button>
        <input ref="fileInput" type="file" accept=".yaml,.yml" hidden @change="importFile" />
        <el-button @click="download">下载</el-button>
        <el-button :loading="validating" @click="validate">校验</el-button>
        <el-button :disabled="saving || loading" @click="saveAs">另存为</el-button>
        <el-button type="primary" :loading="saving" :disabled="loading" @click="save(filename)">保存</el-button>
      </div>
    </header>
    <el-alert v-if="fileError" :title="fileError" type="error" :closable="false" />
    <el-button v-if="loadedFilename" size="small" @click="reload">重新读取服务器文件</el-button>
    <div class="document-heading">
      <label>文件名<input v-model="filename" placeholder="experiment.yaml" /></label>
      <label>实验名称<input :value="definition.name ?? ''" :disabled="!inspection.editable" @change="set(['name'], inputText($event))" /></label>
      <label class="description">描述<input :value="definition.description ?? ''" :disabled="!inspection.editable" @change="set(['description'], inputText($event))" /></label>
      <el-button :disabled="!inspection.editable" @click="openAdvanced(['metadata'], '实验元数据')">元数据</el-button>
    </div>
    <div class="mode-bar">
      <div role="tablist" aria-label="编排模式">
        <button role="tab" :aria-selected="mode === 'graph'" :disabled="!inspection.editable" @click="mode = 'graph'">图形编排</button>
        <button role="tab" :aria-selected="mode === 'yaml'" @click="mode = 'yaml'">YAML 编辑</button>
      </div>
      <span>{{ steps.length }} 个步骤 · 编排和保存不会连接或运行设备</span>
    </div>
    <el-alert v-if="inspection.errors.length || inspection.restriction" :title="inspection.errors.join('；') || inspection.restriction" type="warning" :closable="false" />
    <div v-if="localErrors.length" class="issues" aria-live="polite"><strong>需要处理</strong><p v-for="message in localErrors" :key="message">{{ message }}</p></div>
    <div v-if="validation" class="issues" :class="{ valid: validation.valid }" aria-live="polite">
      <strong>{{ validation.valid ? '文件校验通过（不代表设备就绪或安全确认）' : '文件校验未通过' }}</strong>
      <button v-for="(issue, i) in [...validation.errors, ...validation.warnings]" :key="i" @click="locate(issue)">{{ issue.step_id ? `${issue.step_id} · ` : '' }}第 {{ issue.line }} 行：{{ issue.message }}</button>
    </div>
    <YamlEditor v-if="mode === 'yaml'" :model-value="source" @update:model-value="changeSource" />
    <div v-else class="workspace">
      <aside class="action-library">
        <h3>动作库</h3><p>点击添加，再拖动排序</p>
        <section v-for="group in groups" :key="group.key">
          <h4><img v-if="group.image" :src="group.image" alt="" />{{ group.label }}</h4>
          <button v-for="action in actions.filter(a => a.group === group.key)" :key="action.type + (action.position || '')" @click="add(action.type, action.position)">＋ {{ action.label }}</button>
        </section>
      </aside>
      <main class="step-canvas" aria-label="实验步骤">
        <div v-if="!steps.length" class="empty">从左侧添加第一个动作<br /><small>按从上到下的顺序执行</small></div>
        <article v-for="(step, index) in steps" :key="index" class="step-card" :class="{ selected: selected === index, disabled: step.enabled === false }" draggable="true" @dragstart="dragged = index" @dragend="dragged = null" @dragover.prevent @drop.prevent="drop(index)">
          <button class="step-select" @click="selected = index">
            <span class="number">{{ index + 1 }}</span><strong>{{ actionLabel(step.type, step.params) }}</strong><span v-if="step.enabled === false">已禁用</span>
            <small>{{ step.id || '缺少 ID' }} · {{ step.params?.device_id || '通用动作' }}</small>
            <small>{{ summary(step) }}</small>
            <small>{{ executionHint(step) }}</small>
            <small v-if="step.wait?.type && step.wait.type !== 'none'">{{ waitOptions.find(w => w.value === step.wait?.type)?.label || step.wait.type }} · {{ step.wait.seconds ?? step.wait.timeout ?? '' }}</small>
          </button>
          <div class="step-tools">
            <button :disabled="index === 0" @click="move(index, index - 1)" aria-label="上移步骤">↑</button>
            <button :disabled="index === steps.length - 1" @click="move(index, index + 1)" aria-label="下移步骤">↓</button>
            <button @click="duplicate(index)">复制</button>
            <button @click="set(['steps', index, 'enabled'], step.enabled === false)">{{ step.enabled === false ? '启用' : '禁用' }}</button>
            <button @click="remove(index)">删除</button>
          </div>
        </article>
      </main>
      <aside class="inspector" v-if="step">
        <h3>{{ actionLabel(step.type, step.params) }}</h3>
        <label>步骤 ID<input :value="step.id" @change="set(['steps', selected, 'id'], inputText($event))" /></label>
        <p class="hint">{{ executionHint(step) }}</p>
        <ParameterFields :fields="parameterFields(step)" :values="step.params || {}" :devices="devicesFor(step.type.split('.')[0]!)" @change="(k, v) => set(['steps', selected, 'params', k], v)" />
        <details v-if="step.type === 'syringe_pump.configure'" open>
          <summary>运动参数</summary>
          <ParameterFields :fields="settingsFields" :values="step.params?.settings || {}" :devices="[]" @change="(k, v) => set(['steps', selected, 'params', 'settings', k], v)" />
        </details>
        <details v-if="step.type.startsWith('microwave.configure_')" open>
          <summary>微波段参数</summary>
          <div class="segments-table"><table><thead><tr><th>参数</th><th v-for="(_, i) in segments" :key="i">段 {{ i + 1 }} <button @click="removeSegment(i)">删除</button></th></tr></thead>
            <tbody><tr v-for="field in segmentFields(step.type)" :key="field.key"><th>{{ field.label }}</th><td v-for="(segment, i) in segments" :key="i"><input type="number" :aria-label="`段 ${i + 1} ${field.label}`" :min="field.min" :max="field.max" :step="field.integer ? 1 : 'any'" :value="segment[field.key] ?? ''" @change="set(['steps', selected, 'params', 'segments', i, field.key], inputText($event) === '' ? undefined : Number(inputText($event)))" /></td></tr></tbody>
          </table></div>
          <el-button :disabled="segments.length >= 5" @click="addSegment">添加段</el-button>
          <p class="hint">未填字段保留引擎默认值；已有别名参数可在高级 YAML 中核对。</p>
        </details>
        <details open><summary>步骤后的等待</summary>
          <select :value="step.wait?.type || 'none'" @change="set(['steps', selected, 'wait', 'type'], inputText($event))"><option v-for="option in waitOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
          <ParameterFields :fields="waitFields(step.wait?.type)" :values="step.wait || {}" :devices="devicesFor(waitGroup(step.wait?.type))" @change="(k, v) => set(['steps', selected, 'wait', k], v)" />
        </details>
        <label>步骤失败时<select :value="step.on_error || 'stop'" @change="set(['steps', selected, 'on_error'], inputText($event))"><option value="stop">停止实验</option><option value="skip">跳过并继续</option></select></label>
        <el-button @click="openAdvanced(['steps', selected], '步骤完整 YAML（含额外字段）')">高级 YAML</el-button>
      </aside>
      <aside class="inspector" v-else><p>选择步骤以编辑参数</p></aside>
    </div>
    <el-dialog v-model="advancedVisible" :title="advancedTitle" width="min(800px, 94vw)" :close-on-click-modal="false" :before-close="closeAdvanced">
      <div v-if="advancedPath[0] === 'metadata'" class="metadata-fields"><label v-for="key in metadataKeys" :key="key">{{ key }}<input :value="advancedObject[key] ?? ''" @change="updateMetadata(key, inputText($event))" /></label></div>
      <YamlEditor :model-value="advancedSource" @update:model-value="advancedSource = $event" />
      <p v-if="advancedError" class="error">{{ advancedError }}</p>
      <template #footer><el-button @click="closeAdvanced(() => advancedVisible = false)">取消</el-button><el-button type="primary" @click="applyAdvanced">应用</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, isAlias, isMap, parseDocument, visit, type Node } from 'yaml'
import { editorApi, type Issue, type Validation } from '../api/experimentEditor'
import { devicesApi } from '../api/devices'
import { actions, groups, actionLabel, parameterFields, settingsFields, segmentFields, waitFields, waitOptions, fieldErrors, executionHint } from '../experiment/catalog'
import { duplicateStep, editSource, emptySource, inspectSource, moveStep, setValue, stepsFrom, uniqueId, type Path, type Step } from '../experiment/document'
import YamlEditor from '../components/experiment/YamlEditor.vue'
import ParameterFields from '../components/experiment/ParameterFields.vue'

const route = useRoute(), router = useRouter()
const source = ref(emptySource), baseline = ref(emptySource), filename = ref(''), loadedFilename = ref(''), revision = ref<string | null>(null)
const loading = ref(false), saving = ref(false), validating = ref(false), fileError = ref('')
const mode = ref<'graph' | 'yaml'>('graph'), selected = ref(0), dragged = ref<number | null>(null)
const history = ref([emptySource]), cursor = ref(0), validation = ref<Validation | null>(null)
const registry = ref<Record<string, Record<string, any>>>({}), devicesLoaded = ref(false)
const fileInput = ref<HTMLInputElement>()
const inspection = computed(() => inspectSource(source.value))
const definition = ref<Record<string, any>>({ steps: [] })
watch(source, () => {
  validation.value = null
  if (inspection.value.editable) definition.value = inspection.value.doc!.toJS()
  else mode.value = 'yaml'
}, { immediate: true })
const steps = computed<Step[]>(() => definition.value.steps ?? [])
const step = computed(() => steps.value[selected.value])
const segments = computed<Record<string, any>[]>(() => Array.isArray(step.value?.params?.segments) ? step.value!.params!.segments : [])
const dirty = computed(() => source.value !== baseline.value || filename.value !== loadedFilename.value)
const inputText = (event: Event) => (event.target as HTMLInputElement).value
function changeSource(value: string) {
  if (value === source.value) return
  history.value.splice(cursor.value + 1)
  history.value.push(value)
  cursor.value = history.value.length - 1
  source.value = value
}
function undo() { if (cursor.value > 0) source.value = history.value[--cursor.value]! }
function redo() { if (cursor.value < history.value.length - 1) source.value = history.value[++cursor.value]! }
function mutate(change: (doc: Document) => void) {
  try { changeSource(editSource(source.value, change)) } catch (e) { ElMessage.error(String(e)) }
}
function set(path: Path, value: unknown) { mutate(doc => setValue(doc, path, value)) }
function add(type: string, position?: string) {
  mutate(doc => doc.addIn(['steps'], { id: uniqueId(doc, type), type, params: position ? { position } : {}, enabled: true, on_error: 'stop' }))
  selected.value = stepsFrom(inspection.value.doc).length - 1
}
function move(from: number, to: number) { mutate(doc => moveStep(doc, from, to)); selected.value = to }
function drop(to: number) { if (dragged.value !== null) move(dragged.value, to); dragged.value = null }
function duplicate(index: number) { mutate(doc => duplicateStep(doc, index)); selected.value = index + 1 }
function remove(index: number) { mutate(doc => doc.deleteIn(['steps', index])); selected.value = Math.max(0, index - 1) }
function addSegment() {
  const used = new Set(segments.value.map(s => s.segment))
  const number = [1, 2, 3, 4, 5].find(n => !used.has(n))
  mutate(doc => {
    const path: Path = ['steps', selected.value, 'params', 'segments']
    if (!doc.hasIn(path)) doc.setIn(path, [])
    doc.addIn(path, { segment: number })
  })
}
function removeSegment(index: number) { mutate(doc => doc.deleteIn(['steps', selected.value, 'params', 'segments', index])) }
function devicesFor(group: string) {
  const key = groups.find(g => g.key === group)?.devices
  return Object.entries(registry.value[key || ''] || {}).map(([value, d]) => ({ value, label: `${d.name || value} · ${value}${d.connected ? '' : '（离线 / 未连接）'}` }))
}
function waitGroup(type?: string) {
  return type === 'temperature_reached' ? 'heater' : type?.startsWith('microwave') ? 'microwave' : type?.startsWith('syringe') ? 'syringe_pump' : type === 'pump_complete' ? 'pump' : ''
}
function summary(item: Step) {
  return parameterFields(item).filter(f => !['device_id', 'confirm', 'program'].includes(f.key) && item.params?.[f.key] != null).slice(0, 4).map(f => `${f.label.split('（')[0]} ${item.params![f.key]}`).join(' · ')
}
const localErrors = computed(() => {
  if (!inspection.value.editable) return []
  const ids = new Set<string>()
  return steps.value.flatMap((s, i) => {
    const errors = fieldErrors(parameterFields(s), s.params || {}).concat(fieldErrors(waitFields(s.wait?.type), s.wait || {}))
    if (typeof s.id !== 'string' || !s.id.trim() || ids.has(s.id)) errors.push('步骤 ID 为空或重复')
    ids.add(s.id)
    if (!actions.some(a => a.type === s.type)) errors.push('不支持的实验动作；请在 YAML 中修正')
    if (s.type === 'syringe_pump.configure') errors.push(...fieldErrors(settingsFields, s.params?.settings || {}))
    if (s.type.startsWith('microwave.configure_')) {
      if (!Array.isArray(s.params?.segments) || !s.params.segments.length) errors.push('至少需要一个微波段')
      else for (const seg of s.params.segments) errors.push(...fieldErrors(segmentFields(s.type), seg))
    }
    if (devicesLoaded.value) {
      if (s.params?.device_id && !devicesFor(s.type.split('.')[0]!).some(d => d.value === s.params!.device_id)) errors.push(`未知设备 ${s.params.device_id}`)
      if (waitGroup(s.wait?.type) && s.wait?.device_id && !devicesFor(waitGroup(s.wait.type)).some(d => d.value === s.wait!.device_id)) errors.push(`等待引用未知设备 ${s.wait.device_id}`)
    }
    return errors.map(e => `步骤 ${i + 1}：${e}`)
  })
})
function message(error: any) { return typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message || '请求失败' }
async function validate() {
  const text = source.value
  validating.value = true
  try { const result = (await editorApi.validate(text)).data; if (source.value === text) validation.value = result; return result }
  catch (e) { ElMessage.error(message(e)) }
  finally { validating.value = false }
}
async function save(name: string) {
  if (!name || !/^[^\\/:<>"|?*\x00-\x1f]+\.ya?ml$/.test(name) || name.includes('..')) { ElMessage.error('请输入普通 .yaml 或 .yml 文件名'); return }
  saving.value = true; fileError.value = ''
  const text = source.value
  try {
    const result = (await editorApi.save(name, text, name === loadedFilename.value ? revision.value : null)).data
    loadedFilename.value = name; filename.value = name; revision.value = result.revision; baseline.value = text
    ElMessage.success('已保存。返回实验页后可选择并明确启动。')
  } catch (e: any) {
    if (e.response?.data?.detail?.errors && source.value === text) validation.value = e.response.data.detail
    else fileError.value = message(e)
  } finally { saving.value = false }
}
async function saveAs() {
  try {
    const result = await ElMessageBox.prompt('输入新的 YAML 文件名；不会覆盖同名文件。', '另存为', { inputValue: filename.value.replace(/\.ya?ml$/, '-copy.yaml') })
    if (result.value === loadedFilename.value) { ElMessage.error('另存为需要不同的文件名'); return }
    await save(result.value)
  } catch { /* cancelled */ }
}
async function discard(messageText = '存在未保存修改，确定放弃吗？') {
  if (!dirty.value && !(advancedVisible.value && advancedSource.value !== advancedBaseline.value)) return true
  try { await ElMessageBox.confirm(messageText, '未保存修改', { type: 'warning' }); return true } catch { return false }
}
async function load(name: string) {
  loading.value = true; fileError.value = ''
  try {
    const result = (await editorApi.read(name)).data
    source.value = result.content; baseline.value = result.content; history.value = [result.content]; cursor.value = 0
    filename.value = name; loadedFilename.value = name; revision.value = result.revision; selected.value = 0
  } catch (e) { fileError.value = message(e) }
  finally { loading.value = false }
}
async function reload() { if (await discard()) await load(loadedFilename.value) }
async function importFile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]; input.value = ''
  if (!file || !await discard()) return
  if (file.size > 1_000_000) { ElMessage.error('文件不能超过 1 MB'); return }
  try {
    const text = await file.text()
    changeSource(text); filename.value = file.name; loadedFilename.value = ''; revision.value = null; baseline.value = emptySource; selected.value = 0
  } catch (e) { ElMessage.error(String(e)) }
}
function download() {
  const url = URL.createObjectURL(new Blob([source.value], { type: 'text/yaml;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = filename.value || 'experiment.yaml'; a.click(); URL.revokeObjectURL(url)
}
function locate(issue: Issue) {
  const index = issue.path[0] === 'steps' ? issue.path[1] : steps.value.findIndex(s => s.id === issue.step_id)
  if (typeof index === 'number' && index >= 0 && inspection.value.editable) { selected.value = index; mode.value = 'graph' }
  else mode.value = 'yaml'
}
const advancedVisible = ref(false), advancedSource = ref(''), advancedBaseline = ref(''), advancedError = ref(''), advancedTitle = ref(''), advancedPath = ref<Path>([])
const metadataKeys = ['material_system', 'batch_id', 'condition_id', 'sample_index', 'operator', 'recipe_version']
const advancedObject = computed(() => { try { const d = parseDocument(advancedSource.value); return d.errors.length ? {} : d.toJS() || {} } catch { return {} } })
function openAdvanced(path: Path, title: string) {
  const node = inspection.value.doc!.getIn(path, true)
  advancedSource.value = node ? String(node) : '{}\n'
  // String(YAMLMap) omits source comments; stringify a cloned document node instead.
  const doc = new Document({}); if (isMap(node)) doc.contents = node.clone() as Node
  advancedSource.value = doc.toString(); advancedBaseline.value = advancedSource.value
  advancedPath.value = path; advancedTitle.value = title; advancedError.value = ''; advancedVisible.value = true
}
function updateMetadata(key: string, value: string) {
  try {
    const doc = parseDocument(advancedSource.value)
    if (doc.errors.length || !isMap(doc.contents)) throw new Error('请先修复下方 YAML')
    setValue(doc, [key], key === 'sample_index' && value !== '' && /^\d+$/.test(value) ? Number(value) : value)
    advancedSource.value = doc.toString()
  } catch (e) { advancedError.value = String(e) }
}
function applyAdvanced() {
  try {
    const doc = parseDocument(advancedSource.value, { version: '1.1' })
    if (doc.errors.length || !isMap(doc.contents)) throw new Error(doc.errors[0]?.message || '需要 YAML 对象')
    visit(doc, (_, node) => { if (isAlias(node) || node && typeof node === 'object' && ('anchor' in node && node.anchor || 'tag' in node && node.tag) || isMap(node) && node.items.some(p => String(p.key) === '<<' || (p.key && typeof p.key === 'object' && 'value' in p.key && typeof p.key.value === 'symbol'))) throw new Error('高级表单不支持锚点、合并键或标签，请改用完整 YAML 模式。') })
    if (advancedSource.value !== advancedBaseline.value) mutate(current => current.setIn(advancedPath.value, doc.contents!.clone()))
    advancedVisible.value = false
  } catch (e) { advancedError.value = String(e) }
}
async function closeAdvanced(done: () => void) {
  if (advancedSource.value !== advancedBaseline.value) {
    try { await ElMessageBox.confirm('放弃尚未应用的 YAML 修改？', '未应用修改') } catch { return }
  }
  done()
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || advancedVisible.value && advancedSource.value !== advancedBaseline.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(async () => !saving.value && !loading.value && await discard())
onBeforeRouteUpdate(async to => {
  if (saving.value || loading.value || !await discard()) return false
  if (typeof to.query.filename === 'string') await load(to.query.filename)
  return true
})
onMounted(async () => {
  window.addEventListener('beforeunload', beforeUnload)
  if (typeof route.query.filename === 'string') await load(route.query.filename)
  try { registry.value = (await devicesApi.list()).data; devicesLoaded.value = true }
  catch { ElMessage.warning('设备配置列表读取失败，可继续编辑 YAML；设备选项暂不可用') }
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<style scoped>
.experiment-editor { color: #294357; min-width: 0; }
h2, h3 { margin: 0 0 10px; } h4 { margin: 14px 0 8px; display: flex; align-items: center; gap: 8px; }
.editor-top, .tools, .mode-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; justify-content: space-between; }
.editor-top { margin-bottom: 16px; } .editor-top span, .hint, .mode-bar > span { color: #60788f; font-size: 12px; }
.tools { justify-content: flex-start; } .tools :deep(.el-button + .el-button) { margin-left: 0; }
.document-heading { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin: 16px 0; }
.document-heading .description { flex: 1; min-width: 200px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
input, select { padding: 8px; min-width: 0; box-sizing: border-box; border: 1px solid #b9cddd; border-radius: 5px; background: #fff; color: #243a4b; max-width: 100%; }
button { cursor: pointer; } button:disabled { cursor: default; opacity: .5; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid #267bbb; outline-offset: 2px; }
.mode-bar { margin: 14px 0; }.mode-bar button { padding: 9px 16px; border: 1px solid #b9cddd; background: #fff; color: #315775; }.mode-bar button[aria-selected=true] { background: #276c9c; color: white; }
.workspace { display: grid; grid-template-columns: 190px minmax(220px, 1fr) minmax(290px, 390px); gap: 14px; align-items: start; }
.action-library, .inspector { padding: 16px; background: #fff; border: 1px solid #d6e3ec; border-radius: 8px; min-width: 0; }
.action-library img { width: 40px; height: 34px; object-fit: contain; }.action-library p { font-size: 12px; }
.action-library section > button { display: block; width: 100%; text-align: left; border: 0; border-radius: 4px; background: #eef5fa; padding: 9px 7px; margin: 4px 0; color: #315775; }.action-library section > button:hover { background: #daebf9; }
.step-canvas { min-width: 0; }.empty { padding: 80px 12px; text-align: center; border: 1px dashed #9eb8cf; border-radius: 8px; line-height: 2; }
.step-card { background: white; border: 1px solid #c9dbe8; border-radius: 8px; margin-bottom: 18px; overflow: hidden; }.step-card.selected { border: 2px solid #3b86bf; }.step-card.disabled { opacity: .65; }
.step-select { width: 100%; border: 0; background: transparent; text-align: left; padding: 14px; color: inherit; }.step-select small { display: block; margin-top: 7px; overflow-wrap: anywhere; color: #536f84; }.number { display: inline-block; padding: 3px 7px; border-radius: 4px; background: #e1edf7; margin-right: 8px; }
.step-tools { display: flex; flex-wrap: wrap; gap: 5px; padding: 8px 12px; border-top: 1px solid #edf2f6; }.step-tools button { border: 0; padding: 5px 8px; background: #eef5fa; color: #315775; border-radius: 4px; }
.inspector > * { margin-bottom: 14px; }.inspector details { border-top: 1px solid #d6e3ec; padding-top: 12px; }.inspector summary { cursor: pointer; margin-bottom: 10px; }.inspector select { width: 100%; margin-bottom: 10px; }
.segments-table { overflow-x: auto; margin-bottom: 10px; }.segments-table th { min-width: 90px; font-size: 12px; text-align: left; }.segments-table input { width: 95px; }.segments-table button { border: 0; color: #ac3948; background: transparent; }
.issues { padding: 12px; margin-bottom: 12px; border: 1px solid #e2bf8d; border-radius: 6px; background: #fff8ec; font-size: 13px; }.issues p { margin: 5px 0; }.issues button { display: block; border: 0; background: transparent; text-align: left; color: #875212; padding: 5px 0; }.issues.valid { background: #eff8f1; border-color: #aacbb3; }
.metadata-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }.error { color: #b92e42; }
@media (max-width: 1100px) { .workspace { grid-template-columns: 160px minmax(180px, 1fr); }.inspector { grid-column: 1 / -1; } }
@media (max-width: 650px) { .workspace { grid-template-columns: minmax(0, 1fr); }.action-library section > button { display: inline-block; width: auto; margin: 4px; }.document-heading { align-items: stretch; }.document-heading label { width: 100%; }.metadata-fields { grid-template-columns: 1fr; } }
</style>
