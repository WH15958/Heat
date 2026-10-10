<template>
  <div class="guided">
    <header><div><h2>{{ showProgress ? '实验进度' : '引导式实验' }}</h2><p>{{ showProgress ? '初始化与预充 → 前驱体加热与进料 → 微波反应 → 降温与收集 → 清洗 → 下一组' : '前驱体加热 → 进料 → 微波反应 → 降温与收集 → 清洗 → 预充与排气 → 批次确认' }}</p></div><div class="header-actions"><el-button v-if="batch.batch_id" @click="showProgress=!showProgress">{{ showProgress ? '查看参数' : '查看实验进度' }}</el-button><el-button @click="router.push('/experiment/editor')">自由编排</el-button></div></header>
    <nav v-if="!showProgress"><button v-for="(name,i) in stages" :key="name" :class="{active:stage===i}"  :disabled="i>stage" @click="goBack(i)"><b>{{ i+1 }}</b>{{ name }}</button></nav>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <section v-if="showProgress" class="run-panel" aria-label="实验进度">
      <div class="run-heading"><div><h3>{{ stateLabel }}</h3><p class="batch-id">批次 {{ batch.batch_id }}</p></div><div class="run-actions">
        <el-button v-if="batch.state==='running'&&!batch.pause_pending" :disabled="controlling" @click="controlBatch('pause')">暂停批次</el-button>
        <el-button v-if="(batch.state==='paused'||batch.pause_pending)&&batch.phase!=='ready'" :disabled="controlling" @click="controlBatch('resume')">{{ batch.pause_pending ? '取消暂停请求' : '继续批次' }}</el-button>
        <el-button v-if="activeRun||batch.cleanup_pending" type="danger" :disabled="controlling" @click="controlBatch('stop')">停止批次</el-button>
        <el-button v-if="batch.phase==='ready'" @click="showProgress=false;stage=6">前往批次确认</el-button>
      </div></div>
      <el-alert v-if="refreshError" :title="refreshError" type="warning" :closable="false" />
      <el-alert v-if="batch.pause_pending" title="已请求暂停：当前反应继续，停止微波后暂停；随后不收集、不清洗、不进入下一组。" type="warning" :closable="false" />
      <el-alert v-else-if="batch.state==='paused'&&batch.phase!=='ready'" :title="batch.phase==='priming'?'预充已暂停；已发出的注射泵动作完成后，等待继续，不发送下一步。':'实验已暂停，等待继续；前驱体加热器保持保温。'" type="info" :closable="false" />
      <el-alert v-if="batch.error" :title="batch.error" type="error" :closable="false" />
      <el-alert v-if="batch.persistence_status==='error'" title="记录保存失败，禁止继续运行" type="error" :closable="false" />
      <el-alert v-if="batch.state==='completed'&&batch.cleanup_pending" title="实验流程已结束，设备清理仍待确认。" type="warning" :closable="false" />
      <div v-if="batch.recovery_required" class="notice"><p>需要现场检查设备停止、残留和液路，解除恢复锁定后才能开始新批次。</p><el-button type="warning" :disabled="controlling" @click="acknowledgeInterrupted">现场已检查，解除恢复锁定</el-button></div>
      <div class="run-summary">
        <div><small>整批完成组数</small><strong>{{ completedGroups }} / {{ batch.total_groups || 0 }}</strong><progress :value="completedGroups" :max="batch.total_groups||1" aria-label="已完成实验组数"></progress></div>
        <div><small>当前实验组</small><strong>{{ batch.phase==='priming'||batch.phase==='ready' ? '批次准备' : `第 ${batch.current_group || 0} 组` }}</strong><span>{{ phaseLabel }}</span></div>
        <div><small>预充 / 当前组累计用时</small><strong>{{ elapsedLabel }}</strong><span>含暂停时间 · 每 2 秒更新 · {{ lastRefresh ? new Date(lastRefresh).toLocaleTimeString() : '等待状态' }}</span></div>
      </div>
      <div class="current-operation" role="status" aria-live="polite"><small>当前步骤</small><h3>{{ currentStepLabel }}</h3><p v-if="batch.progress?.total_steps">{{ batch.phase==='priming'?'批次准备':'当前组' }}步骤 {{ displayedStep }} / {{ batch.progress.total_steps }} · {{ currentDevice }}</p></div>
      <ol class="run-stages"><li v-for="(name,i) in executionStages" :key="name" :class="{current:i===executionStage}"><b>{{ i+1 }}</b>{{ name }}<small v-if="i===executionStage">{{ batch.state==='running'?'进行中':stateLabel }}</small></li></ol>
      <div v-if="batch.phase==='priming'||batch.phase==='ready'" class="notice">已完成预充循环：A {{ batch.priming?.completed_cycles?.[0] || 0 }} / {{ batch.request?.prime_cycles || '—' }} 次，B {{ batch.priming?.completed_cycles?.[1] || 0 }} / {{ batch.request?.prime_cycles || '—' }} 次。初始化与预充每批只执行一次。</div>
      <h4>各组进度与实验条件</h4><div class="table run-table"><table><thead><tr><th>组号</th><th>状态</th><th>A / B 温度（℃）</th><th>A / B 进料量（μL）</th><th>反应温度（℃）</th><th>保温（分钟）</th><th>样品编号</th></tr></thead><tbody><tr v-for="g in progressGroups" :key="g.index" :class="{selected:g.index===batch.current_group}"><td>{{ g.index }}</td><td>{{ labels[g.state] || g.state }}</td><td>{{ g.parameters[0] ?? '—' }} / {{ g.parameters[1] ?? '—' }}</td><td>{{ g.parameters[2] ?? '—' }} / {{ g.parameters[3] ?? '—' }}</td><td>{{ g.parameters[4] ?? '—' }}</td><td>{{ g.parameters[5] ?? '—' }}</td><td>{{ g.sample_id || '—' }}</td></tr></tbody></table></div>
      <p><small>整批进度按完成组数统计。升温和降温耗时取决于实测温度；不估算剩余完成时间。产物瓶仍由现场逐组更换。</small></p>
    </section>
    <div v-else class="layout"><main :inert="activeRun">
      <section v-if="stage<=2"><h3>{{ stages[stage] }}</h3><p>{{ stageDescriptions[stage] }}</p><div class="notice device-summary">{{ deviceSummary }}</div><div v-for="a in stageAxes" :key="a.key" class="axis"><div class="axis-heading"><strong>{{ a.label }}</strong><span>实验条件</span></div><div class="axis-controls"><label>设置方式<select v-model="a.mode"><option value="fixed">固定值</option><option value="range">范围与间隔</option><option value="list">指定数值</option></select></label><label v-if="a.mode!=='list'">{{ a.mode==='fixed'?'数值':'起点' }}<input v-model.number="a.start" type="number" step="any" /></label><template v-if="a.mode==='range'"><label>终点<input v-model.number="a.end" type="number" step="any" /></label><label>间隔<input v-model.number="a.interval" type="number" step="any" /></label></template><label v-if="a.mode==='list'">逗号分隔<input v-model="a.list" placeholder="多个数值用逗号分隔" /></label></div></div><div v-if="stage===1" class="grid settings"><label>A 进料速度（设备步频，赫兹）<input v-model.number="speedA" type="number" /></label><label>B 进料速度（设备步频，赫兹）<input v-model.number="speedB" type="number" /></label></div><p>支持固定值、范围与间隔或指定数值。演示初值需按实际实验修改。</p></section>
      <section v-if="stage===3"><h3>降温与产物收集</h3><div class="notice"><strong>抽液前降温条件：反应液温度 ≤ 45℃</strong><p>反应结束后停止微波加热，产物留在微波仪中自然降温。以微波仪读取的反应液温度为依据，降至 45℃及以下后，才允许切向产物出口并启动抽液，不使用固定等待秒数代替测温。温度读取失败或降温超时，不得继续抽液。</p><small>后端收取前会实测降温并复查温度，达到条件后自动抽液。降温超时上限为 60 分钟，需现场确认。</small></div><div class="notice">三通阀：{{ valveConfigured ? '已配置' : '配置缺失' }} · {{ registry.valves?.valve1?.connected ? '已连接' : '未连接' }}。状态只代表继电器读回，不代表实物流路已确认。</div><div class="notice">固定出口：NO（断电）收产物，NC（通电）排废液。请按此映射现场接管；页面显示不会切换设备。</div><p v-if="batch.request?.product_port==='NC'" class="notice">历史批次使用 NC 收产物，仅供查阅。新批次须按 NO 收产物、NC 排废液重新确认液路并预充。</p><p>固定液路：蠕动泵通道四抽取产物；产物从三通阀的产物出口排出，由人工逐组更换产物瓶。</p><div class="grid"><label v-for="item in fixed.filter(s=>['drainFlow','productTime'].includes(s.key))" :key="item.key">{{ item.label }}<input v-model.number="item.value" type="number" step="any" /></label></div><div class="estimate"><label>固定排液方向<select v-model="drainDirection"><option value="CW">顺时针（CW）</option><option value="CCW">逆时针（CCW）</option></select></label><small>排液时间由现场标定，覆盖管路死体积及排空余量；本批次所有组使用同一设定时间。</small></div></section>
      <section v-if="stage===4"><h3>清洗与排液</h3><p>固定液路：蠕动泵通道三注入清洗液，通道四抽出清洗液。</p><div class="notice">清洗排液流量：{{ setting('drainFlow') }} mL/min，与产物收集一致。</div><div class="grid"><label v-for="item in fixed.filter(s=>!['drainFlow','productTime'].includes(s.key))" :key="item.key">{{ item.label }}<input v-model.number="item.value" type="number" step="any" /></label></div><div class="estimate"><label>固定清洗进液方向<select v-model="cleanDirection"><option value="CW">顺时针（CW）</option><option value="CCW">逆时针（CCW）</option></select></label><small>排液时间独立填写，需现场标定管路排空余量；清洗进液按体积与进液流量计算。</small></div><div class="notice">先切 NC 废液端 → 注清洗液 → 停留 → 按填写时间排清洗液，按清洗次数重复。</div></section>
      <section v-if="stage===5">
        <h3>预充与排气</h3>
        <p>初始化 A → 初始化 B → 泵 A 预充 → 泵 B 预充 → 切向废液端 → 排液；不启动加热或微波。点击“开始自动实验”后自动执行，每批一次，各组不重复。</p>
        <div class="grid settings"><div v-for="(item,i) in initialization" :key="i"><h4>注射泵 {{ i===0?'A':'B' }} 初始化</h4><label>方向<select v-model="item.direction"><option value="Z">Z：左吸右排</option><option value="Y">Y：右吸左排</option></select></label><label class="settings">初始化代码<select v-model.number="item.initialization_code"><option v-for="code in initializationCodes" :key="code" :value="code">{{ code }}</option></select></label></div></div>
        <div class="grid"><label v-for="p in priming.slice(0,5)" :key="p.key">{{ p.label }}<input v-model.number="p.value" type="number" :step="p.key==='prime_cycles'?1:'any'" /></label></div>
        <el-button class="settings" @click="estimatePrimingTime">按理论量估算时间</el-button>
        <p><small>理论时间，需现场标定，不能证明彻底排空。</small></p>
        <p>预充耗液 / 废液 {{ primeTotal }} mL · 废液出口 {{ wastePort }}</p>
        <p>预充使用独立维护编号：批次编号_PRIMING_运行编号；正式产物从 S001 开始编号。</p>
        <details :open="advancedOpen" @toggle="advancedOpen=($event.target as HTMLDetailsElement).open">
          <summary>高级设置 <span v-if="advancedMissing">· 待填写</span></summary>
          <div class="grid settings"><label v-for="p in priming.slice(5)" :key="p.key">{{ p.label }}<input v-model.number="p.value" type="number" step="any" /></label></div>
          <p><small>按现场可用量填写，储液量须扣除防吸空余量；确认前驱体相容、残留剂量影响及废液防溢出。</small></p>
        </details>
        <label class="confirm-check"><input v-model="primingConfirmed" type="checkbox" />已确认设备就绪、前驱体相容及液路、容量和废液条件。</label>
        <label class="confirm-check"><input v-model="initializationConfirmed" type="checkbox" />已确认两台泵的初始化方向与代码，允许本批次活塞运动及切阀；故障原因已排除。</label>
        <el-button :loading="validating" @click="validate">生成并校验完整批次</el-button><p>{{ report }}</p>
        <p>此页只设置参数。进入批次确认并点击“开始自动实验”后，系统自动完成初始化与预充，成功后继续正式实验，无需单独操作预充。</p>
        <p v-if="primeReady">已有本批次预充结果，开始自动实验时将沿用，不重复初始化或预充。修改参数或维护设备前请先停止批次。</p>
        <details><summary>预充流程预览</summary><pre>{{ previewPrime }}</pre></details>
      </section>
      <section v-if="stage===6"><h3>批次确认 · {{ plan.rows.length }} 组</h3><label class="settings">每个条件重复次数<input v-model.number="repeats" type="number" min="1" /></label><div class="table"><table><thead><tr><th>组号</th><th v-for="a in axes" :key="a.key">{{ a.label }}</th><th>产物排液时间（秒）</th></tr></thead><tbody><tr v-for="(row,i) in plan.rows" :key="i" :class="{selected:selected===i}" @click="selected=i"><td>{{ i+1 }}</td><td v-for="(v,j) in row" :key="j">{{ v }}</td><td>{{ setting('productTime') }}</td></tr></tbody></table></div><h4>每组固定流程</h4><ol><li>前驱体 A/B 加热，两路同时在各自目标 ±3℃ 内持续 30 秒后才开始吸液与进料。</li><li>两泵各自吸取剂量，再并行进料、各自完成；任一路失败停止两路。</li><li>两路进料完成后微波升温，到温后保温，结束后停止微波；前驱体 A/B 加热器持续保温。</li><li>产物留在微波仪中降温，等待反应液实测温度降至 45℃及以下；读取失败或超时不进入抽液。</li><li>收取前复查温度 ≤45℃，阀切 NO 产物端，按填写时间抽取产物。</li><li>先切 NC 废液端，再注清洗液、停留、按填写时间排清洗液，按次数重复。</li><li>记录本组结果，加热器保持运行并自动进入下一组；新组按目标调整温度。整批结束、失败或停止时关闭加热器。换瓶由现场安排，程序不等待确认。</li></ol><el-button :loading="validating" :disabled="!!plan.error" @click="validate">生成并校验完整批次</el-button><p role="status">{{ report }}</p><details><summary>第 {{ selected+1 }} 组的完整实验流程</summary><p>完整流程由后端生成。校验不连接或启动硬件；开始实验才会执行。</p><pre>{{ fragment }}</pre></details></section>
    </main><aside><h3>本批实验</h3><div class="count">{{ plan.error?'—':plan.rows.length }} <small>组</small></div><p>{{ plan.counts.join(' × ') }} 个取值 × {{ repeats }} 次重复</p><el-alert v-if="plan.error" :title="plan.error" type="error" :closable="false" /><p>A 理论耗液（含预充）：{{ total(2)+primeValue('prime_volume_a')*primeValue('prime_cycles') }} 毫升</p><p>B 理论耗液（含预充）：{{ total(3)+primeValue('prime_volume_b')*primeValue('prime_cycles') }} 毫升</p><p>清洗液：{{ Number((plan.rows.length*setting('volume')*setting('cycles')).toPrecision(10)) }} 毫升</p><p>需人工更换的产物瓶：{{ plan.rows.length }} 个</p><hr /><strong>执行前确认</strong><p>请先在装置控制页连接全部设备。本批次预充前会依次初始化两台注射泵，请核对方向与代码并确认允许运动。</p><label class="confirm-check"><input v-model="plumbingConfirmed" type="checkbox" />已确认 NO 收产物、NC 排废液的接管、泵方向及微波负载条件</label><el-button type="primary" :loading="controlling" :disabled="stage!==6||!!plan.error||validatedKey!==requestKey||!plumbingConfirmed||!primingConfirmed||!initializationConfirmed||activeRun||(batch.phase==='ready'&&!primeReady)||batch.recovery_required" @click="startBatch">开始自动实验</el-button><p>自动初始化 → 本批次预充与排液 → 正式实验；预充成功后自动继续，降温达标后自动收取。</p></aside></div>
    <footer v-if="!showProgress"><el-button :disabled="stage===0" @click="goBack(stage-1)">上一步</el-button><el-button v-if="stage<6" type="primary" @click="nextStage">{{ stage===5?'批次确认':'下一步' }}</el-button><el-button @click="router.push('/experiment/batch/template')">高级：已有模板参数设计</el-button></footer>
  </div>
