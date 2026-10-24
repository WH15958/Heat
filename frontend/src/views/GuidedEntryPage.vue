<template>
  <BatchExperimentPage v-if="setup" />
  <div v-else class="guided-entry">
    <header><div><h2>引导式实验</h2><p>以命名批次保存参数、预充与各组实验记录。</p></div><el-button v-if="history" @click="router.push('/experiment/batch')">返回实验入口</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <section v-if="attention" class="attention"><h3>有正在执行或需要处理的批次</h3><p>{{ current.experiment_name || current.request?.experiment_name || current.batch_id }} · {{ label(current.state) }}</p><p>请先查看进度或处理恢复事项，再开始新批次。本机草稿会保留。</p><el-button type="primary" @click="openCurrent">查看当前批次 / 恢复事项</el-button></section>
    <div v-if="!history" class="entry-grid">
      <section><span class="entry-icon">＋</span><h3>新建实验</h3><p>填写实验条件，确认预充、收集和清洗参数，生成本批各组实验。</p><el-button type="primary" :disabled="loading||!!error||attention" @click="create">新建实验</el-button><el-button v-if="hasDraft" :disabled="loading||!!error||attention" @click="continueDraft">继续填写草稿</el-button><small v-if="hasDraft">本机有未完成草稿，新建前会询问是否替换。</small></section>
      <section><span class="entry-icon">▤</span><h3>历史实验</h3><p>按批次查看完整参数、预充记录、各组结果与曲线，并导出整批记录。</p><el-button @click="router.push({path:'/experiment/batch',query:{view:'history'}})">查看历史实验</el-button></section>
    </div>
    <template v-else>
      <div class="history-heading"><h3>历史实验 · {{ records.length }} 批</h3><el-button :loading="loading" @click="load">刷新记录</el-button></div>
      <p v-if="!loading&&!records.length&&!error">暂无已保存的批次。</p>
      <div class="history-layout">
        <nav aria-label="历史批次"><button v-for="record in records" :key="record.batch_id" :class="{selected:detail?.batch_id===record.batch_id}" @click="selectBatch(record.batch_id)"><strong>{{ record.experiment_name || record.request?.experiment_name || '未命名实验' }}</strong><span>{{ label(record.state) }} · {{ record.total_groups || 0 }} 组</span><small>{{ date(record.created_at) }}</small><small>{{ record.batch_id }}</small></button></nav>
        <section v-if="detail" class="batch-detail" :aria-busy="detailLoading">
          <h3>{{ detail.experiment_name || detail.request?.experiment_name || '未命名实验' }}</h3><p>{{ label(detail.state) }} · {{ detail.total_groups || 0 }} 组 · {{ date(detail.created_at) }}</p><small>{{ detail.batch_id }}</small>
          <el-alert v-if="detail.error" :title="detail.error" type="error" :closable="false" />
          <el-alert v-if="finalizationFailed" title="实验组已完成，收尾回零失败；已完成样品记录保留，请检查恢复事项。" type="warning" :closable="false" />
          <el-alert v-if="detail.persistence_status==='error'" title="批次保存失败，请检查记录恢复，不能视为完整归档。" type="error" :closable="false" />
          <el-alert v-if="detailError" :title="detailError" type="warning" :closable="false" />
          <div class="detail-actions"><el-button :loading="exporting" :disabled="detailLoading" @click="exportAll">导出整批记录</el-button><el-button @click="router.push({path:'/history',query:{batch_id:detail.batch_id}})">查看记录详情与曲线</el-button></div>
          <h4>本批预充</h4><p>{{ label(detail.priming?.status || 'pending') }} · A {{ detail.priming?.completed_cycles?.[0] || 0 }} 次 / B {{ detail.priming?.completed_cycles?.[1] || 0 }} 次</p><p>记录编号：{{ detail.priming?.run_id || '未生成（可查看下方已关联记录）' }}</p>
          <h4>各组实验</h4><div class="table-scroll"><table><thead><tr><th>组号</th><th>状态</th><th>产物瓶</th><th>收取状态</th><th>样品编号</th><th>记录编号</th></tr></thead><tbody><tr v-for="g in groups" :key="g.index"><td>{{ g.index }}</td><td>{{ label(g.state) }}</td><td>{{ g.bottle_number==null ? '未记录' : turntableBottleLabel(g.bottle_number) }}</td><td>{{ collectionStatusLabel(g.collection_status) }}<p v-if="g.collection_error">{{ g.collection_error }}</p></td><td>{{ g.sample_id || '—' }}</td><td>{{ g.run_id || '尚未生成' }}</td></tr></tbody></table></div>
          <details v-if="detail.turntable"><summary>转盘与收尾记录</summary><p>最后确认瓶位：{{ turntableBottleLabel(detail.turntable.current_bottle) }} · 目标：{{ turntableBottleLabel(detail.turntable.target_bottle) }}</p><p>收尾：{{ label(detail.finalization?.status || 'pending') }} {{ detail.finalization?.error || '' }}</p><pre>{{ JSON.stringify(detail.turntable_events || [],null,2) }}</pre></details>
          <h4>已关联执行记录（含预充）</h4><p v-if="!related.length">尚未找到执行日志；批次参数与检查点仍保留。</p><ul><li v-for="run in related" :key="run.run_id">{{ run.experiment_name || run.run_id }} · {{ label(run.status) }} · {{ run.run_id }}</li></ul>
          <details><summary>完整批次参数</summary><pre>{{ JSON.stringify(detail.request, null, 2) }}</pre></details>
          <details><summary>预充及各组完整流程快照</summary><pre>{{ savedPlan ? JSON.stringify(savedPlan,null,2) : '流程快照未读取成功，请检查记录。' }}</pre></details>
        </section>
        <p v-else-if="!loading&&records.length">请选择一个批次查看。</p>
      </div>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessageBox } from 'element-plus'
