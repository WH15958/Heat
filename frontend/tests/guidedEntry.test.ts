import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as progress from '../src/experiment/guidedProgress'
import * as history from '../src/experiment/guidedHistory'
const source=readFileSync(new URL('../src/views/GuidedEntryPage.vue',import.meta.url),'utf8')
const compiled=ts.transpileModule(compileScript(parse(source).descriptor,{id:'entry-test'}).content,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText
function page(){
 const route=vue.reactive({query:{} as any}),calls:string[]=[],stored=new Map<string,string>()
 let records:any[]=[],current:any={state:'idle'},confirm=false
 const details:Record<string,any>={},plans:Record<string,any>={}
 let runs:any[]=[],failPlan=false
 const imports:Record<string,any>={
  vue:{...vue,onMounted:()=>{},onUnmounted:()=>{}},
  'vue-router':{useRoute:()=>route,useRouter:()=>({push:async(v:any)=>{route.query=typeof v==='string'?{}:v.query},replace:async(v:any)=>{route.query=v.query}})},
  axios:{get:async(url:string)=>{calls.push(url);if(url.endsWith('/current'))return{data:current};if(url.endsWith('/batches'))return{data:records};if(url.endsWith('/runs'))return{data:runs};if(url.endsWith('/plan')){if(failPlan)throw Error('missing');return{data:plans[url.split('/')[3]!]}};return{data:details[url.split('/')[3]!]}}},
  'element-plus':{ElMessageBox:{confirm:async()=>{if(!confirm)throw 'cancel'}}},
  './BatchExperimentPage.vue':{},'../experiment/guidedProgress':progress,'../experiment/guidedHistory':history,
 }
 const exports:any={},scope=vue.effectScope()
 runInNewContext(compiled,{exports,localStorage:{getItem:(k:string)=>stored.get(k)||null,setItem:(k:string,v:string)=>stored.set(k,v),removeItem:(k:string)=>stored.delete(k)},require:(name:string)=>{assert.ok(name in imports,name);return imports[name]}})
 const state=scope.run(()=>exports.default.setup({}, {expose:()=>{}}))
 return{state,route,calls,stored,details,plans,setRecords:(v:any[])=>{records=v},setCurrent:(v:any)=>{current=v},setRuns:(v:any[])=>{runs=v},failPlan:()=>{failPlan=true},confirm:()=>{confirm=true},dispose:()=>scope.stop()}
}
test('entry honors active, recovery, cleanup and persistence barriers without sending control',async()=>{
 const p=page()
 try{for(const current of [{state:'running'},{state:'paused',phase:'ready'},{state:'failed',recovery_required:true},{state:'completed',cleanup_pending:true},{state:'failed',persistence_status:'error'}]){
  p.setCurrent(current);await p.state.load();assert.equal(p.state.attention.value,true);await p.state.create();assert.equal(p.route.query.new,undefined)
 }assert.ok(p.calls.every(url=>url.endsWith('/current')||url.endsWith('/batches')))}finally{p.dispose()}
})

test('history shows recorded conditions before plans and keeps unexecuted groups explicitly planned',async()=>{
 const p=page();try{
  p.details.B={batch_id:'B',total_groups:4,request:{axes:[[30],[31],[2],[3],[70,80,90,100],[10]],repeats:1},groups:[
   {index:1,state:'completed',parameters:[35,36,1,2,72,11]},
   {index:2,state:'failed',parameters:[30,31,2,3,80,10]},
  ]}
  p.plans.B={batch_id:'B',recipes:[{metadata:{sample_index:3,guided_parameters:[30,31,2,3,95,12]}}]}
  await p.state.readDetail('B')
  const groups=p.state.groups.value
  assert.equal(groups[0].parameters[4],72);assert.match(groups[0].conditionSource,/执行记录/)
  assert.equal(groups[1].parameters[4],80);assert.equal(groups[1].state,'failed')
  assert.equal(groups[2].parameters[4],95);assert.match(groups[2].conditionSource,/计划.*未执行/)
  assert.equal(groups[3].parameters[4],100);assert.equal(groups[3].run_id,undefined)
  p.plans.B={batch_id:'wrong',recipes:[{metadata:{sample_index:3,guided_parameters:[1,1,1,1,1,1]}}]}
  await p.state.readDetail('B');assert.equal(p.state.groups.value[2].parameters[4],90)
 }finally{p.dispose()}
})

test('missing historical conditions stay unknown and repeated plans retain group order',()=>{
 const batch={batch_id:'B',total_groups:5,request:{axes:[[30],[30],[2],[2],[70,80],[10]],repeats:2},groups:[]}
 assert.deepEqual(history.guidedHistoryGroups(batch,null).map(g=>g.parameters?.[4]),[70,70,80,80,undefined])
 assert.equal(history.guidedHistoryGroups({total_groups:1},null)[0]!.conditionSource,'条件未记录')
})

test('history reuse replaces a draft only after confirmation and copies input without execution identity',async()=>{
 const p=page();try{
  const request={axes:[[30],[30],[2],[2],[70,80],[10]],repeats:2,experiment_name:'旧名称',prime_drain_seconds:200,
   plumbing_confirmed:true,bottles_confirmed:true,priming_batch_id:'old',sample_id:'old-sample'}
  p.details.B={batch_id:'B',experiment_name:'旧名称',request,total_groups:4,groups:[]}
  await p.state.readDetail('B');p.stored.set('heat.guided-draft.v1','existing')
  await p.state.reuseConditions();assert.equal(p.stored.get('heat.guided-draft.v1'),'existing')
  p.confirm();await p.state.reuseConditions()
  const draft=JSON.parse(p.stored.get('heat.guided-draft.v1')!)
  assert.equal(p.route.query.new,'1');assert.equal(draft.kind,'guided-history')
  assert.deepEqual(draft.request.axes,request.axes);assert.equal(draft.request.prime_drain_seconds,200)
  for(const key of ['experiment_name','plumbing_confirmed','bottles_confirmed','priming_batch_id','sample_id'])assert.equal(draft.request[key],undefined)
  assert.equal(request.plumbing_confirmed,true)
  assert.ok(p.calls.every(url=>url.startsWith('/api/guided/')||url==='/api/experiments/history/runs'))
 }finally{p.dispose()}
})

test('history reuse rechecks current execution and leaves draft intact if a batch needs attention',async()=>{
 for(const current of [{state:'running'},{state:'failed',recovery_required:true},{state:'failed',cleanup_required:true},{state:'failed',persistence_status:'error'}]){
  const p=page();try{
   p.details.B={batch_id:'B',request:{axes:[[30],[30],[2],[2],[70],[10]]},total_groups:1}
   await p.state.readDetail('B');p.confirm();p.stored.set('heat.guided-draft.v1','existing');p.setCurrent(current)
   await p.state.reuseConditions()
   assert.equal(p.stored.get('heat.guided-draft.v1'),'existing');assert.equal(p.route.query.new,undefined)
   assert.match(p.state.detailError.value,/恢复事项/)
  }finally{p.dispose()}
 }
})
test('new experiment preserves draft on cancellation and requires explicit replacement',async()=>{
 const p=page();try{p.stored.set('heat.guided-draft.v1','draft');p.state.checkDraft();await p.state.create();assert.equal(p.stored.get('heat.guided-draft.v1'),'draft');assert.equal(p.route.query.new,undefined);p.confirm();await p.state.create();assert.equal(p.stored.has('heat.guided-draft.v1'),false);assert.equal(p.route.query.new,'1')}finally{p.dispose()}
})
test('batch detail keeps parameters and partial/failed priming even with no executed groups',async()=>{
 const p=page();try{
  const batch={batch_id:'B',experiment_name:'同名批次',state:'failed',request:{axes:[[30]],prime_cycles:2},total_groups:3,groups:[],priming:{status:'failed',run_id:'prime'}}
  p.details.B=batch;p.plans.B={batch_id:'B',request:batch.request,priming:{},recipes:[]};p.setRuns([{run_id:'prime',status:'failed'},{run_id:'unrelated',experiment_name:'同名批次'}])
  await p.state.readDetail('B');assert.equal(p.state.detail.value.batch_id,'B');assert.equal(p.state.related.value.length,1);assert.equal(p.state.related.value[0].run_id,'prime');assert.equal(p.state.groups.value.length,3);assert.equal(p.state.groups.value[2].state,'pending')
  p.failPlan();await p.state.readDetail('B');assert.equal(p.state.detail.value.priming.status,'failed');assert.match(p.state.detailError.value,/快照/)
 }finally{p.dispose()}
})

test('batch history preserves bottle associations and distinguishes collection from final homing',async()=>{
 const p=page();try{
  const group={index:1,state:'completed',sample_id:'B_S001',bottle_number:1,collection_status:'collected',run_id:'R'}
  p.details.B={batch_id:'B',state:'failed',total_groups:1,groups:[group],finalization:{status:'failed',error:'回零失败'},turntable:{current_bottle:null,target_bottle:1},turntable_events:[{operation:'homing'}]}
  p.plans.B={batch_id:'B',request:{},priming:{},recipes:[]};p.setRuns([{run_id:'R',metadata:{batch_id:'B'}}])
  await p.state.readDetail('B')
  assert.equal(p.state.finalizationFailed.value,true);assert.equal(p.state.groups.value[0].bottle_number,1);assert.equal(p.state.groups.value[0].collection_status,'collected')
  p.details.B.groups=[{...group,state:'failed',collection_status:'possibly_partial',collection_error:'排液中断'}]
  await p.state.readDetail('B')
  assert.equal(p.state.finalizationFailed.value,false);assert.equal(p.state.groups.value[0].collection_status,'possibly_partial');assert.equal(p.state.groups.value[0].collection_error,'排液中断')
  assert.ok(p.calls.every(url=>url.startsWith('/api/guided/')||url==='/api/experiments/history/runs'))
 }finally{p.dispose()}
})