</template>
<script setup lang="ts">
import {computed,onMounted,onUnmounted,reactive,ref,watch} from 'vue'
import {ElMessageBox} from 'element-plus'
import {useRouter} from 'vue-router'
import axios from 'axios'
import {combinations,valuesFor,microwaveHoldSeconds,type Axis} from '../experiment/batch'
import {estimateDrainSeconds} from '../experiment/drainEstimate'
import {primingDrainForDisplay} from '../experiment/priming'
const router=useRouter(),stage=ref(0),selected=ref(0),error=ref(''),report=ref(''),validating=ref(false)
const stages=['前驱体加热','前驱体进料','微波反应','产物收集','清洗与排液','预充与排气','批次确认']
const stageDescriptions=['设置加热器 A/B 的目标温度，两路同时在各自目标 ±3℃ 内持续 30 秒后才开始吸液与进料。同批次持续保温（含反应、清洗、组间和暂停），下一组按新目标调整；结束、失败或停止时关闭。','分别设置 A/B 进样量和速度；双泵同时开始、各自完成。','两路进料完成后启动微波；物料到温后开始保温计时，每秒检查故障和控制状态。保温分钟须可转换为整秒，例如 0.5 分钟为 30 秒。']
const stageAxes=computed(()=>axes.value.slice(stage.value*2,stage.value*2+2))
const deviceSummary=computed(()=>stage.value===0?'加热器一：前驱体 A　｜　加热器二：前驱体 B':stage.value===1?'注射泵一：前驱体 A　｜　注射泵二：前驱体 B':'微波仪一：反应温区')
const roles=[{key:'heaterA',label:'前驱体 A 加热器',group:'heaters',description:'前驱体储液加热'},{key:'heaterB',label:'前驱体 B 加热器',group:'heaters',description:'独立温区'},{key:'pumpA',label:'前驱体 A 注射泵',group:'syringe_pumps',description:'进样量与速度独立设置'},{key:'pumpB',label:'前驱体 B 注射泵',group:'syringe_pumps',description:'同时进料、各自完成'},{key:'reaction',label:'微波反应装置',group:'microwaves',description:'测得物料到温后计时'},{key:'liquid',label:'清洗与排液蠕动泵',group:'pumps',description:'不同通道负责进液和排液'}]
const registry=ref<Record<string,Record<string,any>>>({}),chosen=reactive<Record<string,string>>({heaterA:'heater1',heaterB:'heater2',pumpA:'syringe_pump1',pumpB:'syringe_pump2',reaction:'microwave1',liquid:'pump1'})
const axes=ref<Axis[]>([['ta','前驱体 A 温度（℃）',30],['tb','前驱体 B 温度（℃）',30],['va','A 进样量（毫升）',0.1],['vb','B 进样量（毫升）',0.1],['tr','微波反应温度（℃）',30],['time','保温时间（分钟）',1]].map(([key,label,v])=>({key:String(key),label:String(label),value:Number(v),paths:[],mode:'fixed',start:Number(v),end:Number(v),interval:1,list:String(v)})))
const productPort='NO'
const wastePort='NC'
const valveConfigured=computed(()=>!!registry.value.valves?.valve1)
const repeats=ref(1),speedA=ref(100),speedB=ref(100),cleanChannel=ref(3),drainChannel=ref(4)
const fixed=ref([{key:'drainFlow',label:'产物与清洗共用排液流量（毫升／分钟）',value:1},{key:'productTime',label:'产物排液时间（秒，现场标定）',value:0},{key:'cleanTime',label:'清洗排液时间（秒，现场标定）',value:0},{key:'volume',label:'每次清洗液量（毫升）',value:1},{key:'flow',label:'清洗进液流量（毫升／分钟）',value:1},{key:'wait',label:'清洗停留时间（秒）',value:0},{key:'cycles',label:'每组清洗次数',value:1}])
const setting=(key:string)=>fixed.value.find(s=>s.key===key)!.value
const plan=computed(()=>{try{if(!Number.isInteger(repeats.value)||repeats.value<1)throw new Error('重复次数须为正整数');const rows=combinations(axes.value);if(rows.length*repeats.value>200)throw new Error('最多 200 组，请缩小范围');if(rows.some(r=>r.some((v,i)=>i===2||i===3?v<=0:v<0)))throw new Error('进样量须大于零，温度与时间不能为负');rows.forEach(r=>microwaveHoldSeconds(r[5]!));return{rows:rows.flatMap(r=>Array.from({length:repeats.value},()=>r)),counts:axes.value.map(a=>valuesFor(a).length),error:''}}catch(e){return{rows:[] as number[][],counts:[] as number[],error:String(e)}}})
function goBack(i:number){if(i>=0&&i<=stage.value){stage.value=i;error.value=''}}
function stepError(step:number):string {
 if(roles.some(r=>!chosen[r.key]||!registry.value[r.group]?.[chosen[r.key]!]))return '固定装置配置缺失，请检查设备配置后再继续'
 if(chosen.heaterA===chosen.heaterB||chosen.pumpA===chosen.pumpB)return '两路须选择不同的加热器和注射泵'
 if(step>=0){
  if(plan.value.error)return plan.value.error
  if(![speedA.value,speedB.value].every(v=>Number.isInteger(v)&&v>=5&&v<=5000))return '速度须为 5–5000 的整数步频'
 }
 if(step>=3){
  if(!valveConfigured.value)return '当前配置缺少三通阀 valve1'
  if(cleanChannel.value===drainChannel.value)return '进液与排液通道不能相同'
  for(const item of fixed.value.filter(s=>step>=4||['drainFlow','productTime'].includes(s.key)))if(!Number.isFinite(item.value)||(item.key==='wait'?item.value<0:item.value<=0)||(item.key==='cycles'&&!Number.isInteger(item.value)))return '请填写有效的收集与清洗参数'
  for(const key of step>=4?['productTime','cleanTime']:['productTime'])if(!Number.isFinite(setting(key))||setting(key)<0.1||setting(key)>9999)return '产物及清洗排液时间须为 0.1–9999 秒，请按现场标定填写'
  if(step>=4){try{const seconds=estimateDrainSeconds(setting('volume'),setting('flow'));if(seconds<0.1||seconds>9999)throw new Error()}catch{return '清洗进液时间超出有效范围，请检查体积和流量'}}
 }
 return ''
}
function nextStage(){error.value=stepError(stage.value);if(!error.value&&stage.value<6)stage.value++}
const total=(i:number)=>Number(plan.value.rows.reduce((s,r)=>s+r[i]!,0).toPrecision(10))
const plumbingConfirmed=ref(false),drainDirection=ref('CW'),cleanDirection=ref('CW')
const previewPrime=ref(''),previewYaml=ref<string[]>([]),validatedKey=ref(''),controlling=ref(false),batch=ref<any>({state:'idle'})
const activeRun=computed(()=>['running','paused'].includes(batch.value.state)&&batch.value.phase!=='ready')
const showProgress=ref(false),lastRefresh=ref(0),refreshError=ref('')
const executionStages=['初始化与预充','前驱体加热','吸液与进料','微波升温与保温','降温与收集','清洗与排液']
const executionStage=computed(()=>{
 if(batch.value.phase==='priming'||batch.value.phase==='ready')return 0
 const id=batch.value.progress?.step_id||''
 if(id.startsWith('heat_'))return 1
 if(id.startsWith('aspirate_')||id==='feed_both')return 2
 if(id.startsWith('microwave_')||id==='hold')return 3
 if(id.startsWith('cool_')||id==='recheck_temperature'||id==='product_route'||id.startsWith('collect_'))return 4
 if(id.startsWith('clean_'))return 5
 return -1
})
const phaseLabel=computed(()=>batch.value.phase==='priming'?'初始化与预充':batch.value.phase==='ready'?'预充完成，待正式启动':'正式实验')
const completedGroups=computed(()=>(batch.value.groups||[]).filter((g:any)=>g.state==='completed').length)
const displayedStep=computed(()=>Math.min((batch.value.progress?.current_step??0)+1,batch.value.progress?.total_steps||0))
const elapsedLabel=computed(()=>{
 const seconds=Math.max(0,Math.floor(batch.value.progress?.elapsed||0))
 return `${Math.floor(seconds/3600)}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`
})
const currentStepLabel=computed(()=>batch.value.state==='completed'?'全部实验组已完成':batch.value.phase==='ready'?'预充已完成，等待正式启动':batch.value.progress?.step_label||(batch.value.state==='running'?'正在准备执行':'暂无步骤信息'))
const currentDevice=computed(()=>{
 if(batch.value.progress?.device_id)return batch.value.progress.device_id
 const id=batch.value.progress?.step_id||''
 if(id==='heat_both_stable')return '加热器 A / B'
 if(id.startsWith('heat_'))return id.startsWith('heat_0')?'加热器 A':'加热器 B'
 if(id.startsWith('aspirate_'))return id==='aspirate_0'?'注射泵 A':'注射泵 B'
 if(id==='feed_both')return '注射泵 A / B'
 if(id.startsWith('microwave_')||id==='hold'||id.startsWith('cool_')||id==='recheck_temperature')return '微波反应仪'
 if(id==='product_route'||id.endsWith('_route'))return '三通阀'
 if(id.startsWith('collect_')||/^clean_\d+_out/.test(id))return '蠕动泵 / 通道四'
 if(/^clean_\d+_in/.test(id))return '蠕动泵 / 通道三'
 return '—'
})
const progressGroups=computed(()=>{
 const r=batch.value.request
 let rows:number[][]=[[]]
 if(r?.axes?.length===6){
  for(const values of r.axes)rows=rows.flatMap(row=>values.map((v:number)=>[...row,v]))
  rows=rows.flatMap(row=>Array.from({length:r.repeats||1},()=>row))
 }else rows=[]
 return Array.from({length:batch.value.total_groups||0},(_,i)=>{
  const recorded=batch.value.groups?.find((g:any)=>g.index===i+1)
  return {index:i+1,parameters:recorded?.parameters||rows[i]||[],sample_id:recorded?.sample_id,
   state:recorded?.state==='running'&&i+1===batch.value.current_group?batch.value.state:recorded?.state||'pending'}
 })
})
const primeFields=[{key:'prime_volume_a',label:'A 每次预充量（mL）',value:2},{key:'prime_volume_b',label:'B 每次预充量（mL）',value:2},{key:'prime_cycles',label:'每台泵循环次数',value:2},{key:'prime_drain_seconds',label:'排液时间（秒）',value:480},{key:'prime_drain_flow',label:'预充排液流量（mL/min）',value:1},{key:'reactor_available_ml',label:'反应仪可用容积（mL，现场填写）',value:0},{key:'source_available_a_ml',label:'A 可用前驱体量（mL）',value:0},{key:'source_available_b_ml',label:'B 可用前驱体量（mL）',value:0},{key:'waste_available_ml',label:'废液瓶剩余可用容积（mL）',value:0}]
const priming=ref(primeFields),primingConfirmed=ref(false),initializationConfirmed=ref(false)
const initialization=ref([{direction:'Z',initialization_code:0},{direction:'Z',initialization_code:0}])
const initializationCodes=[0,1,2,...Array.from({length:31},(_,i)=>i+10)]
const primeValue=(key:string)=>priming.value.find(p=>p.key===key)!.value
const primeTotal=computed(()=>(primeValue('prime_volume_a')+primeValue('prime_volume_b'))*primeValue('prime_cycles'))
const advancedOpen=ref(false)
const advancedMissing=computed(()=>priming.value.slice(5).some(p=>!Number.isFinite(p.value)||p.value<=0))
function estimatePrimingTime(){try{const cycles=primeValue('prime_cycles');if(!Number.isInteger(cycles)||cycles<1||cycles>10||primeValue('prime_volume_a')<=0||primeValue('prime_volume_b')<=0)throw new Error('请填写有效的预充体积及循环次数');const seconds=estimateDrainSeconds(primeTotal.value,primeValue('prime_drain_flow'));if(seconds<0.1||seconds>9999)throw new Error('排液时间须为 0.1–9999 秒');priming.value.find(p=>p.key==='prime_drain_seconds')!.value=seconds;error.value=''}catch(e){showError(e)}}
const primeReady=computed(()=>batch.value.request?.initialization_a!=null&&batch.value.request?.initialization_b!=null&&batch.value.request?.product_port==='NO'&&batch.value.request?.product_drain_seconds!=null&&batch.value.request?.clean_drain_seconds!=null&&batch.value.request?.prime_drain_seconds!=null&&batch.value.request?.prime_drain_flow!=null&&batch.value.phase==='ready'&&batch.value.state==='paused'&&!batch.value.recovery_required&&batch.value.priming?.status==='completed'&&JSON.stringify(batch.value.request&&requestWithoutFlags(batch.value.request))===JSON.stringify(requestWithoutFlags(requestBody.value)))
function requestWithoutFlags(r:any){const keys=Object.keys(requestBody.value).filter(k=>!['plumbing_confirmed','priming_confirmed','initialization_confirmed','priming_batch_id'].includes(k));return Object.fromEntries(keys.map(k=>[k,r[k]]))}
const labels:Record<string,string>={idle:'未运行',pending:'待执行',running:'执行中',paused:'已暂停',completed:'已完成',failed:'失败',stopped:'已停止',interrupted:'服务中断'}
const stateLabel=computed(()=>labels[batch.value.state]||batch.value.state)
const requestBody=computed(()=>({axes:axes.value.map(a=>valuesFor(a)),repeats:repeats.value,initialization_a:initialization.value[0],initialization_b:initialization.value[1],speed_a:speedA.value,speed_b:speedB.value,product_port:productPort,drain_flow:setting('drainFlow'),product_drain_seconds:setting('productTime'),clean_drain_seconds:setting('cleanTime'),clean_volume:setting('volume'),clean_flow:setting('flow'),clean_dwell:setting('wait'),clean_cycles:setting('cycles'),drain_direction:drainDirection.value,clean_direction:cleanDirection.value,...Object.fromEntries(priming.value.map(p=>[p.key,p.value]))}))
const requestKey=computed(()=>{try{return JSON.stringify(requestBody.value)}catch{return ''}})
const fragment=computed(()=>previewYaml.value[selected.value]||'请先生成并校验完整批次。')
watch([axes,chosen,repeats,speedA,speedB,fixed,drainDirection,cleanDirection,priming,initialization],()=>{report.value='';selected.value=0;validatedKey.value='';previewYaml.value=[];previewPrime.value='';plumbingConfirmed.value=false;primingConfirmed.value=false;initializationConfirmed.value=false},{deep:true})
function showError(e:any){const detail=e.response?.data?.detail;error.value=Array.isArray(detail)?detail.map(d=>`${d.loc?.slice(1).join('.') || '参数'}：${d.msg}`).join('；'):String(detail||e.message||e)}
async function validate(){validating.value=true;report.value='';try{const issue=stepError(5);if(issue)throw new Error(issue);if(advancedMissing.value)throw new Error('请在高级设置中填写有效的可用容积和储液量');const key=requestKey.value;const {data}=await axios.post('/api/guided/preview',requestBody.value);if(key!==requestKey.value)return;previewYaml.value=data.yaml;previewPrime.value=JSON.stringify(data.priming,null,2);validatedKey.value=key;report.value=`后端已生成并校验 ${data.total_groups} 组完整流程，尚未启动设备。`}catch(e){stage.value=5;advancedOpen.value=true;showError(e)}finally{validating.value=false}}
let restored=false
async function refreshBatch(){try{batch.value=(await axios.get('/api/guided/current')).data;lastRefresh.value=Date.now();refreshError.value='';if(!restored&&batch.value.request){const r=batch.value.request;axes.value.forEach((a,i)=>{const values=r.axes[i];a.mode=values.length===1?'fixed':'list';a.start=values[0];a.list=values.join(',')});repeats.value=r.repeats;speedA.value=r.speed_a;speedB.value=r.speed_b;drainDirection.value=r.drain_direction;cleanDirection.value=r.clean_direction;const mapping:Record<string,string>={drainFlow:'drain_flow',productTime:'product_drain_seconds',cleanTime:'clean_drain_seconds',volume:'clean_volume',flow:'clean_flow',wait:'clean_dwell',cycles:'clean_cycles'};fixed.value.forEach(s=>s.value=r[mapping[s.key]!]??0);const displayDrain=primingDrainForDisplay(r);priming.value.forEach(p=>p.value=displayDrain[p.key as keyof typeof displayDrain]??r[p.key]??p.value);if(r.initialization_a&&r.initialization_b)initialization.value=[{...r.initialization_a},{...r.initialization_b}];stage.value=batch.value.phase==='ready'?6:5;showProgress.value=true;restored=true}}catch{refreshError.value='进度读取失败，当前显示为上次收到的状态。请检查后端连接。'}}
async function startBatch(){
 if(controlling.value)return
 controlling.value=true
 try{
  const key=requestKey.value
  if(validatedKey.value!==key||!plumbingConfirmed.value||!primingConfirmed.value||!initializationConfirmed.value||activeRun.value||(batch.value.phase==='ready'&&!primeReady.value))throw new Error('请先校验当前参数并确认现场条件，已有批次须先停止')
  await ElMessageBox.confirm('将先自动初始化 A/B（移动活塞并切阀），按设定参数预充并排废液，消耗前驱体；成功后自动开始加热、进料和微波反应。已有匹配的本批次预充结果时直接开始正式实验。请确认初始化方向与代码、设备安装、液路、容量、废液及微波负载条件，运行期间有人看护。','开始真实实验',{confirmButtonText:'确认启动',cancelButtonText:'取消',type:'warning'})
  if(key!==requestKey.value||validatedKey.value!==key||!plumbingConfirmed.value||!primingConfirmed.value||!initializationConfirmed.value||activeRun.value||(batch.value.phase==='ready'&&!primeReady.value))throw new Error('参数、确认或批次状态已变化，请重新校验并确认')
  batch.value=(await axios.post('/api/guided/start',{...requestBody.value,plumbing_confirmed:plumbingConfirmed.value,priming_confirmed:primingConfirmed.value,initialization_confirmed:initializationConfirmed.value,priming_batch_id:primeReady.value?batch.value.batch_id:undefined})).data
  showProgress.value=true
  lastRefresh.value=Date.now()
  refreshError.value=''
  error.value=''
 }catch(e){if(e!=='cancel'&&e!=='close')showError(e)}finally{controlling.value=false}
}
async function controlBatch(action:string){controlling.value=true;try{const {data}=await axios.post(`/api/guided/${batch.value.batch_id}/${action}`,{});if(data.success===false)throw new Error('停止或记录保存未确认成功，请检查设备及后端状态');await refreshBatch()}catch(e){showError(e)}finally{controlling.value=false}}
async function acknowledgeInterrupted(){controlling.value=true;try{await ElMessageBox.confirm('请在现场确认所有设备已停止。请同时检查预充残留、气泡和液路。此操作只解除恢复锁定，不恢复原批次。','确认中断后的设备状态',{type:'warning'});await axios.post(`/api/guided/${batch.value.batch_id}/acknowledge-interrupted`,{devices_stopped_confirmed:true});await refreshBatch()}catch(e){if(e!=='cancel'&&e!=='close')showError(e)}finally{controlling.value=false}}
let statusTimer:ReturnType<typeof setInterval>|undefined
onMounted(()=>{void refreshBatch();statusTimer=setInterval(()=>{void refreshBatch()},2000)})
onUnmounted(()=>{if(statusTimer)clearInterval(statusTimer)})
onMounted(async()=>{try{registry.value=(await axios.get('/api/devices')).data;if(!batch.value.request){initialization.value.forEach((item,i)=>{const capacity=registry.value.syringe_pumps?.[`syringe_pump${i+1}`]?.capacity_ml;if(capacity!=null)item.initialization_code=capacity>=2.5?0:capacity>=0.5?1:2})}const missing=roles.filter(r=>!registry.value[r.group]?.[chosen[r.key]!]);if(missing.length)error.value='配置缺少固定装置：'+missing.map(r=>r.label).join('、')}catch{error.value='读取装置失败，请检查后端服务。'}})
</script>
<style scoped>
.estimate strong{display:block;margin:16px 0 12px}.estimate .el-button{margin-bottom:12px}
.guided{max-width:1400px;margin:auto;padding:12px;color:#243e58}header{display:flex;justify-content:space-between;align-items:center;gap:20px}h2{font-size:28px;margin:0}p{color:#667e94;line-height:1.7}nav{display:flex;gap:8px;margin:24px 0;flex-wrap:wrap}nav button{flex:1;min-width:115px;padding:14px 8px;border:1px solid #ccddeb;border-radius:10px;background:white;color:#526b83;cursor:pointer}nav b{flex-shrink:0;display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#e8f2fc;margin-right:10px}nav button:disabled{opacity:.45;cursor:not-allowed}nav .active{background:#edf7ff;border-color:#409eff;color:#1680d6}.layout{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:20px}section,aside{padding:24px;border:1px solid #dce7f1;border-radius:14px;background:#ffffffef}aside{align-self:start;position:sticky;top:90px}aside h3{margin:0 0 8px}aside p{font-size:13px;margin:12px 0}aside .el-button{width:100%}section h3{margin:0 0 10px}section>p{margin:8px 0 16px}header .el-button{flex-shrink:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}label{display:flex;flex-direction:column;gap:8px;font-size:13px}small{color:#6d8499}input,select{min-width:0;max-width:100%;padding:10px;border:1px solid #c3d6e7;border-radius:7px;background:white;color:#243e58}.notice{margin-top:18px;padding:18px;background:#eef5fb;border-radius:10px;line-height:1.8}.axis{margin-top:18px;padding:20px;border:1px solid #dce7f1;border-radius:12px;background:#fbfdff}.axis-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.axis-heading strong{font-size:15px}.axis-heading span{font-size:12px;color:#73899d}.axis-controls{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:end}.axis-controls input,.axis-controls select{width:100%;box-sizing:border-box;height:42px}.axis-controls label{min-width:0}.axis-controls label:last-child:first-child{grid-column:span 2}.settings{margin-top:24px}.device-summary{margin-bottom:24px;font-size:13px}.estimate{margin-top:20px;padding:18px;background:#eaf5ff;border:1px solid #cbe4fa;border-radius:10px}.estimate p{margin:8px 0}.estimate small{line-height:1.7;display:block}.confirm-check{flex-direction:row;align-items:flex-start;line-height:1.6;margin:12px 0}.confirm-check input{flex-shrink:0;width:16px;height:16px;margin:3px 0 0;padding:0}.count{font-size:62px;color:#1688e8;font-weight:700}.count small{font-size:20px}.table{overflow:auto;max-height:450px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:12px;text-align:left;border-bottom:1px solid #dce7f1}th{background:#eff6fc}.selected{background:#e7f4ff}li{line-height:1.9;font-size:14px}pre{background:#172c40;color:#e0edf8;padding:16px;overflow:auto;max-height:350px}details{margin-top:20px}footer{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0}@media(max-width:1000px){.layout{grid-template-columns:1fr}aside{position:static}}@media(max-width:760px){.axis-controls{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.grid{grid-template-columns:1fr}nav,header{flex-wrap:wrap}nav button{min-width:130px}}

.header-actions,.run-heading,.run-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.run-panel{margin-top:24px}.run-heading{justify-content:space-between;margin-bottom:20px}.run-heading h3{font-size:26px;margin:0}.batch-id{margin:8px 0 0;font-size:12px;overflow-wrap:anywhere}.run-panel>.el-alert{margin:12px 0}.run-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:24px 0}.run-summary>div{padding:20px;background:#eef5fb;border-radius:12px;display:flex;flex-direction:column;gap:10px}.run-summary strong{font-size:26px}.run-summary span{font-size:12px;color:#667e94}.run-summary progress{width:100%;height:10px;accent-color:#1688e8}.current-operation{padding:24px;background:#eaf5ff;border-left:4px solid #1688e8;border-radius:10px}.current-operation h3{margin:10px 0}.current-operation p{margin:0}.run-stages{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;list-style:none;padding:0;margin:24px 0}.run-stages li{display:flex;flex-direction:column;gap:8px;padding:16px 12px;background:#f5f8fc;border:1px solid #dce7f1;border-radius:10px;font-size:13px}.run-stages b{font-size:18px}.run-stages .current{background:#eaf5ff;border-color:#1688e8;color:#1680d6}.run-table{max-height:500px}.run-table td:nth-child(2){white-space:nowrap}@media(max-width:1000px){.run-stages{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:600px){.run-summary{grid-template-columns:1fr}.run-stages{grid-template-columns:repeat(2,minmax(0,1fr))}.run-panel{padding:16px}}
</style>
