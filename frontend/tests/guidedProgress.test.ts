import assert from 'node:assert/strict'
import {test} from 'node:test'
import {activeStage,stageState,staleStatus,batchRunIds,batchExport,formatTemperature,temperatureReadingStatus,batchCompletionConfirmed,collectionStatusLabel,turntableBottleLabel,batchElapsedLabel} from '../src/experiment/guidedProgress'

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

test('whole-batch elapsed time survives group resets and final turntable progress',()=>{
 for(const progress of [{elapsed:12},{elapsed:0,step_id:'turntable_home_finish'},undefined]){
  assert.equal(batchElapsedLabel({elapsed_seconds:3723.9,progress}),'1:02:03')
 }
 assert.equal(batchElapsedLabel({elapsed_seconds:0}),'0:00:00')
 for(const elapsed_seconds of [null,undefined,NaN,Infinity,-1,'120']){
  assert.equal(batchElapsedLabel({elapsed_seconds,progress:{elapsed:120}}),'未记录')
 }
 assert.equal(batchElapsedLabel({created_at:'2026-10-25T00:00:00Z',progress:{elapsed:120}}),'未记录')
})

test('completion presentation waits for successful batch and confirmed cleanup',()=>{
 assert.equal(batchCompletionConfirmed({state:'completed'}),true)
 for(const state of ['running','paused','failed','stopped','interrupted'])assert.equal(batchCompletionConfirmed({state}),false)
 for(const flag of ['cleanup_in_progress','cleanup_pending','cleanup_required','recovery_required'])assert.equal(batchCompletionConfirmed({state:'completed',[flag]:true}),false)
 // Saving a record is separate from experiment success; show its explicit warning in the completed panel.
 assert.equal(batchCompletionConfirmed({state:'completed',persistence_status:'error'}),true)
 const automatic={state:'completed',request:{turntable_drip_seconds:0}}
 assert.equal(batchCompletionConfirmed(automatic),false)
 for(const status of ['pending','running','failed'])assert.equal(batchCompletionConfirmed({...automatic,finalization:{status}}),false)
 assert.equal(batchCompletionConfirmed({...automatic,finalization:{status:'completed'}}),true)
})

test('turntable preparation, indexing and finalization override stale group activities',()=>{
 for(const phase of ['indexing','finishing']){
  const batch={state:'running',phase,progress:{activity:{stage:'cleaning'}}}
  assert.equal(activeStage(batch),6);assert.equal(stageState(batch,6),'running')
 }
 assert.equal(activeStage({phase:'preparing',progress:{activity:{stage:'reaction'}}}),0)
 assert.equal(activeStage({progress:{step_id:'turntable_settle'}}),6)
 assert.equal(stageState({state:'failed',phase:'finishing',finalization:{status:'failed'}},6),'failed')
 assert.equal(stageState({state:'completed',phase:'finishing',finalization:{status:'failed'}},6),'failed')
 assert.equal(stageState({state:'paused',phase:'indexing'},6),'paused')
 assert.equal(stageState({state:'running',phase:'indexing',stop_requested:true},6),'stopping')
})

test('bottle and collection labels retain unknown and partially collected states',()=>{
 for(const value of [null,undefined,0,-1,NaN,'1',1.5])assert.equal(turntableBottleLabel(value),'未确认')
 assert.equal(turntableBottleLabel(2),'2 号瓶')
 assert.equal(collectionStatusLabel('possibly_partial'),'可能部分收取')
 assert.equal(collectionStatusLabel('collecting'),'收取中')
 assert.equal(collectionStatusLabel('collected'),'已收取')
 assert.equal(collectionStatusLabel(undefined),'未记录')
})

test('batch history joins exact run IDs and metadata, never names; export is all or nothing',async()=>{
 const batch={batch_id:'B',priming:{status:'completed',run_id:'prime'},groups:[{state:'completed',run_id:'group'}]}
 const runs=[{run_id:'prime'}, {run_id:'group',metadata:{batch_id:'B'}},{run_id:'extra',metadata:{batch_id:'B'}},{run_id:'other',experiment_name:'same name'}]
 assert.deepEqual(batchRunIds(batch,runs),['prime','group','extra'])
 const plan={batch_id:'B',request:{experiment_name:'test'},priming:{steps:[]},recipes:[]}
 const get=async(url:string)=>({data:url.endsWith('/plan')?plan:url.endsWith('/runs')?runs:runs.find(r=>url.endsWith('/'+r.run_id))})
 const result=await batchExport(batch,get)
 assert.equal(result.count,3)
 assert.equal(result.batch,batch)
 assert.equal(result.plan,plan)
 await assert.rejects(batchExport(batch,async url=>url.endsWith('/plan')?{data:{...plan,batch_id:'other'}}:get(url)),/快照/)
 await assert.rejects(batchExport(batch,async url=>{if(url.endsWith('/plan'))throw new Error('snapshot missing');return get(url)}),/snapshot missing/)
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

test('initial precursor reach accepts overshoot while formal stability and cooling keep their rules',()=>{
 const reading={read_ok:true,target:50,tolerance:null,value:50.8}
 for(const value of [50,50.8,56.1])assert.equal(temperatureReadingStatus({...reading,value},'heater_pair_reached'),'已达标')
 assert.equal(temperatureReadingStatus({...reading,value:49.99},'heater_pair_reached'),'等待达标')
 assert.equal(temperatureReadingStatus({...reading,target:60,value:56.1},'heater_pair_reached'),'等待达标')
 assert.equal(temperatureReadingStatus({...reading,read_ok:false,value:56.1},'heater_pair_reached'),'读取未确认')
 assert.equal(temperatureReadingStatus({...reading,target:null},'heater_pair_reached'),'最新读数')
 assert.equal(temperatureReadingStatus({...reading,tolerance:3,value:56.1},'heater_pair_stable'),'等待达标')
 assert.equal(temperatureReadingStatus({...reading,tolerance:3,value:47},'heater_pair_stable'),'已达标')
 assert.equal(temperatureReadingStatus({...reading,target:45,value:44.9},'microwave_temperature_below'),'已达标')
 assert.equal(temperatureReadingStatus({...reading,target:45,value:45.1},'microwave_temperature_below'),'等待达标')
})
