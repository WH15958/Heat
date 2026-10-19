import assert from 'node:assert/strict'
import {test} from 'node:test'
import {activeStage,stageState,staleStatus,batchRunIds,batchExport,formatTemperature} from '../src/experiment/guidedProgress'

test('stages reset per group while preparation remains completed; terminal is never running',()=>{
 const batch:any={state:'running',phase:'experiments',priming:{status:'completed'},current_group:2,progress:{step_id:'heat_both_stable'}}
 assert.equal(stageState(batch,0),'completed')
 assert.equal(stageState(batch,1),'running')
 assert.equal(stageState(batch,3),'pending')
 for(const [key,value,expected] of [['state','paused','paused'],['state','failed','failed'],['state','stopped','stopped'],['stop_requested',true,'stopping'],['cleanup_in_progress',true,'cleanup']] as const){
  assert.equal(stageState({...batch,[key]:value},1),expected)
 }
 assert.equal(activeStage({progress:{step_id:'unknown'}}),-1)
 assert.equal(activeStage({progress:{activity:{stage:'cleaning'}}}),5)
 assert.equal(stageState({...batch,state:'stopped'},5),'pending')
})

test('refresh errors and six-second freshness do not invent countdowns',()=>{
 assert.equal(staleStatus(1000,7000,''),false)
 assert.equal(staleStatus(1000,7001,''),true)
 assert.equal(staleStatus(1000,1001,'offline'),true)
 assert.equal(staleStatus(0,1000,''),true)
})

test('batch history joins exact run IDs and metadata, never names; export is all or nothing',async()=>{
 const batch={batch_id:'B',priming:{status:'completed',run_id:'prime'},groups:[{state:'completed',run_id:'group'}]}
 const runs=[{run_id:'prime'}, {run_id:'group',metadata:{batch_id:'B'}},{run_id:'extra',metadata:{batch_id:'B'}},{run_id:'other',experiment_name:'same name'}]
 assert.deepEqual(batchRunIds(batch,runs),['prime','group','extra'])
 const get=async(url:string)=>({data:url.endsWith('/runs')?runs:runs.find(r=>url.endsWith('/'+r.run_id))})
 const result=await batchExport(batch,get)
 assert.equal(result.count,3)
 await assert.rejects(batchExport(batch,async url=>{if(url.endsWith('/group'))throw new Error('missing');return get(url)}),/missing/)
 await assert.rejects(batchExport({...batch,persistence_status:'error'},get),/保存失败/)
 await assert.rejects(batchExport({batch_id:'missing'},async()=>({data:[]})),/缺失/)
})

test('temperature display rounds without changing measurements',()=>{
 assert.equal(formatTemperature(61.171875),'61.2 ℃')
 assert.equal(formatTemperature(44.42578125),'44.4 ℃')
 for(const value of [null,undefined,NaN,Infinity,'50'])assert.equal(formatTemperature(value),'温度未知')
 assert.equal(formatTemperature(0),'0.0 ℃')
})
