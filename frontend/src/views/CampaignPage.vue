<template>
  <div class="campaign-page">
    <el-row :gutter="20">
      <el-col :xs="24" :md="7">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>Campaign</span>
              <div class="card-header-actions">
                <el-button size="small" @click="loadCampaigns" :loading="loading">刷新</el-button>
                <el-button size="small" type="primary" @click="createVisible = true">新建</el-button>
              </div>
            </div>
          </template>

          <div v-if="campaigns.length === 0" class="empty-state">暂无 Campaign</div>
          <button
            v-for="(campaign, index) in campaigns"
            :key="campaign.campaign_id"
            type="button"
            class="campaign-item"
            :class="{ active: selectedCampaign?.campaign_id === campaign.campaign_id }"
            @click="previewCampaign = campaign"
          >
            <span class="campaign-number">{{ index + 1 }}</span>
            <span class="campaign-title">{{ campaign.name }}</span>
          </button>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="17">
        <div v-if="!selectedCampaign" class="empty-panel">
          选择或创建一个 Campaign 后开始批次优化
        </div>

        <template v-else>
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">
                <span>{{ selectedCampaign.name }}</span>
                <el-tag type="info">{{ selectedCampaign.objective_metric }}</el-tag>
              </div>
            </template>

            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="Campaign ID">{{ selectedCampaign.campaign_id }}</el-descriptions-item>
              <el-descriptions-item label="材料体系">{{ selectedCampaign.material_system || '-' }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ selectedCampaign.status }}</el-descriptions-item>
              <el-descriptions-item label="参数名" :span="3">
                <el-tag
                  v-for="name in selectedCampaign.parameter_names"
                  :key="name"
                  size="small"
                  style="margin-right: 6px"
                >
                  {{ name }}
                </el-tag>
                <span v-if="selectedCampaign.parameter_names.length === 0" class="muted">未设置</span>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-row :gutter="20" style="margin-top: 20px">
            <el-col :span="10">
              <el-card shadow="hover">
                <template #header><span>ManualPlanner</span></template>
                <el-input
                  v-model="manualParametersText"
                  type="textarea"
                  :rows="8"
                  spellcheck="false"
                  placeholder='[{"temperature_c": 120, "flow_a": 0.4}]'
                />
                <div class="actions-row">
                  <el-button @click="fillExample">填入示例</el-button>
                  <el-button type="primary" @click="createRecommendation" :loading="recommending">
                    生成 Trial
                  </el-button>
                </div>
              </el-card>
            </el-col>

            <el-col :span="14">
              <el-card shadow="hover">
                <template #header>
                  <div class="card-header">
                    <span>离线表征录入</span>
                    <el-button size="small" @click="loadCampaignData">刷新</el-button>
                  </div>
                </template>
                <el-form :model="charForm" label-width="100px">
                  <el-form-item label="Trial">
                    <el-select v-model="charForm.trial_id" placeholder="选择 Trial" style="width: 100%">
                      <el-option
                        v-for="trial in trials"
                        :key="trial.trial_id"
                        :label="trial.trial_id"
                        :value="trial.trial_id"
                      />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="类型">
                    <el-input v-model="charForm.characterization_type" placeholder="PL" />
                  </el-form-item>
                  <el-form-item :label="selectedCampaign.objective_metric">
                    <el-input-number v-model="objectiveValue" :min="0" style="width: 100%" />
                  </el-form-item>
                  <el-form-item label="额外指标">
                    <el-input
                      v-model="extraMetricsText"
                      type="textarea"
                      :rows="3"
                      spellcheck="false"
                      placeholder='{"peak_nm": 516.4, "fwhm_nm": 21.5}'
                    />
                  </el-form-item>
                  <el-form-item label="Sample ID">
                    <el-input v-model="charForm.sample_id" placeholder="CSPB_20260608_B01_S001" />
                  </el-form-item>
                  <el-form-item label="原始文件">
                    <el-input v-model="charForm.raw_file_path" placeholder="data/characterization/pl/S001.csv" />
                  </el-form-item>
                  <el-form-item>
                    <el-button type="primary" @click="saveCharacterization" :loading="savingChar">
                      保存表征结果
                    </el-button>
                  </el-form-item>
                </el-form>
              </el-card>
            </el-col>
          </el-row>

          <el-card shadow="hover" style="margin-top: 20px">
            <template #header><span>Trial 队列</span></template>
            <el-table :data="trials" stripe style="width: 100%">
              <el-table-column prop="trial_id" label="Trial ID" width="230" />
              <el-table-column label="参数">
                <template #default="{ row }">
                  <code>{{ formatJson(row.parameters) }}</code>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="190">
                <template #default="{ row }">
                  <el-select
                    v-model="row.status"
                    size="small"
                    @change="() => updateTrialStatus(row, row.status)"
                  >
                    <el-option v-for="status in trialStatuses" :key="status" :label="status" :value="status" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="Run / Sample" width="260">
                <template #default="{ row }">
                  <el-input
                    v-model="row.run_id"
                    size="small"
                    placeholder="run_id"
                    style="margin-bottom: 6px"
                    @change="() => updateTrialLinks(row)"
                  />
                  <el-input
                    v-model="row.sample_id"
                    size="small"
                    placeholder="sample_id"
                    @change="() => updateTrialLinks(row)"
                  />
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <el-card shadow="hover" style="margin-top: 20px">
            <template #header><span>表征结果</span></template>
            <el-table :data="characterizations" stripe style="width: 100%">
              <el-table-column prop="trial_id" label="Trial ID" width="230" />
              <el-table-column prop="sample_id" label="Sample ID" width="180" />
              <el-table-column prop="characterization_type" label="类型" width="100" />
              <el-table-column label="指标">
                <template #default="{ row }">
                  <code>{{ formatJson(row.metrics) }}</code>
                </template>
              </el-table-column>
              <el-table-column prop="raw_file_path" label="原始文件" />
            </el-table>
          </el-card>
        </template>
      </el-col>
    </el-row>

    <el-dialog v-model="createVisible" title="新建 Campaign" width="min(560px, 92vw)" top="5vh">
      <el-form :model="campaignForm" label-position="top" class="create-form">
        <el-form-item label="名称"><el-input v-model="campaignForm.name" placeholder="CsPbBr3 PL optimization" /></el-form-item>
        <el-form-item label="材料体系"><el-input v-model="campaignForm.material_system" placeholder="CsPbBr3" /></el-form-item>
        <el-form-item label="主目标指标"><el-input v-model="campaignForm.objective_metric" placeholder="pl_intensity" /></el-form-item>
        <el-form-item label="参数名"><el-input v-model="parameterNamesText" placeholder="temperature_c, flow_a, flow_b" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="createCampaign" :loading="creating">创建 Campaign</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="Boolean(previewCampaign)" @close="previewCampaign = null" title="Campaign 详情" width="min(680px, 92vw)" top="5vh">
      <template v-if="previewCampaign">
        <h2 class="preview-title">{{ previewCampaign.name }}</h2>
        <el-descriptions :column="1" border size="small" class="campaign-preview-details">
          <el-descriptions-item label="Campaign ID">{{ previewCampaign.campaign_id }}</el-descriptions-item>
          <el-descriptions-item label="材料体系">{{ previewCampaign.material_system || '-' }}</el-descriptions-item>
          <el-descriptions-item label="主目标指标">{{ previewCampaign.objective_metric }}</el-descriptions-item>
          <el-descriptions-item label="参数名">{{ previewCampaign.parameter_names.join(', ') || '未设置' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ previewCampaign.status }}</el-descriptions-item>
          <el-descriptions-item v-if="previewCampaign.notes" label="备注">{{ previewCampaign.notes }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ previewCampaign.created_at }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="previewCampaign = null">关闭</el-button>
        <el-button type="primary" @click="enterCampaign">进入 Campaign</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { campaignsApi, type Campaign, type CharacterizationResult, type Trial } from '../api/campaigns'

