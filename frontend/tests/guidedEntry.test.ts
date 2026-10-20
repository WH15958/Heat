import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as progress from '../src/experiment/guidedProgress'
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
  './BatchExperimentPage.vue':{},'../experiment/guidedProgress':progress,
 }
 const exports:any={},scope=vue.effectScope()
 runInNewContext(compiled,{exports,localStorage:{getItem:(k:string)=>stored.get(k)||null,removeItem:(k:string)=>stored.delete(k)},require:(name:string)=>{assert.ok(name in imports,name);return imports[name]}})
 const state=scope.run(()=>exports.default.setup({}, {expose:()=>{}}))
 return{state,route,calls,stored,details,plans,setRecords:(v:any[])=>{records=v},setCurrent:(v:any)=>{current=v},setRuns:(v:any[])=>{runs=v},failPlan:()=>{failPlan=true},confirm:()=>{confirm=true},dispose:()=>scope.stop()}
}
test('entry honors active, recovery, cleanup and persistence barriers without sending control',async()=>{
 const p=page()
 try{for(const current of [{state:'running'},{state:'paused',phase:'ready'},{state:'failed',recovery_required:true},{state:'completed',cleanup_pending:true},{state:'failed',persistence_status:'error'}]){
  p.setCurrent(current);await p.state.load();assert.equal(p.state.attention.value,true);await p.state.create();assert.equal(p.route.query.new,undefined)
 }assert.ok(p.calls.every(url=>url.endsWith('/current')||url.endsWith('/batches')))}finally{p.dispose()}
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
