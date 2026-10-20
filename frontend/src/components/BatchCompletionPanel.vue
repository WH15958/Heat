<template>
  <div class="batch-completion" aria-label="本批实验已完成">
    <div class="completion-heading">
      <span class="completion-mark"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><circle cx="20" cy="20" r="17" stroke="currentColor" stroke-width="1.7"/><path d="m12 20 5 5 11-11" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
      <div><small>批次完成</small><h3>本批实验已完成</h3><p class="completion-name">{{ experimentName }}</p></div>
      <span class="completion-badge">流程已结束</span>
    </div>
    <div class="completion-facts">
      <div><small>完成实验组</small><strong>{{ completedCount }} <span>/ {{ totalCount }} 组</span></strong><p>各组条件与样品记录可在历史中查看</p></div>
      <div :class="{ 'record-warning': persistenceStatus !== 'ok' }"><small>实验记录</small><strong>{{ persistenceStatus === 'ok' ? '已保存' : persistenceStatus === 'error' ? '保存失败' : '保存状态未确认' }}</strong><p>{{ persistenceStatus === 'ok' ? '可查看本批历史或导出完整记录' : persistenceStatus === 'error' ? '请先处理记录恢复，再开始新实验' : '请核对记录保存结果' }}</p></div>
    </div>
    <div class="completion-actions"><el-button type="primary" @click="$emit('history')">查看本批历史</el-button><el-button :loading="exporting" @click="$emit('export')">导出本批记录</el-button></div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ experimentName: string; completedCount: number; totalCount: number; persistenceStatus?: string; exporting?: boolean }>()
defineEmits<{ history: []; export: [] }>()
</script>

<style scoped>
.batch-completion{position:relative;padding:28px;border:1px solid #bad7ee;border-radius:16px;background:linear-gradient(115deg,#e9f5ff,#f6fbff 65%,#edf6ff);overflow:hidden;color:#243e58}
.completion-heading{display:flex;gap:18px;align-items:center}.completion-mark{display:grid;place-items:center;flex-shrink:0;width:68px;height:68px;border:1px solid #c2dff5;border-radius:22px;background:#fff;color:#1777c3}.completion-mark svg{width:44px;height:44px}.completion-heading small{font-size:12px;color:#517f9e;letter-spacing:2px}.completion-heading h3{margin:7px 0;font-size:29px;line-height:1.35}.completion-name{margin:0;font-size:16px;line-height:1.7;overflow-wrap:anywhere;color:#516f88}.completion-badge{margin-left:auto;padding:7px 12px;border:1px solid #c6deed;border-radius:20px;background:#ffffffa8;color:#306a94;font-size:12px;white-space:nowrap}
.completion-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:26px 0 20px}.completion-facts>div{padding:18px;border:1px solid #dceaf5;border-radius:11px;background:#ffffffd9;min-width:0}.completion-facts small{font-size:12px;color:#68839b}.completion-facts strong{display:block;margin:10px 0;font-size:23px;line-height:1.4;overflow-wrap:anywhere}.completion-facts strong span{font-size:14px;font-weight:400;color:#6c849a}.completion-facts p{margin:0;font-size:12px;line-height:1.7;color:#688097}.completion-facts .record-warning{border-color:#dfc890}.record-warning strong{color:#91601f}.completion-actions{display:flex;gap:10px;flex-wrap:wrap}.completion-actions .el-button{margin:0}
@media(max-width:650px){.batch-completion{padding:20px}.completion-heading{display:grid;grid-template-columns:50px minmax(0,1fr);gap:12px;align-items:start}.completion-mark{width:50px;height:50px;border-radius:16px}.completion-mark svg{width:34px;height:34px}.completion-heading>div{min-width:0}.completion-heading h3{font-size:23px}.completion-name{font-size:14px}.completion-badge{grid-column:2;justify-self:start;margin-left:0}.completion-facts{grid-template-columns:1fr;gap:10px;margin:20px 0}.completion-facts>div{padding:14px}.completion-facts strong{font-size:21px;margin:6px 0}.completion-actions .el-button{flex:1;min-width:0}}
</style>