const campaigns = ref<Campaign[]>([])
const createVisible = ref(false)
const previewCampaign = ref<Campaign | null>(null)
const selectedCampaign = ref<Campaign | null>(null)
const trials = ref<Trial[]>([])
const characterizations = ref<CharacterizationResult[]>([])
const loading = ref(false)
const creating = ref(false)
const recommending = ref(false)
const savingChar = ref(false)
const parameterNamesText = ref('temperature_c, flow_a, flow_b')
const manualParametersText = ref('')
const extraMetricsText = ref('')
const objectiveValue = ref(0)

const trialStatuses = [
  'planned',
  'ready_to_run',
  'running',
  'synthesized',
  'waiting_characterization',
  'characterized',
  'accepted_for_planner',
  'excluded',
  'failed',
]

const campaignForm = reactive({
  name: '',
  material_system: 'CsPbBr3',
  objective_metric: 'pl_intensity',
})

const charForm = reactive({
  trial_id: '',
  characterization_type: 'PL',
  sample_id: '',
  raw_file_path: '',
})

const parameterNames = computed(() =>
  parameterNamesText.value
    .split(',')
    .map(item => item.trim())
    .filter(Boolean),
)

function formatJson(value: unknown): string {
  return JSON.stringify(value)
}

async function loadCampaigns() {
  loading.value = true
  try {
    campaigns.value = (await campaignsApi.list()).data
    if (selectedCampaign.value) {
      const match = campaigns.value.find(item => item.campaign_id === selectedCampaign.value?.campaign_id)
      selectedCampaign.value = match || null
    }
  } catch (e) {
    ElMessage.error(`加载 Campaign 失败: ${readError(e)}`)
  } finally {
    loading.value = false
  }
}