import BatchExperimentPage from './BatchExperimentPage.vue'
import { batchExport, batchRunIds, collectionStatusLabel, turntableBottleLabel } from '../experiment/guidedProgress'
const route=useRoute(),router=useRouter()
const setup=computed(()=>route.query.new==='1'||route.query.resume==='1')
const history=computed(()=>route.query.view==='history')
const records=ref<any[]>([]),current=ref<any>({}),detail=ref<any>(null),savedPlan=ref<any>(null),related=ref<any[]>([])
const loading=ref(false),detailLoading=ref(false),exporting=ref(false),error=ref(''),detailError=ref(''),hasDraft=ref(false)
const attention=computed(()=>['running','paused'].includes(current.value.state)||!!(current.value.recovery_required||current.value.cleanup_pending||current.value.cleanup_required||current.value.persistence_status==='error'))
const groups=computed(()=>Array.from({length:detail.value?.total_groups||0},(_,i)=>detail.value.groups?.find((g:any)=>g.index===i+1)||{index:i+1,state:'pending'}))
const finalizationFailed=computed(()=>detail.value?.finalization?.status==='failed'&&groups.value.length>0&&groups.value.every((g:any)=>g.state==='completed'))
const labels:Record<string,string>={idle:'未开始',pending:'未执行',running:'运行中',paused:'暂停',completed:'已完成',failed:'失败',stopped:'已停止',interrupted:'中断待确认',ready:'准备就绪'}
const label=(state:string)=>labels[state]||state||'未知'
const date=(value:string)=>value?new Date(value).toLocaleString('zh-CN'):'时间未记录'
function checkDraft(){try{hasDraft.value=!!localStorage.getItem('heat.guided-draft.v1')}catch{hasDraft.value=false}}
function continueDraft(){void router.push({path:'/experiment/batch',query:{new:'1'}})}
function openCurrent(){void router.push({path:'/experiment/batch',query:{resume:'1'}})}
async function create(){
 if(loading.value||error.value||attention.value)return
 if(hasDraft.value){try{await ElMessageBox.confirm('将清除本机未完成草稿，开始空白实验。已执行批次记录不受影响。','替换草稿',{type:'warning',confirmButtonText:'新建空白实验',cancelButtonText:'保留草稿'})}catch{return}}
 try{localStorage.removeItem('heat.guided-draft.v1')}catch{error.value='无法清除本机草稿，请检查浏览器存储。';return}
 continueDraft()
}
let sequence=0
async function selectBatch(id:string){
 await router.replace({path:'/experiment/batch',query:{view:'history',batch_id:id}})
}
async function readDetail(id:string){
 const token=++sequence;detailLoading.value=true;detail.value=null;savedPlan.value=null;related.value=[];detailError.value=''
 try{
  const {data}=await axios.get(`/api/guided/${encodeURIComponent(id)}`)
  if(token!==sequence)return
  detail.value=data
  const results=await Promise.allSettled([axios.get(`/api/guided/${encodeURIComponent(id)}/plan`),axios.get('/api/experiments/history/runs')])
  if(token!==sequence)return
  const warnings:string[]=[]
  if(results[0].status==='fulfilled')savedPlan.value=results[0].value.data;else warnings.push('完整流程快照读取失败')
  if(results[1].status==='fulfilled'){
   const runs=results[1].value.data,ids=batchRunIds(data,runs)
   related.value=runs.filter((r:any)=>ids.includes(r.run_id))
   const missing=ids.filter((runId:string)=>!runs.some((r:any)=>r.run_id===runId))
   if(missing.length)warnings.push('部分执行日志缺失：'+missing.join('、'))
  }else warnings.push('执行日志列表读取失败')
  detailError.value=warnings.join('；')
 }catch{if(token===sequence)detailError.value='批次读取失败，请刷新记录。'}finally{if(token===sequence)detailLoading.value=false}
}
async function load(){
 loading.value=true;error.value='';checkDraft()
 try{
  const [active,list]=await Promise.all([axios.get('/api/guided/current'),axios.get('/api/guided/batches')])
  current.value=active.data;records.value=list.data
  if(history.value){const id=typeof route.query.batch_id==='string'?route.query.batch_id:records.value[0]?.batch_id;if(id)await readDetail(id)}
 }catch{error.value='批次列表或当前状态读取失败，请刷新后重试。'}finally{loading.value=false}
}
async function exportAll(){
 if(!detail.value||exporting.value)return
 exporting.value=true;detailError.value=''
 try{
  const content=await batchExport(detail.value,url=>axios.get(url))
  const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:'application/json'}))
  const link=document.createElement('a');link.href=url;link.download=`batch_${content.batch_id}.json`;link.click();URL.revokeObjectURL(url)
 }catch(e){detailError.value=(e as Error).message}finally{exporting.value=false}
}
watch(()=>[route.query.view,route.query.batch_id,setup.value],()=>{if(!setup.value)void load()})
onMounted(()=>{if(!setup.value)void load()})
onUnmounted(()=>{sequence++})
</script>
<style scoped>
.guided-entry{color:#294763;max-width:1400px;margin:auto}header,.history-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:24px}h2{font-size:28px;margin:0}p{line-height:1.8;color:#607a91}.entry-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin-top:28px}.entry-grid section,.batch-detail,.attention{background:white;border:1px solid #d7e6f4;border-radius:16px;padding:28px}.entry-icon{font-size:32px;color:#1688e8}.entry-grid small{display:block;margin-top:16px;color:#607a91}.attention{margin:20px 0;border-color:#e8b963}.history-heading{margin-top:24px}.history-layout{display:grid;grid-template-columns:minmax(220px,300px) minmax(0,1fr);gap:24px}.history-layout nav{display:flex;flex-direction:column;gap:12px}.history-layout nav button{text-align:left;border:1px solid #d7e6f4;border-radius:10px;padding:16px;background:white;color:#294763;cursor:pointer;display:flex;flex-direction:column;gap:8px;overflow-wrap:anywhere}.history-layout nav button.selected{border-color:#1688e8;background:#edf6ff}.batch-detail{min-width:0}.batch-detail>small{overflow-wrap:anywhere}.detail-actions{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px;text-align:left;border-bottom:1px solid #e3ebf3;overflow-wrap:anywhere}details{margin-top:20px}summary{cursor:pointer}pre{max-height:400px;overflow:auto;background:#f4f8fc;padding:16px;font-size:12px}li{font-size:13px;overflow-wrap:anywhere;margin:10px 0}@media(max-width:800px){.entry-grid,.history-layout{grid-template-columns:1fr}.entry-grid section,.batch-detail{padding:20px}}
</style>
