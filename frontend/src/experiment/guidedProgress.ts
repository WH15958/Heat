export const stageNames=['初始化、加热与预充','正式进料前稳定到温','吸液与进料','微波升温与保温','降温与收集','清洗与排液']
export const stageIds=['preparation','stabilizing','feeding','reaction','collection','cleaning']
export const stagePaths=[
 'M9 3h6v4l3 3v10H6V10l3-3V3M8 14h8M10 17h4',
 'M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0M12 9v8',
 'M5 3l4 4M3 5l4 4M8 6l10 10-4 4L4 10M16 18l5 3M9 11l3-3',
 'M3 5h18v14H3V5M6 8h10v8H6V8M19 9v2M9 10l-1 2 2 2 1-2 2 2',
 'M7 3h10M9 3v6l-5 9v3h16v-3l-5-9V3M7 16h10',
 'M12 3C9 8 5 12 5 16a7 7 0 0 0 14 0c0-4-4-8-7-13M9 16a3 3 0 0 0 3 3',
]
export function activeStage(batch:any):number {
 const activity=batch.progress?.activity
 if(activity?.stage)return stageIds.indexOf(activity.stage)
 if(batch.phase==='priming'||batch.phase==='ready')return 0
 const id=batch.progress?.step_id||''
 if(id.startsWith('heat_'))return 1
 if(id.startsWith('aspirate_')||id==='feed_both')return 2
 if(id.startsWith('microwave_')||id==='hold')return 3
 if(id.startsWith('cool_')||id==='recheck_temperature'||id==='product_route'||id.startsWith('collect_'))return 4
 return id.startsWith('clean_')?5:-1
}
export function stageState(batch:any,index:number):string {
 const current=activeStage(batch), terminal=['completed','failed','stopped','interrupted'].includes(batch.state)
 if(index===0&&batch.priming?.status==='completed')return 'completed'
 if(batch.state==='completed'&&batch.phase!=='priming')return 'completed'
 if(index<current)return 'completed'
 if(index!==current)return 'pending'
 if(batch.cleanup_in_progress)return 'cleanup'
 if(terminal)return batch.state==='failed'?'failed':batch.state==='completed'?'completed':'stopped'
 if(batch.stop_requested)return 'stopping'
 if(batch.state==='paused')return 'paused'
 return batch.state==='running'?'running':'pending'
}
export function staleStatus(last:number,now:number,error:string){return !!error||!last||now-last>6000}
export function batchRunIds(batch:any,runs:any[]):string[]{
 return [...new Set<string>([batch.priming?.run_id,...(batch.groups||[]).map((g:any)=>g.run_id),
  ...runs.filter(r=>r.metadata?.batch_id===batch.batch_id).map(r=>r.run_id)].filter(Boolean))]
}
export async function batchExport(batch:any,get:(url:string)=>Promise<{data:any}>){
 if(batch.persistence_status==='error')throw new Error('本批记录保存失败，请先处理记录恢复')
 const {data:runs}=await get('/api/experiments/history/runs')
 const ids=batchRunIds(batch,runs)
 const expected=(batch.groups||[]).filter((g:any)=>g.state!=='pending').length+(batch.priming?.status==='completed'||batch.priming?.run_id?1:0)
 if(!ids.length||ids.length<expected)throw new Error('批次记录缺失，未导出；请检查预充及各组记录')
 const details=await Promise.all(ids.map(async id=>{
  const {data}=await get(`/api/experiments/history/runs/${encodeURIComponent(id)}`)
  if(data.run_id!==id||data.persistence_status==='error'||data.log_saved===false)throw new Error(`记录 ${id} 缺失或保存失败，未导出`)
  return data
 }))
 return {exported_at:new Date().toISOString(),batch_id:batch.batch_id,count:details.length,runs:details}
}

export function formatTemperature(value:unknown):string {
 return typeof value==='number'&&Number.isFinite(value)?`${value.toFixed(1)} ℃`:'温度未知'
}