async function loadCampaignData() {
  if (!selectedCampaign.value) return
  const campaignId = selectedCampaign.value.campaign_id
  try {
    const [trialResp, charResp] = await Promise.all([
      campaignsApi.listTrials(campaignId),
      campaignsApi.listCharacterizations(campaignId),
    ])
    trials.value = trialResp.data
    characterizations.value = charResp.data
  } catch (e) {
    ElMessage.error(`加载 Campaign 数据失败: ${readError(e)}`)
  }
}

async function createCampaign() {
  if (!campaignForm.name.trim()) {
    ElMessage.warning('请输入 Campaign 名称')
    return
  }
  creating.value = true
  try {
    const resp = await campaignsApi.create({
      name: campaignForm.name,
      material_system: campaignForm.material_system,
      objective_metric: campaignForm.objective_metric,
      parameter_names: parameterNames.value,
    })
    campaigns.value.unshift(resp.data)
    await selectCampaign(resp.data)
    createVisible.value = false
    ElMessage.success('Campaign 已创建')
  } catch (e) {
    ElMessage.error(`创建失败: ${readError(e)}`)
  } finally {
    creating.value = false
  }
}

async function selectCampaign(campaign: Campaign) {
  selectedCampaign.value = campaign
  charForm.trial_id = ''
  await loadCampaignData()
}

async function enterCampaign() {
  if (!previewCampaign.value) return
  const campaign = previewCampaign.value
  previewCampaign.value = null
  await selectCampaign(campaign)
}

function fillExample() {
  const names = selectedCampaign.value?.parameter_names.length
    ? selectedCampaign.value.parameter_names
    : ['temperature_c', 'flow_a']
  const first = Object.fromEntries(names.map((name, index) => [name, index === 0 ? 120 : 0.4]))
  const second = Object.fromEntries(names.map((name, index) => [name, index === 0 ? 140 : 0.5]))
  manualParametersText.value = JSON.stringify([first, second], null, 2)
}

async function createRecommendation() {
  if (!selectedCampaign.value) return
  let parametersBatch: Record<string, unknown>[]
  try {
    const parsed = JSON.parse(manualParametersText.value)
    if (!Array.isArray(parsed)) throw new Error('必须是参数对象数组')
    parametersBatch = parsed
  } catch (e) {
    ElMessage.error(`参数 JSON 无效: ${readError(e)}`)
    return
  }
  recommending.value = true
  try {
    await campaignsApi.recommendManual(selectedCampaign.value.campaign_id, parametersBatch)
    await loadCampaignData()
    ElMessage.success('Trial 已生成')
  } catch (e) {
    ElMessage.error(`生成失败: ${readError(e)}`)
  } finally {
    recommending.value = false
  }
}

async function updateTrialStatus(trial: Trial, status: string) {
  if (!selectedCampaign.value) return
  try {
    await campaignsApi.updateTrial(selectedCampaign.value.campaign_id, trial.trial_id, { status })
    ElMessage.success('状态已更新')
  } catch (e) {
    ElMessage.error(`状态更新失败: ${readError(e)}`)
    await loadCampaignData()
  }
}

async function updateTrialLinks(trial: Trial) {
  if (!selectedCampaign.value) return
  try {
    await campaignsApi.updateTrial(selectedCampaign.value.campaign_id, trial.trial_id, {
      run_id: trial.run_id,
      sample_id: trial.sample_id,
    })
  } catch (e) {
    ElMessage.error(`关联更新失败: ${readError(e)}`)
    await loadCampaignData()
  }
}

async function saveCharacterization() {
  if (!selectedCampaign.value || !charForm.trial_id) {
    ElMessage.warning('请选择 Trial')
    return
  }
  let metrics: Record<string, unknown> = {
    [selectedCampaign.value.objective_metric]: objectiveValue.value,
  }
  if (extraMetricsText.value.trim()) {
    try {
      metrics = { ...metrics, ...JSON.parse(extraMetricsText.value) }
    } catch (e) {
      ElMessage.error(`额外指标 JSON 无效: ${readError(e)}`)
      return
    }
  }
  savingChar.value = true
  try {
    await campaignsApi.createCharacterization(selectedCampaign.value.campaign_id, {
      trial_id: charForm.trial_id,
      characterization_type: charForm.characterization_type,
      metrics,
      sample_id: charForm.sample_id,
      raw_file_path: charForm.raw_file_path,
    })
    await loadCampaignData()
    ElMessage.success('表征结果已保存')
  } catch (e) {
    ElMessage.error(`保存失败: ${readError(e)}`)
  } finally {
    savingChar.value = false
  }
}

function readError(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

onMounted(loadCampaigns)
</script>

<style scoped>
.campaign-page {
  padding: 0;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.card-header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.card-header-actions :deep(.el-button + .el-button) { margin-left: 0; }
.create-form {
  margin-bottom: 4px;
}
.campaign-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  border: 0;
  border-bottom: 1px solid #ebeef5;
  padding: 12px;
  cursor: pointer;
  background: transparent;
  text-align: left;
  font: inherit;
  color: inherit;
}
.campaign-item:hover { background: var(--el-fill-color-light); }
.campaign-item:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.campaign-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}
.campaign-title {
  min-width: 0;
  font-weight: 600;
  color: #303133;
  overflow-wrap: anywhere;
}
.campaign-number { flex: 0 0 24px; color: var(--el-text-color-secondary); font-size: 13px; }
.preview-title { margin: 0 0 16px; font-size: 20px; line-height: 1.5; overflow-wrap: anywhere; }
.campaign-page :deep(.campaign-preview-details .el-descriptions__content) { overflow-wrap: anywhere; }
.empty-state,
.empty-panel {
  color: #909399;
  text-align: center;
  padding: 32px;
}
.empty-panel {
  background: #fff;
  border-radius: 6px;
}
.actions-row {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
}
.muted {
  color: #909399;
}
code {
  white-space: normal;
  word-break: break-all;
  color: #303133;
}
@media (max-width: 991px) { .campaign-page > .el-row { row-gap: 16px; } }
</style>
