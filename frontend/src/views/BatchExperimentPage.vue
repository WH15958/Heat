<template>
  <div class="guided">
    <header><div><h2>{{ showProgress ? '实验进度' : '引导式实验' }}</h2><p>{{ showProgress ? '回零与预充 → 到温复查与进料 → 微波反应 → 降温与收集 → 清洗与换瓶 → 收尾回零' : '前驱体加热 → 进料 → 微波反应 → 降温与收集 → 清洗 → 预充与排气 → 批次确认' }}</p></div><div class="header-actions"><el-button @click="router.push('/experiment/batch')">返回实验入口</el-button><el-button v-if="batch.batch_id" @click="showProgress=!showProgress">{{ newDraft ? (showProgress ? '返回新实验设置' : '查看上次实验') : (showProgress ? '查看参数' : '查看实验进度') }}</el-button></div></header>
    <p v-if="draftNotice" role="status">{{ draftNotice }}</p>
    <nav v-if="!showProgress"><button v-for="(name,i) in stages" :key="name" :class="{active:stage===i}"  :disabled="i>stage" @click="goBack(i)"><b>{{ i+1 }}</b>{{ name }}</button></nav>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <section v-if="showProgress" class="run-panel" aria-label="实验进度">
      <div class="run-heading"><div><h3>{{ batch.experiment_name || batch.request?.experiment_name || batch.name || '未命名实验' }}</h3><p>{{ stateLabel }}</p><p class="batch-id">批次 {{ batch.batch_id }}</p></div><div class="run-actions">
        <el-button v-if="batch.state==='running'&&!batch.pause_pending" :disabled="controlsBusy" :loading="pendingControl==='pause'" @click="controlBatch('pause')">{{ pendingControl==='pause'?'请求暂停中':'暂停批次' }}</el-button>
        <el-button v-if="(batch.state==='paused'||batch.pause_pending)&&batch.phase!=='ready'" :disabled="controlsBusy" :loading="pendingControl==='resume'" @click="controlBatch('resume')">{{ batch.pause_pending ? '取消暂停请求' : '继续批次' }}</el-button>
        <el-button v-if="activeRun||batch.cleanup_pending" type="danger" :disabled="controlling||pendingControl==='stop'" :loading="pendingControl==='stop'" @click="controlBatch('stop')">{{ pendingControl==='stop'?'请求停止中':'停止本批次' }}</el-button>
        <el-button v-if="terminalRun&&!batch.recovery_required" :disabled="controlsBusy||batch.cleanup_pending||batch.persistence_status==='error'" type="primary" @click="returnToSetup()">新建实验</el-button>
        <el-button v-if="terminalRun&&!batch.recovery_required" :disabled="controlsBusy||batch.cleanup_pending||batch.persistence_status==='error'" @click="returnToSetup(true)">沿用本次参数新建</el-button>
        <el-button v-if="batch.phase==='ready'" @click="showProgress=false;stage=6">前往批次确认</el-button>
      </div></div>
      <el-alert v-if="stale" :title="refreshError||'状态已过期：超过 6 秒未收到更新，以下为最后一次确认的信息。'" type="warning" :closable="false" />
      <el-alert v-if="batch.pause_pending" :title="turntablePausePending(batch)?'已请求暂停：当前转盘动作继续监督，到位并确认停止后暂停；恢复不回零、不重复换瓶。':'已请求暂停：当前反应继续，停止微波后暂停；随后不收集、不清洗、不进入下一组。'" type="warning" :closable="false" />
      <el-alert v-else-if="batch.state==='paused'&&batch.phase!=='ready'" :title="['preparing','indexing','finishing'].includes(batch.phase)?'转盘阶段已暂停，保留当前位置与进度；恢复不重新回零、不重放动作。':batch.phase==='priming'?'预充已暂停；前驱体保持已启动的加热，已发出的泵动作完成后等待继续。':'实验已暂停，等待继续；前驱体加热器保持保温。'" type="info" :closable="false" />
      <el-alert v-if="batch.error" :title="batch.error" type="error" :closable="false" />
      <el-alert v-if="finalizationFailed" :title="'实验组已完成，收尾回零失败。已完成样品记录保留；请现场检查后解除恢复锁定。'+(batch.finalization.error||'')" type="error" :closable="false" />
      <el-alert v-if="batch.persistence_status==='error'" title="记录保存失败，禁止继续运行" type="error" :closable="false" />
      <el-alert v-if="batch.state==='completed'&&batch.cleanup_pending" title="实验流程已结束，设备清理仍待确认。" type="warning" :closable="false" />
      <div v-if="batch.recovery_required" class="notice"><p>需要现场检查设备停止、残留、液路和已用产物瓶。停止或故障后转盘保留当前位置，不自动回零；解除恢复锁定仅允许新建批次，不续跑原批次。下次启动重新确认空瓶并机械回零。</p><el-button type="warning" :disabled="controlling" @click="acknowledgeInterrupted">现场已检查，解除锁定</el-button></div>
      <BatchCompletionPanel v-if="batchCompleted" :experiment-name="batch.experiment_name || batch.request?.experiment_name || batch.name || '未命名实验'" :completed-count="completedGroups" :total-count="batch.total_groups || 0" :persistence-status="batch.persistence_status" :exporting="exportingBatch" @history="openBatchHistory" @export="exportBatch" />
      <component :is="batchCompleted?'details':'div'" class="current-operation" :class="{stale,'completed-snapshot':batchCompleted}" :aria-label="batchCompleted?'最后动作记录':'当前动作'">
        <summary v-if="batchCompleted">查看最后动作与读数</summary>
        <div class="activity-heading"><div><small>{{ terminalRun ? '最后动作快照' : '当前动作' }}</small><h3>{{ operationTitle }}</h3><p>{{ operationDescription }}</p></div><span class="activity-status">{{ stale?'状态过期':batch.cleanup_in_progress?'正在清理':batch.stop_requested&&!terminalRun?'正在停止':stateLabel }}</span></div>
        <p v-if="controlFeedback" class="control-feedback" role="status">{{ controlFeedback }} <el-button v-if="controlUncertain" size="small" @click="refreshBatch(true)">核对最新状态</el-button></p>
        <div class="activity-readings">
          <div v-for="reading in activity?.readings||[]" :key="reading.device_id" class="reading"><small>{{ deviceLabel(reading.device_id) }}</small><strong>{{ reading.read_ok ? formatTemperature(reading.value) : '温度未知' }}</strong><span v-if="reading.target!=null">目标 {{ activity?.wait_type==='heater_pair_reached'?'≥':activity?.wait_type==='microwave_temperature_below'?'≤':'' }}{{ reading.target }} ℃{{ reading.tolerance!=null?' ±'+reading.tolerance+'℃':'' }}</span><b>{{ temperatureReadingStatus(reading,activity?.wait_type) }}</b></div>
          <div v-if="activity?.stable_required_seconds!=null && !['microwave_temperature_reached','heater_pair_reached'].includes(activity.wait_type)" class="reading"><small>双路连续稳定</small><strong>{{ seconds(activity.stable_seconds) }} / {{ seconds(activity.stable_required_seconds) }}</strong><span>任一路越界或暂停后重新计时</span></div>
          <MicrowaveHoldProgress :activity="activity" />
          <div v-if="activity?.duration_seconds!=null && activity.qualified_seconds==null && activity.hold_mode!=='timed'" class="reading"><small>{{ activity.wait_type==='flow_duration'?'流量排液剩余':activity.reference?'设定时长参考剩余':'有效计时剩余' }}</small><strong>{{ seconds(activity.remaining_seconds) }}</strong><span>{{ activity.reference?(activity.remaining_seconds===0&&activity.state!=='completed'?'等待设备完成确认':activity.wait_type==='flow_duration'?'软件到时主动停泵；暂停不延长排液':'从设备启动确认后计时，不表示动作完成'):'暂停期间不计时' }}</span><span>设定 {{ seconds(activity.duration_seconds) }}</span></div>
          <div v-for="(device,id) in activity?.devices||{}" :key="id" class="reading"><small>{{ deviceLabel(String(id)) }}</small><strong>{{ device.read_ok!==true?'状态未知':device.relay_energized!=null?'已确认 '+(device.relay_energized?'NC':'NO'):device.busy===true||device.running===true||device.control_active===true?'设备运行中':device.result==='completed'?'动作已完成':device.running===false?'设备已停止':'等待设备确认' }}</strong><span v-for="feed in (activity?.feeds||[]).filter((f:any)=>f.device_id===id)" :key="feed.device_id">设定进样量 {{ feed.volume }} {{ feed.unit }}</span><span v-if="device.fault_code">故障码 {{ device.fault_code }}</span></div>
          <div v-if="Object.keys(activity?.parameters||{}).length||(!(activity?.readings?.length)&&!Object.keys(activity?.devices||{}).length)" class="reading"><small>相关设备 / 参数</small><strong>{{ activity?.device_ids?.map(deviceLabel).join(' / ')||currentDevice }}</strong><span v-if="activity?.parameters?.target_temperature!=null">目标 {{ activity.parameters.target_temperature }} ℃</span><span v-if="activity?.parameters?.temperature!=null">目标 {{ activity.parameters.temperature }} ℃</span><span v-if="activity?.parameters?.channel">通道 {{ activity.parameters.channel }}</span><span v-if="activity?.parameters?.flow_rate!=null">{{ activity.parameters.flow_rate }} mL/min</span><span v-if="activity?.parameters?.volume!=null">{{ activity.parameters.volume }} {{ activity.parameters.unit||'mL' }}</span><span v-if="activity?.parameters?.position">出口 {{ activity.parameters.position }}</span></div>
        </div>
      </component>
      <div v-if="batch.turntable" class="turntable-progress" aria-label="产物收集转盘状态">
        <div><small>最近确认瓶位</small><strong>{{ turntableBottleLabel(batch.turntable.current_bottle) }}</strong></div>
        <div><small>目标瓶位</small><strong>{{ turntableBottleLabel(batch.turntable.target_bottle) }}</strong></div>
        <div><small>转盘动作</small><strong>{{ turntableOperationLabel }}</strong></div>
        <div><small>批次收尾</small><strong>{{ finalizationLabel }}</strong></div>
        <p>瓶位以后台确认结果为准，未知时不推算。暂停保留进度；停止或故障原位停机，不自动回零。</p>
      </div>
      <ol class="run-stages" aria-label="本组阶段" :data-active-stage="executionStage"><li v-for="(name,i) in executionStages" :key="name" :class="stageState(stageBatch,i)" :aria-current="stageState(stageBatch,i)==='running'?'step':undefined"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="stageState(stageBatch,i)==='completed'?'M5 12l4 4L19 6':stageState(stageBatch,i)==='paused'?'M8 5v14M16 5v14':stageState(stageBatch,i)==='failed'?'M12 4v10M12 18v2':stagePaths[i]" /></svg><strong>{{ name }}</strong><small>{{ stageLabels[stageState(stageBatch,i)] }}</small></li></ol>
      <div class="run-summary">
        <div><small>整批完成组数</small><strong>{{ completedGroups }} / {{ batch.total_groups || 0 }}</strong><progress :value="completedGroups" :max="batch.total_groups||1" aria-label="已完成实验组数"></progress></div>
        <div><small>当前实验组</small><strong>{{ ['preparing','priming','ready'].includes(batch.phase) ? '批次准备' : batch.phase==='finishing' ? '批次收尾' : `第 ${batch.current_group || 0} 组` }}</strong><span>{{ phaseLabel }}</span></div>
        <div><small>整批累计用时</small><strong>{{ elapsedLabel }}</strong><span>{{ terminalRun ? '已结束 · 用时已固定' : '含暂停时间' }} · 状态每 2 秒更新 · {{ lastRefresh ? new Date(lastRefresh).toLocaleTimeString() : '等待状态' }}</span></div>
      </div>
      <div v-if="terminalRun&&!batchCompleted" class="result-summary"><h4>批次结果</h4><p>完成 {{ resultCounts.completed }} 组 · 失败 {{ resultCounts.failed }} 组 · 未执行 {{ resultCounts.unexecuted }} 组<span v-if="batch.state==='stopped'"> · 中途停止的组请查看下方记录</span></p><p>记录：{{ batch.persistence_status==='ok'?'已保存':batch.persistence_status==='error'?'保存失败，请处理记录恢复':'保存状态未确认' }} · {{ batch.recovery_required?'需现场检查并解除恢复锁定':batch.cleanup_pending?'设备清理未确认':'无待处理恢复事项' }}</p><el-button @click="openBatchHistory">查看本批历史</el-button><el-button :loading="exportingBatch" @click="exportBatch">导出本批记录</el-button></div>
      <div v-if="batch.phase==='priming'||batch.phase==='ready'" class="notice">已完成预充循环：A {{ batch.priming?.completed_cycles?.[0] || 0 }} / {{ batch.request?.prime_cycles || '—' }} 次，B {{ batch.priming?.completed_cycles?.[1] || 0 }} / {{ batch.request?.prime_cycles || '—' }} 次。初始化与预充每批只执行一次。</div>
      <div class="group-toolbar"><h4>各组进度与实验条件</h4><el-button @click="showCompleted=!showCompleted">{{ showCompleted?'折叠已完成组':'展开全部' }}</el-button><el-button @click="locateCurrent">定位当前组</el-button></div><div class="table run-table"><table><thead><tr><th>组号</th><th>状态</th><th>A / B 温度（℃）</th><th>A / B 进料量（mL）</th><th>反应温度（℃）</th><th>保温（分钟）</th><th>样品编号</th><th>产物瓶</th><th>收取状态</th></tr></thead><tbody><tr v-for="g in visibleGroups" :key="g.index" :class="{selected:g.index===batch.current_group}"><td>{{ g.index }}</td><td>{{ labels[g.state] || g.state }}</td><td>{{ g.parameters[0] ?? '—' }} / {{ g.parameters[1] ?? '—' }}</td><td>{{ g.parameters[2] ?? '—' }} / {{ g.parameters[3] ?? '—' }}</td><td>{{ g.parameters[4] ?? '—' }}</td><td>{{ g.parameters[5] ?? '—' }}</td><td>{{ g.sample_id || '—' }}</td><td>{{ g.bottle_number==null ? '未记录' : turntableBottleLabel(g.bottle_number) }}</td><td>{{ collectionStatusLabel(g.collection_status) }}<small v-if="g.collection_error" class="collection-error">{{ g.collection_error }}</small></td></tr></tbody></table></div>
      <p><small>整批进度按完成组数统计。升温和降温耗时取决于实测温度；不估算剩余完成时间。每组使用独立瓶位；清洗、停泵和滴液等待完成后自动换瓶，最后一组结束后回零。</small></p>
    </section>
    <div v-else class="layout"><main :inert="activeRun">
      <section v-if="stage<=2"><label v-if="stage===0" class="experiment-name">实验名称<input data-field="experimentName" :aria-invalid="!!fieldErrors.experimentName" v-model="experimentName" placeholder="请输入实验名称" /><small v-if="fieldErrors.experimentName" class="field-error" role="alert">{{ fieldErrors.experimentName }}</small></label><h3>{{ stages[stage] }}</h3><p>{{ stageDescriptions[stage] }}</p><div class="notice device-summary">{{ deviceSummary }}</div><div v-for="a in stageAxes" :key="a.key" class="axis" :data-field="a.key"><div class="axis-heading"><strong>{{ a.label }}</strong><span>实验条件</span></div><p v-if="fieldErrors[a.key]" class="field-error" role="alert">{{ fieldErrors[a.key] }}</p><div class="axis-controls"><label>设置方式<select v-model="a.mode"><option value="fixed">固定值</option><option value="range">范围与间隔</option><option value="list">指定数值</option></select></label><label v-if="a.mode!=='list'">{{ a.mode==='fixed'?'数值':'起点' }}<span class="number-unit"><input v-model.number="a.start" :aria-invalid="!!fieldErrors[a.key]" type="number" step="any" placeholder="请输入" /><span>{{ a.unit }}</span></span></label><template v-if="a.mode==='range'"><label>终点<span class="number-unit"><input v-model.number="a.end" :aria-invalid="!!fieldErrors[a.key]" type="number" step="any" placeholder="请输入" /><span>{{ a.unit }}</span></span></label><label>间隔<span class="number-unit"><input v-model.number="a.interval" :aria-invalid="!!fieldErrors[a.key]" type="number" step="any" placeholder="请输入" /><span>{{ a.unit }}</span></span></label></template><label v-if="a.mode==='list'">逗号分隔<span class="number-unit"><input v-model="a.list" :aria-invalid="!!fieldErrors[a.key]" placeholder="多个数值用逗号分隔" /><span>{{ a.unit }}</span></span></label></div></div><div v-if="stage===1" class="grid settings"><label>A 进料速度<span class="number-unit"><input data-field="speedA" :aria-invalid="!!fieldErrors.speedA" v-model.number="speedA" type="number" placeholder="请输入" /><span>Hz</span></span><small v-if="fieldErrors.speedA" class="field-error" role="alert">{{ fieldErrors.speedA }}</small></label><label>B 进料速度<span class="number-unit"><input data-field="speedB" :aria-invalid="!!fieldErrors.speedB" v-model.number="speedB" type="number" placeholder="请输入" /><span>Hz</span></span><small v-if="fieldErrors.speedB" class="field-error" role="alert">{{ fieldErrors.speedB }}</small></label></div><p>支持固定值、范围与间隔或指定数值。请按实际实验填写。</p></section>
      <section v-if="stage===3"><h3>降温与产物收集</h3>
        <div class="notice compact-notice"><strong>反应液 ≤45℃ 后自动收集</strong><p>NO 收产物，NC 排废液；转盘自动切换产物瓶，每组独立用瓶。</p><small>流量和时间按现场标定，时间需覆盖死体积与排空余量。</small></div>
        <p><small>三通阀：{{ valveConfigured ? '已配置' : '配置缺失' }} · {{ registry.valves?.valve1?.connected ? '已连接' : '未连接' }}（继电器读回）</small></p>
        <p><small>产物转盘：{{ turntableConfigError || `已配置 ${bottleCount} 个瓶位` }}。机械原点对应 1 号瓶；本批最多 {{ bottleCount || '—' }} 组，不循环复用。</small></p>
        <p v-if="batch.request?.product_port==='NC'" class="notice compact-notice">历史批次仅供查阅；新批次须按 NO 收产物、NC 排废液重新确认并预充。</p>
        <div class="grid compact-fields"><label v-for="item in fixed.slice(0,2)" :key="item.key">{{ item.label }}<span class="number-unit"><input :data-field="item.key" :aria-invalid="!!fieldErrors[item.key]" v-model.number="item.value" type="number" step="any" placeholder="请输入" /><span>{{ item.unit }}</span></span><small v-if="fieldErrors[item.key]" class="field-error" role="alert">{{ fieldErrors[item.key] }}</small></label></div>
        <p><small>建议流量 15 mL/min，抽液 5 分钟（300 秒）。</small></p>
        <p><small>清洗排液沿用此流量，排液时间分别设置。</small></p>
        <label class="direction-field">排液方向<select v-model="drainDirection"><option value="CW">顺时针（CW）</option><option value="CCW">逆时针（CCW）</option></select></label>
      </section>
      <section v-if="stage===4"><h3>清洗与排液</h3><p>通道三进液，通道四排液。</p>
        <div class="form-group"><h4>清洗进液 · 通道三</h4>
          <div class="grid compact-fields"><label v-for="item in fixed.slice(2,6)" :key="item.key">{{ item.label }}<span class="number-unit"><input :data-field="item.key" :aria-invalid="!!fieldErrors[item.key]" v-model.number="item.value" type="number" step="any" placeholder="请输入" /><span>{{ item.unit }}</span></span><small v-if="fieldErrors[item.key]" class="field-error" role="alert">{{ fieldErrors[item.key] }}</small></label></div>
          <label class="direction-field settings">清洗进液方向<select v-model="cleanDirection"><option value="CW">顺时针（CW）</option><option value="CCW">逆时针（CCW）</option></select></label>
        </div>
        <div class="form-group"><h4>清洗排液 · 通道四</h4>
          <div class="grid compact-fields"><label v-for="item in fixed.slice(6)" :key="item.key">{{ item.label }}<span class="number-unit"><input :data-field="item.key" :aria-invalid="!!fieldErrors[item.key]" v-model.number="item.value" type="number" step="any" placeholder="请输入" /><span>{{ item.unit }}</span></span><small v-if="fieldErrors[item.key]" class="field-error" role="alert">{{ fieldErrors[item.key] }}</small></label><label>排液流量<span class="readonly-value">{{ Number.isFinite(setting('drainFlow')) ? setting('drainFlow') : '待填写' }} mL/min</span><small>沿用产物收集设置</small></label></div>
          <p><small>建议流量 15 mL/min，抽液 5 分钟（300 秒）。</small></p>
        </div>
        <div class="notice compact-notice">切 NC → 进液 → 停留 → 排液，按次数重复。</div>
        <div class="form-group"><h4>清洗后的自动换瓶</h4><p>清洗结束后，确认泵停止且阀在 NC，再等待残余滴液，最后切换下一瓶；最后一组在收尾回零前同样等待。</p><label class="direction-field">滴液等待时间<span class="number-unit"><input data-field="turntableDripSeconds" :aria-invalid="!!fieldErrors.turntableDripSeconds" v-model.number="turntableDripSeconds" type="number" min="0" max="3600" step="any" placeholder="按现场标定填写" /><span>秒</span></span><small v-if="fieldErrors.turntableDripSeconds" class="field-error" role="alert">{{ fieldErrors.turntableDripSeconds }}</small></label><p><small>按实际管路标定，允许明确填写 0；等待时间不证明管内已排空。</small></p></div>
      </section>
      <section v-if="stage===5">
        <h3>批次准备</h3>
        <p>先确认停泵、NC 流路并将转盘回零至 1 号瓶，再初始化 A/B，按第一组目标加热；两路均达到或超过各自目标后，立即开始计时保温脱气，设定时间结束后预充。前驱体持续保温；预充液 ≤45℃ 后排废，每批一次。</p>
        <div class="form-group initialization-group"><h4>泵初始化</h4><div class="grid"><div v-for="(item,i) in initialization" :key="i" class="pump-initialization"><strong>泵 {{ i===0?'A':'B' }}</strong><label>方向<select v-model="item.direction"><option value="Z">Z：左吸右排</option><option value="Y">Y：右吸左排</option></select></label><label>代码<select v-model.number="item.initialization_code"><option v-for="code in initializationCodes" :key="code" :value="code">{{ code }}</option></select></label></div></div></div>
        <div class="form-group"><h4>预充与排气</h4>
          <label class="preheat-field">到温后等待时间<span class="number-unit"><input data-field="primeHeatMinutes" :aria-invalid="!!fieldErrors.primeHeatMinutes" v-model.number="primeHeatMinutes" type="number" min="0" max="1440" step="any" placeholder="请输入" /><span>分钟</span></span><small v-if="fieldErrors.primeHeatMinutes" class="field-error" role="alert">{{ fieldErrors.primeHeatMinutes }}</small></label>
          <p><small>两路实测温度均达到或超过各自目标后立即计时，无需稳定30秒，暂停不计时；到温等待最多60分钟。填0表示到温后不额外等待。</small></p>
          <div class="grid compact-fields"><label v-for="p in priming.slice(0,5)" :key="p.key">{{ p.label }}<span class="number-unit"><input :data-field="p.key" :aria-invalid="!!fieldErrors[p.key]" v-model.number="p.value" type="number" :step="p.key==='prime_cycles'?1:'any'" placeholder="请输入" /><span>{{ p.unit }}</span></span><small v-if="fieldErrors[p.key]" class="field-error" role="alert">{{ fieldErrors[p.key] }}</small></label></div>
          <p><small>建议流量 15 mL/min，抽液 5 分钟（300 秒）。</small></p>
          <p v-if="Number.isFinite(primeTotal)&&primeTotal>0"><small>预充耗液 / 废液 {{ primeTotal }} mL · 出口 {{ wastePort }}</small></p>
        </div>
        <details class="form-group" :open="advancedOpen" @toggle="advancedOpen=($event.target as HTMLDetailsElement).open">
          <summary>可用容量 <span v-if="advancedMissing">· 待填写</span></summary>
          <div class="grid compact-fields settings"><label v-for="p in priming.slice(5)" :key="p.key">{{ p.label }}<span class="number-unit"><input :data-field="p.key" :aria-invalid="!!fieldErrors[p.key]" v-model.number="p.value" type="number" step="any" placeholder="请输入" /><span>{{ p.unit }}</span></span><small v-if="fieldErrors[p.key]" class="field-error" role="alert">{{ fieldErrors[p.key] }}</small></label></div>
          <p><small>按现场余量填写，预留防吸空和防溢出空间。</small></p>
        </details>
        <p>下一步确认批次，校验后即可开始自动实验。</p>
        <p v-if="primeReady">已有本批次预充结果，开始自动实验时将沿用，不重复初始化或预充。修改参数或维护设备前请先停止批次。</p>
        <details><summary>预充流程预览</summary><pre>{{ previewPrime }}</pre></details>
      </section>
      <section v-if="stage===6"><p>实验名称：{{ experimentName.trim() }}</p><h3>批次确认<span v-if="!plan.error"> · {{ plan.rows.length }} 组</span></h3><label class="settings">每个条件重复次数<span class="number-unit"><input data-field="repeats" :aria-invalid="!!fieldErrors.repeats" v-model.number="repeats" type="number" min="1" placeholder="请输入" /><span>次</span></span><small v-if="fieldErrors.repeats" class="field-error" role="alert">{{ fieldErrors.repeats }}</small></label><div class="table"><table><thead><tr><th>组号</th><th v-for="a in axes" :key="a.key">{{ a.label }} / {{ a.unit }}</th><th>产物排液时间（秒）</th><th>产物瓶</th></tr></thead><tbody><tr v-for="(row,i) in plan.rows" :key="i" :class="{selected:selected===i}" @click="selected=i"><td>{{ i+1 }}</td><td v-for="(v,j) in row" :key="j">{{ v }}</td><td>{{ setting('productTime') }}</td><td>{{ i+1 }} 号瓶</td></tr></tbody></table></div><p>本批 {{ plan.rows.length || '—' }} 组，对应 1–{{ plan.rows.length || '—' }} 号瓶；最多 {{ bottleCount || '—' }} 组，不循环复用。启动先机械回零至 1 号瓶，再执行初始化与预充。</p><h4>每组固定流程</h4><ol><li>前驱体 A/B 加热，两路同时在各自目标 ±3℃ 内持续 30 秒后才开始吸液与进料。</li><li>两泵各自吸取剂量，再并行进料、各自完成；任一路失败停止两路。</li><li>两路进料完成后微波升温，到温后保温，结束后停止微波；前驱体 A/B 加热器持续保温。</li><li>产物留在微波仪中降温，等待反应液实测温度降至 45℃及以下；读取失败或超时不进入抽液。</li><li>收取前复查温度 ≤45℃，阀切 NO 产物端，按填写时间抽取产物。</li><li>先切 NC 废液端，再注清洗液、停留、按填写时间排清洗液，按次数重复。</li><li>本组清洗完成后确认泵停止、阀在 NC，等待设定滴液时间，再转到下一瓶并确认到位；加热器保持运行，新组按目标调整温度。最后一组结束后停机并机械回零。失败或停止时原位停机，不自动回零。</li></ol><el-button :loading="validating" :disabled="!!plan.error" @click="validate">生成并校验完整批次</el-button><p role="status">{{ report }}</p><details><summary>第 {{ selected+1 }} 组操作预览</summary><p>此处仅预览本组操作；批次回零与换瓶由整批流程执行。校验不连接或启动硬件。</p><pre>{{ fragment }}</pre></details></section>
    </main><aside class="batch-sidebar">
      <h3>本批实验</h3>
      <template v-if="validatedKey===requestKey&&!plan.error">
        <div class="batch-count"><strong>{{ plan.rows.length }}</strong><span>组实验</span><small>已校验</small></div>
        <details class="batch-details"><summary>用量与收集准备</summary>
          <dl><div><dt>A 液（含预充）</dt><dd>{{ total(2)+primeValue('prime_volume_a')*primeValue('prime_cycles') }} mL</dd></div><div><dt>B 液（含预充）</dt><dd>{{ total(3)+primeValue('prime_volume_b')*primeValue('prime_cycles') }} mL</dd></div><div><dt>清洗液</dt><dd>{{ Number((plan.rows.length*setting('volume')*setting('cycles')).toPrecision(10)) }} mL</dd></div><div><dt>产物瓶</dt><dd>{{ plan.rows.length }} 个</dd></div></dl>
          <small>用量为理论值；启动前一次备齐空瓶，批内不重复使用。</small>
        </details>
      </template>
      <div v-else class="batch-placeholder"><strong>待完成设置</strong><p>校验参数后显示组数与用量。</p></div>
      <div v-if="stage===6" class="preflight-summary">
        <h4>执行前确认</h4>
        <p>请先连接设备，再逐项核对。启动时系统会检查设备就绪状态。</p>
        <div class="plumbing-summary"><span>NO · 收产物</span><span>NC · 排废液</span></div>
        <label class="confirm-check"><input v-model="plumbingConfirmed" type="checkbox" :disabled="activeRun||controlling" />已核对接管、泵向及微波负载</label>
        <label class="confirm-check"><input v-model="primingConfirmed" type="checkbox" :disabled="activeRun||controlling" />已核对设备、容量及前驱体相容性</label>
        <label class="confirm-check"><input v-model="initializationConfirmed" type="checkbox" :disabled="activeRun||controlling" />已核对初始化方向与代码，允许活塞运动、切阀及预充耗液</label>
        <label class="confirm-check" data-field="bottlesConfirmed"><input v-model="bottlesConfirmed" type="checkbox" :disabled="activeRun||controlling" />已将本批所需 {{ plan.rows.length || '—' }} 个产物瓶清空并按编号就位，允许转盘自动回零与换瓶</label><small v-if="fieldErrors.bottlesConfirmed" class="field-error" role="alert">{{ fieldErrors.bottlesConfirmed }}</small>
        <small>修改参数后，需重新校验并勾选全部确认；运行中不逐组等待换瓶。</small>
        <details class="batch-details"><summary>查看启动说明</summary><p>请先连接全部设备，并将本批所需空瓶按编号摆放。系统先确认泵停止、阀在 NC，再机械回零到 1 号瓶；随后按预充页确认的方向与代码依次初始化两台注射泵，按第一组目标加热，两路均达到或超过各自目标后立即计时保温脱气，设定时间结束后预充、排液；随后再次确认稳定到温并开始进料。反应液降至 45℃及以下后自动收集。</p></details>
      </div>
      <template v-if="stage===6">
        <el-button type="primary" :loading="controlling" :disabled="controlling||!!startBlockReason" aria-describedby="start-status" @click="startBatch">开始自动实验</el-button>
        <p id="start-status" class="start-caption" role="status">{{ controlling ? '正在处理启动请求…' : startBlockReason || '确认启动后先回零，再自动预充和实验' }}</p>
      </template>
      <p v-else class="start-caption">完成参数设置后，在“批次确认”页统一确认并启动。</p>
    </aside></div>
    <footer v-if="!showProgress"><el-button :disabled="stage===0" @click="goBack(stage-1)">上一步</el-button><el-button v-if="stage<6" type="primary" @click="nextStage">{{ stage===5?'批次确认':'下一步' }}</el-button></footer>
  </div>
</template>
<script setup lang="ts">
import MicrowaveHoldProgress from '../components/MicrowaveHoldProgress.vue'
import BatchCompletionPanel from '../components/BatchCompletionPanel.vue'
import {computed,nextTick,onMounted,onUnmounted,reactive,ref,watch} from 'vue'
import {ElMessageBox} from 'element-plus'
import {useRoute,useRouter} from 'vue-router'
import axios from 'axios'
import {usePendingConfirmation} from '../composables/pendingConfirmation'
const confirmations=usePendingConfirmation()
import {combinations,valuesFor as axisValues,microwaveHoldSeconds,type Axis} from '../experiment/batch'
import {estimateDrainSeconds} from '../experiment/drainEstimate'
import {primingDrainForDisplay} from '../experiment/priming'
import {activeStage,stageState,stageNames,stagePaths,staleStatus,batchExport,formatTemperature,temperatureReadingStatus,batchCompletionConfirmed,collectionStatusLabel,turntableBottleLabel,batchElapsedLabel} from '../experiment/guidedProgress'
const router=useRouter(),stage=ref(0),selected=ref(0),error=ref(''),report=ref(''),validating=ref(false)
const route=useRoute(),newDraft=ref(route.query.new==='1'),experimentName=ref('')
const stages=['前驱体加热','前驱体进料','微波反应','产物收集','清洗与排液','预充与排气','批次确认']
const stageDescriptions=['设置加热器 A/B 的目标温度，两路同时在各自目标 ±3℃ 内持续 30 秒后才开始吸液与进料。同批次持续保温（含反应、清洗、组间和暂停），下一组按新目标调整；结束、失败或停止时关闭。','分别设置 A/B 进样量和速度；双泵同时开始、各自完成。','两路进料完成后启动微波；反应液在目标 ±3℃ 内连续稳定 30 秒后开始定时保温，之后温度偏离不暂停计时，仍持续检查故障和控制状态。保温分钟须可转换为整秒，例如 0.5 分钟为 30 秒。']
const stageAxes=computed(()=>axes.value.slice(stage.value*2,stage.value*2+2))
const deviceSummary=computed(()=>stage.value===0?'加热器一：前驱体 A　｜　加热器二：前驱体 B':stage.value===1?'注射泵一：前驱体 A　｜　注射泵二：前驱体 B':'微波仪一：反应温区')
const roles=[{key:'heaterA',label:'前驱体 A 加热器',group:'heaters',description:'前驱体储液加热'},{key:'heaterB',label:'前驱体 B 加热器',group:'heaters',description:'独立温区'},{key:'pumpA',label:'前驱体 A 注射泵',group:'syringe_pumps',description:'进样量与速度独立设置'},{key:'pumpB',label:'前驱体 B 注射泵',group:'syringe_pumps',description:'同时进料、各自完成'},{key:'reaction',label:'微波反应装置',group:'microwaves',description:'测得物料到温后计时'},{key:'liquid',label:'清洗与排液蠕动泵',group:'pumps',description:'不同通道负责进液和排液'},{key:'turntable',label:'产物收集转盘',group:'turntables',description:'每组使用独立产物瓶'}]
const registry=ref<Record<string,Record<string,any>>>({}),chosen=reactive<Record<string,string>>({heaterA:'heater1',heaterB:'heater2',pumpA:'syringe_pump1',pumpB:'syringe_pump2',reaction:'microwave1',liquid:'pump1',turntable:'turntable1'})
type InputNumber = number | null | ''
type FormAxis = Omit<Axis,'start'|'end'|'interval'> & {start:InputNumber;end:InputNumber;interval:InputNumber;unit:string}
const numeric=(value:InputNumber):number=>typeof value==='number'&&Number.isFinite(value)?value:NaN
const completeAxis=(a:FormAxis):Axis=>({...a,start:numeric(a.start),end:numeric(a.end),interval:numeric(a.interval)})
const valuesFor=(a:FormAxis)=>axisValues(completeAxis(a))
const axes=ref<FormAxis[]>([['ta','前驱体 A 温度','℃'],['tb','前驱体 B 温度','℃'],['va','A 进样量','mL'],['vb','B 进样量','mL'],['tr','微波反应温度','℃'],['time','保温时间','分钟']].map(([key,label,unit])=>({key:key!,label:label!,unit:unit!,value:0,paths:[],mode:'fixed',start:null,end:null,interval:null,list:''})))
const productPort='NO'
const wastePort='NC'
const valveConfigured=computed(()=>!!registry.value.valves?.valve1)
const turntableConfig=computed(()=>registry.value.turntables?.turntable1)
const bottleCount=computed(()=>Number.isInteger(turntableConfig.value?.bottle_count)&&turntableConfig.value.bottle_count>1?turntableConfig.value.bottle_count:0)
const turntableConfigError=computed(()=>{
 const config=turntableConfig.value
 if(!config||config.configured===false||config.enabled===false)return '固定转盘 turntable1 未配置或未启用'
 if(!bottleCount.value||!Number.isInteger(config.pulses_per_bottle)||config.pulses_per_bottle<=0)return '转盘瓶位配置无效，请检查瓶数与每瓶脉冲数'
 return config.home_enabled===true&&config.position_encoding_verified===true?'':'转盘机械回零或定位功能尚未启用'
})
const turntableDripSeconds=ref<InputNumber>(null),bottlesConfirmed=ref(false)
const repeats=ref<InputNumber>(null),speedA=ref<InputNumber>(null),speedB=ref<InputNumber>(null),cleanChannel=ref(3),drainChannel=ref(4)
type NumberField={key:string;label:string;unit:string;value:InputNumber}
const fixed=ref<NumberField[]>([
 {key:'drainFlow',label:'排液流量',unit:'mL/min',value:null},
 {key:'productTime',label:'产物排液时间',unit:'秒',value:null},
 {key:'flow',label:'清洗进液流量',unit:'mL/min',value:null},
 {key:'volume',label:'每次清洗液量',unit:'mL',value:null},
 {key:'wait',label:'清洗停留时间',unit:'秒',value:null},
 {key:'cycles',label:'每组清洗次数',unit:'次',value:null},
 {key:'cleanTime',label:'清洗排液时间',unit:'秒',value:null}
])
const setting=(key:string)=>numeric(fixed.value.find(s=>s.key===key)!.value)
const plan=computed(()=>{try{if(!Number.isInteger(repeats.value)||numeric(repeats.value)<1)throw new Error('重复次数须为正整数');const rows=combinations(axes.value.map(completeAxis));if(turntableConfigError.value)throw new Error(turntableConfigError.value);if(rows.length*numeric(repeats.value)>bottleCount.value)throw new Error(`本批最多 ${bottleCount.value} 组，每组独立用瓶，不循环复用`);if(rows.some(r=>r.some((v,i)=>i===2||i===3?v<=0:v<0)))throw new Error('进样量须大于零，温度与时间不能为负');if(rows.some(r=>!Number.isInteger(r[4])))throw new Error('微波目标温度须为整数℃');rows.forEach(r=>microwaveHoldSeconds(r[5]!));return{rows:rows.flatMap(r=>Array.from({length:numeric(repeats.value)},()=>r)),counts:axes.value.map(a=>valuesFor(a).length),error:''}}catch(e){return{rows:[] as number[][],counts:[] as number[],error:String(e)}}})
function goBack(i:number){if(i>=0&&i<=stage.value){stage.value=i;error.value=''}}
const fieldErrors=ref<Record<string,string>>({})
type FieldIssue={key:string;stage:number;message:string}
function fieldIssues(through:number):FieldIssue[]{
 const issues:FieldIssue[]=[]
 const add=(key:string,page:number,message:string)=>issues.push({key,stage:page,message})
 if(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(experimentName.value)||Array.from(experimentName.value.trim()).length<1||Array.from(experimentName.value.trim()).length>80)add('experimentName',0,'请填写 1–80 个字符的实验名称，不含换行或控制字符')
 axes.value.slice(0,Math.min(through+1,3)*2).forEach((a,i)=>{
  try{const values=valuesFor(a);if(values.some(v=>i===2||i===3?v<=0:v<0))throw new Error('请填写有效数值');if(i===4&&values.some(v=>!Number.isInteger(v)))throw new Error('微波目标温度须为整数℃');if(i===5)values.forEach(microwaveHoldSeconds)}catch(e){add(a.key,Math.floor(i/2),(e as Error).message)}
 })
 if(through>=1)for(const [key,value] of [['speedA',speedA.value],['speedB',speedB.value]] as const)if(!Number.isInteger(value)||numeric(value)<5||numeric(value)>5000)add(key,1,'速度须为 5–5000 的整数步频')
 if(through>=3)for(const f of fixed.value.filter(f=>through>=4||['drainFlow','productTime'].includes(f.key))){
  const value=numeric(f.value),page=['drainFlow','productTime'].includes(f.key)?3:4
  if(!Number.isFinite(value)||(f.key==='wait'?value<0:value<=0)||(f.key==='cycles'&&!Number.isInteger(value)))add(f.key,page,'请填写有效数值'+(f.key==='wait'?'（允许 0）':''))
  else if(['productTime','cleanTime'].includes(f.key)&&(value<0.1||value>9999))add(f.key,page,'排液时间须为 0.1–9999 秒')
 }
 if(through>=4&&(!Number.isFinite(turntableDripSeconds.value)||numeric(turntableDripSeconds.value)<0||numeric(turntableDripSeconds.value)>3600))add('turntableDripSeconds',4,'请填写现场标定的滴液等待时间：0–3600 秒（可明确填写 0）')
 if(through>=5){
  try{microwaveHoldSeconds(numeric(primeHeatMinutes.value))}catch{add('primeHeatMinutes',5,'到温后等待时间：请填写 0–1440 分钟，可换算为整秒')}
  for(const f of priming.value.slice(0,through===6?undefined:5)){
   const value=numeric(f.value)
   if(!Number.isFinite(value)||value<=0)add(f.key,5,'请填写有效的'+f.label)
   else if(f.key==='prime_cycles'&&(!Number.isInteger(value)||value>10))add(f.key,5,'次数须为 1–10 的整数')
   else if(f.key==='prime_drain_seconds'&&(value<0.1||value>9999))add(f.key,5,'排液时间须为 0.1–9999 秒')
  }
 }
 if(through>=6&&(!Number.isInteger(repeats.value)||numeric(repeats.value)<1))add('repeats',6,'重复次数须为正整数')
 return issues
}
function focusIssues(through:number){
 const issues=fieldIssues(through)
 fieldErrors.value=Object.fromEntries(issues.map(i=>[i.key,i.message]))
 const first=issues[0]
 if(!first)return
 stage.value=first.stage;showProgress.value=false
 if(priming.value.slice(5).some(p=>p.key===first.key))advancedOpen.value=true
 void nextTick(()=>{const container=document.querySelector(`[data-field="${first.key}"]`);const input=container?.matches('input')?container:container?.querySelector('input')||container?.querySelector('select');(input as HTMLElement|null)?.focus();container?.scrollIntoView({block:'center'})})
}
function stepError(step:number):string {
 const first=fieldIssues(step)[0];if(first)return first.message
 if(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(experimentName.value)||Array.from(experimentName.value.trim()).length<1||Array.from(experimentName.value.trim()).length>80)return '请填写实验名称：1–80 个字符，不能包含换行或控制字符'
 if(roles.some(r=>!chosen[r.key]||!registry.value[r.group]?.[chosen[r.key]!]))return '固定装置配置缺失，请检查设备配置后再继续'
 if(turntableConfigError.value)return turntableConfigError.value
 if(chosen.heaterA===chosen.heaterB||chosen.pumpA===chosen.pumpB)return '两路须选择不同的加热器和注射泵'
 try{
  for(const [i,a] of axes.value.slice(0,Math.min(step+1,3)*2).entries()){
   const values=valuesFor(a)
   if(values.some(v=>i===2||i===3?v<=0:v<0))return `${a.label}：请填写有效数值`
   if(i===5)values.forEach(microwaveHoldSeconds)
  }
 }catch(e){return (e as Error).message}
 if(step>=1&&!([speedA.value,speedB.value].every(v=>Number.isInteger(v)&&numeric(v)>=5&&numeric(v)<=5000)))return '请填写进料速度：5–5000 的整数步频'
 if(step>=3){
  if(!valveConfigured.value)return '当前配置缺少三通阀 valve1'
  if(cleanChannel.value===drainChannel.value)return '进液与排液通道不能相同'
  for(const item of fixed.value.filter(s=>step>=4||['drainFlow','productTime'].includes(s.key)))if(!Number.isFinite(item.value)||(item.key==='wait'?numeric(item.value)<0:numeric(item.value)<=0)||(item.key==='cycles'&&!Number.isInteger(item.value)))return '请填写有效的收集与清洗参数'
  for(const key of step>=4?['productTime','cleanTime']:['productTime'])if(!Number.isFinite(setting(key))||setting(key)<0.1||setting(key)>9999)return '产物及清洗排液时间须为 0.1–9999 秒，请按现场标定填写'
  if(step>=4){try{const seconds=estimateDrainSeconds(setting('volume'),setting('flow'));if(seconds<0.1||seconds>9999)throw new Error()}catch{return '清洗进液时间超出有效范围，请检查体积和流量'}}
 }
 if(step>=5){
  if(!Number.isFinite(primeHeatMinutes.value))return '请填写到温后等待时间'
  try{microwaveHoldSeconds(numeric(primeHeatMinutes.value))}catch{return '到温后等待时间须为 0–1440 分钟，且能换算为整秒'}
  for(const p of priming.value.slice(0,5))if(!Number.isFinite(p.value)||numeric(p.value)<=0)return `请填写有效的${p.label}`
  if(!Number.isInteger(primeValue('prime_cycles'))||primeValue('prime_cycles')>10)return '预充循环次数须为 1–10 的整数'
  if(primeValue('prime_drain_seconds')<0.1||primeValue('prime_drain_seconds')>9999)return '预充排液时间须为 0.1–9999 秒'
 }
 if(step>=6&&plan.value.error)return plan.value.error
 return ''
}
function nextStage(){error.value=stepError(stage.value);if(error.value)focusIssues(stage.value);else if(stage.value<6)stage.value++}
const total=(i:number)=>Number(plan.value.rows.reduce((s,r)=>s+r[i]!,0).toPrecision(10))
const plumbingConfirmed=ref(false),drainDirection=ref('CW'),cleanDirection=ref('CW')
const previewPrime=ref(''),previewYaml=ref<string[]>([]),validatedKey=ref(''),controlling=ref(false),batch=ref<any>({state:'idle'})
const activeRun=computed(()=>['running','paused'].includes(batch.value.state)&&batch.value.phase!=='ready')
const terminalRun=computed(()=>['completed','failed','stopped','interrupted'].includes(batch.value.state))
const batchCompleted=computed(()=>batchCompletionConfirmed(batch.value))
const finalizationFailed=computed(()=>batch.value.finalization?.status==='failed'&&batch.value.total_groups>0&&completedGroups.value===batch.value.total_groups)
const turntableOperationLabel=computed(()=>({pending:'等待准备',homing:'机械回零中',settling:'等待残余滴液',indexing:'切换下一瓶',ready:'瓶位已确认',stopped:'已停止',failed:'动作失败'} as Record<string,string>)[batch.value.turntable?.operation]||'未记录')
const finalizationLabel=computed(()=>({pending:'待收尾',running:'停机与回零中',completed:'已完成停机与回零',failed:'收尾失败'} as Record<string,string>)[batch.value.finalization?.status]||'未记录')
const showProgress=ref(false),lastRefresh=ref(0),refreshError=ref('')
const executionStages=stageNames
const executionStage=computed(()=>activeStage(batch.value))
const activity=computed(()=>batch.value.progress?.activity)
const statusNow=ref(Date.now())
const stale=computed(()=>staleStatus(lastRefresh.value,statusNow.value,refreshError.value))
const stageLabels:Record<string,string>={pending:'未开始',running:'进行中',completed:'已完成',paused:'已暂停',failed:'失败',stopped:'已结束',stopping:'正在停止',cleanup:'正在清理'}
const operationTitle=computed(()=>finalizationFailed.value?'实验组已完成，收尾回零失败':batch.value.cleanup_in_progress?'正在清理设备':terminalRun.value?'已结束 · '+(activity.value?.title||batch.value.progress?.step_label||'本批实验'):batch.value.stop_requested?'正在停止本批次':activity.value?.title||currentStepLabel.value)
const operationDescription=computed(()=>batch.value.cleanup_in_progress?'等待设备停止和资源释放确认。':terminalRun.value?(batch.value.cleanup_pending?'清理未确认，请检查恢复事项。':'最后一次动作与读数保留如下。'):batch.value.stop_requested?'停止请求已发出，等待设备与记录处理完成。':activity.value?.description||'以下显示已确认的步骤信息。')
const deviceLabel=(id:string)=>({heater1:'前驱体 A 加热器',heater2:'前驱体 B 加热器',syringe_pump1:'注射泵 A',syringe_pump2:'注射泵 B',microwave1:'微波反应仪',pump1:'蠕动泵',valve1:'三通阀',turntable1:'产物收集转盘'} as Record<string,string>)[id]||id
const seconds=(value:any)=>typeof value==='number'&&Number.isFinite(value)?Math.floor(value)+' 秒':'未知'
const pendingControl=ref(''),controlFeedback=ref(''),controlUncertain=ref(false)
let controlSequence=0,controlBatchId=''
const stageBatch=computed(()=>pendingControl.value==='stop'?{...batch.value,stop_requested:true}:batch.value)
const controlsBusy=computed(()=>!!pendingControl.value||controlling.value)
const turntablePausePending=(data:any)=>data.pause_pending&&['preparing','indexing','finishing'].includes(data.phase)
function reconcileControl(data:any){
 if(data.batch_id!==controlBatchId)return
 if(!pendingControl.value){if(data.state==='paused'&&controlFeedback.value.startsWith('已请求暂停'))controlFeedback.value='已暂停';return}
 if(['stopped','failed','completed','interrupted'].includes(data.state)&&!data.cleanup_in_progress){++controlSequence;pendingControl.value='';controlUncertain.value=false;controlFeedback.value=data.cleanup_pending?'本批已结束，清理未确认':'本批实验已结束';return}
 const action=pendingControl.value
 const confirmed=action==='pause'?(data.pause_pending||data.state==='paused'):action==='resume'?(data.state==='running'&&!data.pause_pending):(['stopped','failed','completed'].includes(data.state)&&!data.cleanup_in_progress)
 if(confirmed){++controlSequence;controlFeedback.value=action==='pause'?(data.pause_pending?(turntablePausePending(data)?'已请求暂停，等待当前转盘动作完成':'已请求暂停，等待当前反应结束'):'已暂停'):action==='resume'?'已继续运行':data.cleanup_pending?'已停止，清理未确认':'本批次已停止';pendingControl.value='';controlUncertain.value=false}
}
const showCompleted=ref(false)
const visibleGroups=computed(()=>progressGroups.value.filter(g=>showCompleted.value||g.state!=='completed'||g.index===batch.value.current_group))
async function locateCurrent(){await nextTick();document.querySelector('.run-table tr.selected')?.scrollIntoView({block:'nearest'})}
const resultCounts=computed(()=>({completed:completedGroups.value,failed:(batch.value.groups||[]).filter((g:any)=>g.state==='failed').length,unexecuted:Math.max(0,(batch.value.total_groups||0)-(batch.value.groups||[]).filter((g:any)=>g.state!=='pending').length)}))
const exportingBatch=ref(false)
function openBatchHistory(){router.push({path:'/experiment/batch',query:{view:'history',batch_id:batch.value.batch_id}})}
async function exportBatch(){
 if(exportingBatch.value)return
 exportingBatch.value=true
 try{
  const content=await batchExport(batch.value,url=>axios.get(url))
  const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:'application/json;charset=utf-8'}))
  const link=document.createElement('a');link.href=url;link.download=`experiment_${batch.value.batch_id}.json`;link.click();URL.revokeObjectURL(url)
 }catch(e){showError(e)}finally{exportingBatch.value=false}
}
const phaseLabel=computed(()=>({preparing:'启动准备与机械回零',priming:'初始化、加热与预充',ready:'预充完成，待正式启动',experiments:'正式实验',indexing:'清洗后换瓶',finishing:'批次收尾与机械回零'} as Record<string,string>)[batch.value.phase]||'正式实验')
const completedGroups=computed(()=>(batch.value.groups||[]).filter((g:any)=>g.state==='completed').length)
const elapsedLabel=computed(()=>batchElapsedLabel(batch.value))
const currentStepLabel=computed(()=>batch.value.state==='completed'?'全部实验组已完成':batch.value.phase==='ready'?'预充已完成，等待正式启动':batch.value.progress?.step_label||(batch.value.state==='running'?'正在准备执行':'暂无步骤信息'))
const currentDevice=computed(()=>{
 if(batch.value.progress?.device_id)return batch.value.progress.device_id
 const id=batch.value.progress?.step_id||''
 if(id.startsWith('turntable_'))return '产物收集转盘'
 if(['heat_both_stable','prime_heat_both_stable','prime_heat_both_reached','prime_heat_duration'].includes(id))return '加热器 A / B'
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
  return {index:i+1,parameters:recorded?.parameters||rows[i]||[],sample_id:recorded?.sample_id,bottle_number:recorded?.bottle_number,collection_status:recorded?.collection_status,collection_error:recorded?.collection_error,
   state:recorded?.state==='running'&&i+1===batch.value.current_group?batch.value.state:recorded?.state||'pending'}
 })
})
const primeFields:NumberField[]=[
 {key:'prime_volume_a',label:'A 每次预充量',unit:'mL',value:null},
 {key:'prime_volume_b',label:'B 每次预充量',unit:'mL',value:null},
 {key:'prime_cycles',label:'每台泵循环次数',unit:'次',value:null},
 {key:'prime_drain_flow',label:'预充排液流量',unit:'mL/min',value:null},
 {key:'prime_drain_seconds',label:'预充排液时间',unit:'秒',value:null},
 {key:'reactor_available_ml',label:'反应仪可用容积',unit:'mL',value:null},
 {key:'source_available_a_ml',label:'A 可用前驱体量',unit:'mL',value:null},
 {key:'source_available_b_ml',label:'B 可用前驱体量',unit:'mL',value:null},
 {key:'waste_available_ml',label:'废液瓶剩余容量',unit:'mL',value:null}
]
const primeHeatMinutes=ref<InputNumber>(null)
const priming=ref(primeFields),primingConfirmed=ref(false),initializationConfirmed=ref(false)
const initialization=ref([{direction:'Z',initialization_code:0},{direction:'Z',initialization_code:0}])
const initializationCodes=[0,1,2,...Array.from({length:31},(_,i)=>i+10)]
const primeValue=(key:string)=>numeric(priming.value.find(p=>p.key===key)!.value)
const primeTotal=computed(()=>(primeValue('prime_volume_a')+primeValue('prime_volume_b'))*primeValue('prime_cycles'))
const advancedOpen=ref(false)
const advancedMissing=computed(()=>priming.value.slice(5).some(p=>!Number.isFinite(p.value)||numeric(p.value)<=0))
const primeReady=computed(()=>!newDraft.value&&batch.value.request?.experiment_name!=null&&batch.value.request?.prime_heat_minutes!=null&&batch.value.request?.initialization_a!=null&&batch.value.request?.initialization_b!=null&&batch.value.request?.product_port==='NO'&&batch.value.request?.product_drain_seconds!=null&&batch.value.request?.clean_drain_seconds!=null&&batch.value.request?.prime_drain_seconds!=null&&batch.value.request?.prime_drain_flow!=null&&batch.value.request?.turntable_drip_seconds!=null&&batch.value.phase==='ready'&&batch.value.state==='paused'&&!batch.value.recovery_required&&batch.value.priming?.status==='completed'&&JSON.stringify(batch.value.request&&requestWithoutFlags(batch.value.request))===JSON.stringify(requestWithoutFlags(requestBody.value)))
function requestWithoutFlags(r:any){const keys=Object.keys(requestBody.value).filter(k=>!['plumbing_confirmed','priming_confirmed','initialization_confirmed','bottles_confirmed','priming_batch_id'].includes(k));return Object.fromEntries(keys.map(k=>[k,r[k]]))}
const labels:Record<string,string>={idle:'未运行',pending:'待执行',running:'执行中',paused:'已暂停',completed:'已完成',failed:'失败',stopped:'已停止',interrupted:'服务中断'}
const stateLabel=computed(()=>labels[batch.value.state]||batch.value.state)
const requestBody=computed(()=>({experiment_name:experimentName.value.trim(),prime_heat_minutes:primeHeatMinutes.value,turntable_drip_seconds:turntableDripSeconds.value,bottles_confirmed:false,axes:axes.value.map(a=>valuesFor(a)),repeats:repeats.value,initialization_a:initialization.value[0],initialization_b:initialization.value[1],speed_a:speedA.value,speed_b:speedB.value,product_port:productPort,drain_flow:setting('drainFlow'),product_drain_seconds:setting('productTime'),clean_drain_seconds:setting('cleanTime'),clean_volume:setting('volume'),clean_flow:setting('flow'),clean_dwell:setting('wait'),clean_cycles:setting('cycles'),drain_direction:drainDirection.value,clean_direction:cleanDirection.value,...Object.fromEntries(priming.value.map(p=>[p.key,p.value]))}))
const requestKey=computed(()=>{try{return JSON.stringify(requestBody.value)}catch{return ''}})
const startBlockReason=computed(()=>{
 if(stage.value!==6)return '请前往批次确认页'
 if(activeRun.value)return '已有批次运行中，请先停止或查看实验进度'
 if(batch.value.recovery_required)return '请在实验进度页完成现场检查并解除恢复锁定'
 if(batch.value.persistence_status==='error')return '记录保存未确认，请查看实验进度'
 if(batch.value.cleanup_pending||batch.value.cleanup_required)return '设备清理尚未完成，请查看实验进度'
 if(batch.value.phase==='ready'&&!primeReady.value)return '当前参数与已有预充结果不匹配，请先停止旧批次'
 const issue=stepError(6)
 if(issue)return issue
 if(advancedMissing.value)return '请返回预充页填写可用容量'
 if(validating.value)return '正在校验完整批次…'
 if(!requestKey.value||validatedKey.value!==requestKey.value)return '请先生成并校验完整批次'
 const missing=[]
 if(!plumbingConfirmed.value)missing.push('接管、泵向及微波负载')
 if(!primingConfirmed.value)missing.push('设备、容量及相容性')
 if(!initializationConfirmed.value)missing.push('初始化与预充耗液')
 if(!bottlesConfirmed.value)missing.push('本批产物瓶已清空并就位')
 return missing.length?'待确认：'+missing.join('；'):''
})
const fragment=computed(()=>previewYaml.value[selected.value]||'请先生成并校验完整批次。')
watch([experimentName,axes,chosen,repeats,speedA,speedB,fixed,drainDirection,cleanDirection,priming,primeHeatMinutes,initialization,turntableDripSeconds],()=>{fieldErrors.value={};report.value='';selected.value=0;validatedKey.value='';previewYaml.value=[];previewPrime.value='';plumbingConfirmed.value=false;primingConfirmed.value=false;initializationConfirmed.value=false;bottlesConfirmed.value=false},{deep:true})
function showError(e:any){
 const detail=e.response?.data?.detail
 error.value=Array.isArray(detail)?detail.map(d=>`${d.loc?.slice(1).join('.') || '参数'}：${d.msg}`).join('；'):String(detail||e.message||e)
 if(!Array.isArray(detail))return
 const mapping:Record<string,[string,number]>={experiment_name:['experimentName',0],speed_a:['speedA',1],speed_b:['speedB',1],drain_flow:['drainFlow',3],product_drain_seconds:['productTime',3],clean_flow:['flow',4],clean_volume:['volume',4],clean_dwell:['wait',4],clean_cycles:['cycles',4],clean_drain_seconds:['cleanTime',4],prime_heat_minutes:['primeHeatMinutes',5],repeats:['repeats',6]}
 priming.value.forEach(p=>{mapping[p.key]=[p.key,5]})
 mapping.turntable_drip_seconds=['turntableDripSeconds',4]
 mapping.bottles_confirmed=['bottlesConfirmed',6]
 const issues:FieldIssue[]=detail.flatMap(d=>{const loc=d.loc?.slice(1)||[];const field=loc[0]==='axes'&&axes.value[loc[1]]?[axes.value[loc[1]]!.key,Math.floor(loc[1]/2)]:mapping[loc[0]];return field?[{key:field[0] as string,stage:field[1] as number,message:d.msg}]:[]})
 if(!issues.length)return
 fieldErrors.value=Object.fromEntries(issues.map(i=>[i.key,i.message]))
 const first=issues[0]!;stage.value=first.stage
 if(priming.value.slice(5).some(p=>p.key===first.key))advancedOpen.value=true
 void nextTick(()=>{const container=document.querySelector(`[data-field="${first.key}"]`);const input=container?.matches('input')?container:container?.querySelector('input');(input as HTMLElement|null)?.focus();container?.scrollIntoView({block:'center'})})
}
async function validate(){validating.value=true;report.value='';try{const issue=stepError(6);if(issue){focusIssues(6);throw new Error(issue);}if(advancedMissing.value)throw new Error('请在可用容量中填写有效的容积和储液量');const key=requestKey.value;const {data}=await axios.post('/api/guided/preview',requestBody.value);if(key!==requestKey.value)return;previewYaml.value=data.yaml;previewPrime.value=JSON.stringify(data.priming,null,2);validatedKey.value=key;report.value=`后端已生成并校验 ${data.total_groups} 组完整流程，尚未启动设备。`}catch(e){advancedOpen.value=advancedMissing.value;showError(e)}finally{validating.value=false}}
let restoredBatchId:string|null=null, refreshSequence=0
function restoreParameters(r:any){
 experimentName.value=r.experiment_name??''
 turntableDripSeconds.value=r.turntable_drip_seconds??null
 primeHeatMinutes.value=r.prime_heat_minutes??null;axes.value.forEach((a,i)=>{const values=r.axes[i];a.mode=values.length===1?'fixed':'list';a.start=values[0];a.end=a.interval=null;a.list=values.join(',')});repeats.value=r.repeats;speedA.value=r.speed_a;speedB.value=r.speed_b;drainDirection.value=r.drain_direction;cleanDirection.value=r.clean_direction;const mapping:Record<string,string>={drainFlow:'drain_flow',productTime:'product_drain_seconds',cleanTime:'clean_drain_seconds',volume:'clean_volume',flow:'clean_flow',wait:'clean_dwell',cycles:'clean_cycles'};fixed.value.forEach(s=>s.value=r[mapping[s.key]!]??null);const displayDrain=primingDrainForDisplay(r);priming.value.forEach(p=>p.value=displayDrain[p.key as keyof typeof displayDrain]??r[p.key]??null);if(r.initialization_a&&r.initialization_b)initialization.value=[{...r.initialization_a},{...r.initialization_b}]
}
function requiresAttention(value:any){return ['running','paused'].includes(value.state)||value.recovery_required||value.cleanup_pending||value.cleanup_required||value.persistence_status==='error'}
async function refreshBatch(force=false){
 if(controlling.value&&!force)return
 const sequence=++refreshSequence
 try{
  const {data}=await axios.get('/api/guided/current')
  if(sequence!==refreshSequence)return
  batch.value=data;lastRefresh.value=Date.now();statusNow.value=Date.now();refreshError.value='';reconcileControl(data)
  if(newDraft.value&&!requiresAttention(data))return
  const interruptedDraft=newDraft.value
  if(requiresAttention(data)){saveDraft();draftEnabled=false}
  if(interruptedDraft){newDraft.value=false;void router.replace({query:{...route.query,new:undefined,resume:'1'}})}
  if(data.request&&(interruptedDraft||restoredBatchId!==data.batch_id)){
   restoreParameters(data.request)
   stage.value=data.phase==='ready'?6:5;showProgress.value=true;restoredBatchId=data.batch_id
  }else if(interruptedDraft){showProgress.value=true}
 }catch{if(sequence===refreshSequence)refreshError.value='进度读取失败，当前显示为上次收到的状态。请检查后端连接。'}
}
async function startBatch(){
 if(controlling.value)return
 controlling.value=true
 try{
  const key=requestKey.value
  if(startBlockReason.value)throw new Error(startBlockReason.value)
  if(!await confirmations.confirm('start',()=>ElMessageBox.confirm('将先确认泵停止、阀在 NC 并将转盘机械回零至 1 号瓶，再自动初始化 A/B（移动活塞并切阀），按第一组目标加热，两路均达到或超过各自目标后立即计时保温脱气，再按设定参数预充并排废液，消耗前驱体；前驱体持续保温，预充液须降至45℃后排出。成功后重新确认稳定到温，再进料和微波反应。已有匹配的本批次预充结果时直接开始正式实验。本批所需产物瓶须已清空并就位；清洗后自动换瓶，整批正常结束后停机回零，停止或故障时原位停机、不回零。请确认初始化方向与代码、设备安装、液路、容量、废液及微波负载条件，运行期间有人看护。','开始真实实验',{confirmButtonText:'确认启动',cancelButtonText:'取消',type:'warning'})))return
  if(key!==requestKey.value||startBlockReason.value)throw new Error('参数、确认或批次状态已变化，请重新校验并确认')
  ++refreshSequence
  batch.value=(await axios.post('/api/guided/start',{...requestBody.value,plumbing_confirmed:plumbingConfirmed.value,priming_confirmed:primingConfirmed.value,initialization_confirmed:initializationConfirmed.value,bottles_confirmed:bottlesConfirmed.value,priming_batch_id:primeReady.value?batch.value.batch_id:undefined})).data
  removeDraft();draftEnabled=false
  newDraft.value=false;restoredBatchId=batch.value.batch_id
  void router.replace({query:{...route.query,new:undefined,resume:'1'}})
  showProgress.value=true
  lastRefresh.value=Date.now()
  refreshError.value=''
  error.value=''
 }catch(e){if(e!=='cancel'&&e!=='close')showError(e)}finally{controlling.value=false}
}
async function controlBatch(action:string){
 if(action==='stop')confirmations.cancel()
 if(controlling.value||pendingControl.value==='stop'||(pendingControl.value&&action!=='stop'))return
 const sequence=++controlSequence
 ++refreshSequence
 controlBatchId=batch.value.batch_id;pendingControl.value=action;controlUncertain.value=false
 controlFeedback.value=({pause:'正在请求暂停…',resume:'正在请求继续…',stop:'正在请求停止…'} as Record<string,string>)[action]||''
 try{
  const {data}=await axios.post(`/api/guided/${controlBatchId}/${action}`,{})
  if(sequence!==controlSequence)return
  controlUncertain.value=data.success===false
  controlFeedback.value=data.success===false?'设备处理未确认，请查看状态与恢复事项。':'请求已接收，等待状态确认…'
  await refreshBatch(true)
 }catch(e:any){
  if(sequence!==controlSequence)return
  if([400,409,422].includes(e.response?.status)){pendingControl.value='';controlUncertain.value=false;controlFeedback.value='请求未接受：'+String(e.response.data?.detail||e.message)}
  else {controlUncertain.value=true;controlFeedback.value='结果未确认：连接或服务异常，请刷新状态核对；不会自动重发指令。'}
  await refreshBatch(true)
 }
}
function defaultInitializationCode(i:number){const capacity=registry.value.syringe_pumps?.[`syringe_pump${i+1}`]?.capacity_ml;return capacity==null||capacity>=2.5?0:capacity>=0.5?1:2}
function returnToSetup(reuse=false){
 if(controlsBusy.value||!terminalRun.value||batch.value.recovery_required||batch.value.cleanup_pending||batch.value.cleanup_required||batch.value.persistence_status==='error')return
 ++refreshSequence
 if(reuse&&batch.value.request)restoreParameters(batch.value.request)
 else{
  axes.value.forEach(a=>{a.mode='fixed';a.start=a.end=a.interval=null;a.list=''})
  fixed.value.forEach(f=>{f.value=null});priming.value.forEach(p=>{p.value=null})
  repeats.value=speedA.value=speedB.value=primeHeatMinutes.value=turntableDripSeconds.value=null
  initialization.value=[0,1].map(i=>({direction:'Z',initialization_code:defaultInitializationCode(i)}))
  drainDirection.value=cleanDirection.value='CW';cleanChannel.value=3;drainChannel.value=4
  Object.assign(chosen,{heaterA:'heater1',heaterB:'heater2',pumpA:'syringe_pump1',pumpB:'syringe_pump2',reaction:'microwave1',liquid:'pump1',turntable:'turntable1'})
 }
 experimentName.value=''
 plumbingConfirmed.value=primingConfirmed.value=initializationConfirmed.value=bottlesConfirmed.value=false
 validatedKey.value='';report.value='';previewYaml.value=[];previewPrime.value='';selected.value=0
 fieldErrors.value={};controlFeedback.value='';showCompleted.value=false
 error.value='';advancedOpen.value=false;stage.value=0;showProgress.value=false;newDraft.value=true;draftEnabled=true
 void router.replace({query:{...route.query,new:'1'}})
}
async function acknowledgeInterrupted(){if(controlling.value)return;const id=batch.value.batch_id;controlling.value=true;try{if(!await confirmations.confirm('recover',()=>ElMessageBox.confirm('请在现场确认所有设备已停止，并检查预充残留、气泡和液路。解除锁定后可新建实验，原记录保留，不恢复原批次。','确认失败或中断后的设备状态',{type:'warning'}),()=>batch.value.batch_id===id))return;++refreshSequence;batch.value=(await axios.post(`/api/guided/${id}/acknowledge-interrupted`,{devices_stopped_confirmed:true})).data}catch(e){if(e!=='cancel'&&e!=='close')showError(e)}finally{controlling.value=false}}

const draftKey='heat.guided-draft.v1'
const draftNotice=ref('')
let draftEnabled=newDraft.value, draftRestored=false
function removeDraft(){try{if(typeof window!=='undefined')window.localStorage.removeItem(draftKey)}catch{draftNotice.value='无法清除本机草稿，请检查浏览器存储。'}}
function saveDraft(){
 if(!draftEnabled||showProgress.value)return
 try{if(typeof window!=='undefined')window.localStorage.setItem(draftKey,JSON.stringify({version:1,experimentName:experimentName.value,stage:stage.value,axes:axes.value,fixed:fixed.value,priming:priming.value,repeats:repeats.value,speedA:speedA.value,speedB:speedB.value,primeHeatMinutes:primeHeatMinutes.value,turntableDripSeconds:turntableDripSeconds.value,initialization:initialization.value,drainDirection:drainDirection.value,cleanDirection:cleanDirection.value,cleanChannel:cleanChannel.value,drainChannel:drainChannel.value,chosen:{...chosen},advancedOpen:advancedOpen.value}))}
 catch{draftNotice.value='草稿保存失败，离开页面前请保留已填参数。'}
}
function restoreDraft(){
 if(!newDraft.value)return
 try{
  const raw=typeof window!=='undefined'?window.localStorage.getItem(draftKey):null
  if(!raw)return
  const d=JSON.parse(raw)
  const number=(v:unknown)=>v===null||v===''||(typeof v==='number'&&Number.isFinite(v))
  if(d.version!==1||typeof d.experimentName!=='string'||!Number.isInteger(d.stage)||d.stage<0||d.stage>6||!Array.isArray(d.axes)||d.axes.length!==6)throw new Error('invalid')
  for(const [key,fields] of [['axes',axes.value],['fixed',fixed.value],['priming',priming.value]] as const){
   if(!Array.isArray(d[key])||d[key].length!==fields.length)throw new Error('invalid')
   fields.forEach((f,i)=>{const item=d[key][i];if(!item||item.key!==f.key)throw new Error('invalid')})
  }
  if(![d.repeats,d.speedA,d.speedB,d.primeHeatMinutes].every(number)||!Array.isArray(d.initialization)||d.initialization.length!==2||d.initialization.some((x:any)=>!['Z','Y'].includes(x.direction)||![0,1,2].includes(x.initialization_code)))throw new Error('invalid')
  if(d.turntableDripSeconds!==undefined&&!number(d.turntableDripSeconds))throw new Error('invalid')
   if(d.axes.some((a:any)=>!['fixed','range','list'].includes(a.mode)||![a.start,a.end,a.interval].every(number)||typeof a.list!=='string')||[...d.fixed,...d.priming].some((f:any)=>!number(f.value)))throw new Error('invalid')
  experimentName.value=d.experimentName;stage.value=d.stage
  axes.value.forEach((a,i)=>{const v=d.axes[i];Object.assign(a,{mode:v.mode,start:v.start,end:v.end,interval:v.interval,list:v.list})})
  fixed.value.forEach((f,i)=>f.value=d.fixed[i].value);priming.value.forEach((f,i)=>f.value=d.priming[i].value)
  repeats.value=d.repeats;speedA.value=d.speedA;speedB.value=d.speedB;primeHeatMinutes.value=d.primeHeatMinutes;turntableDripSeconds.value=d.turntableDripSeconds??null
  initialization.value=d.initialization.map((v:any)=>({direction:v.direction,initialization_code:v.initialization_code}))
  if(['CW','CCW'].includes(d.drainDirection))drainDirection.value=d.drainDirection
  if(['CW','CCW'].includes(d.cleanDirection))cleanDirection.value=d.cleanDirection
  if(Number.isInteger(d.cleanChannel))cleanChannel.value=d.cleanChannel
  if(Number.isInteger(d.drainChannel))drainChannel.value=d.drainChannel
  for(const key of Object.keys(chosen))if(typeof d.chosen?.[key]==='string')chosen[key]=d.chosen[key]
  advancedOpen.value=d.advancedOpen===true;draftRestored=true
  draftNotice.value='已恢复本机草稿；参数须重新校验，现场确认与预充资格不随草稿恢复。'
 }catch{draftNotice.value='本机草稿无法恢复，请重新填写；原草稿未删除。'}
}
watch([experimentName,stage,axes,fixed,priming,repeats,speedA,speedB,primeHeatMinutes,turntableDripSeconds,initialization,drainDirection,cleanDirection,cleanChannel,drainChannel,chosen,advancedOpen],saveDraft,{deep:true})
onUnmounted(saveDraft)

let statusTimer:ReturnType<typeof setInterval>|undefined
onMounted(()=>{restoreDraft();void refreshBatch();statusTimer=setInterval(()=>{statusNow.value=Date.now();void refreshBatch()},2000)})
onUnmounted(()=>{++refreshSequence;++controlSequence;if(statusTimer)clearInterval(statusTimer)})
onMounted(async()=>{try{registry.value=(await axios.get('/api/devices')).data;if(!draftRestored&&(newDraft.value||!batch.value.request)){initialization.value.forEach((item,i)=>{item.initialization_code=defaultInitializationCode(i)})}const missing=roles.filter(r=>!registry.value[r.group]?.[chosen[r.key]!]);if(missing.length)error.value='配置缺少固定装置：'+missing.map(r=>r.label).join('、')}catch{error.value='读取装置失败，请检查后端服务。'}})
</script>
<style scoped>
.turntable-progress{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:20px 0;padding:18px;background:#f5f8fc;border:1px solid #dce7f1;border-radius:10px}.turntable-progress>div{display:flex;flex-direction:column;gap:8px;min-width:0}.turntable-progress strong{font-size:18px}.turntable-progress p{grid-column:1/-1;font-size:12px;margin:0}.collection-error{display:block;max-width:220px;color:#b34d42}.run-table td{vertical-align:top}@media(max-width:760px){.turntable-progress{grid-template-columns:repeat(2,minmax(0,1fr))}}
.experiment-name{display:flex;flex-direction:column;gap:8px;max-width:420px;margin-bottom:24px}

.estimate strong{display:block;margin:16px 0 12px}.estimate .el-button{margin-bottom:12px}
.guided{max-width:1400px;margin:auto;padding:12px 12px 104px;color:#243e58}header{display:flex;justify-content:space-between;align-items:center;gap:20px}h2{font-size:28px;margin:0}p{color:#667e94;line-height:1.7}nav{display:flex;gap:8px;margin:24px 0;flex-wrap:wrap}nav button{flex:1;min-width:115px;padding:14px 8px;border:1px solid #ccddeb;border-radius:10px;background:white;color:#526b83;cursor:pointer}nav b{flex-shrink:0;display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#e8f2fc;margin-right:10px}nav button:disabled{opacity:.45;cursor:not-allowed}nav .active{background:#edf7ff;border-color:#409eff;color:#1680d6}.layout{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:20px}section,aside{padding:24px;border:1px solid #dce7f1;border-radius:14px;background:#ffffffef}aside{align-self:start;position:sticky;top:90px}aside h3{margin:0 0 8px}aside p{font-size:13px;margin:12px 0}aside .el-button{width:100%}section h3{margin:0 0 10px}section>p{margin:8px 0 16px}header .el-button{flex-shrink:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}label{display:flex;flex-direction:column;gap:8px;font-size:13px}small{color:#6d8499}input,select{min-width:0;max-width:100%;padding:10px;border:1px solid #c3d6e7;border-radius:7px;background:white;color:#243e58}.notice{margin-top:18px;padding:18px;background:#eef5fb;border-radius:10px;line-height:1.8}.axis{margin-top:18px;padding:20px;border:1px solid #dce7f1;border-radius:12px;background:#fbfdff}.axis-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.axis-heading strong{font-size:15px}.axis-heading span{font-size:12px;color:#73899d}.axis-controls{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:end}.axis-controls input,.axis-controls select{width:100%;box-sizing:border-box;height:42px}.axis-controls label{min-width:0}.axis-controls label:last-child:first-child{grid-column:span 2}.settings{margin-top:24px}.device-summary{margin-bottom:24px;font-size:13px}.estimate{margin-top:20px;padding:18px;background:#eaf5ff;border:1px solid #cbe4fa;border-radius:10px}.estimate p{margin:8px 0}.estimate small{line-height:1.7;display:block}.confirm-check{flex-direction:row;align-items:flex-start;line-height:1.6;margin:12px 0}.confirm-check input{flex-shrink:0;width:16px;height:16px;margin:3px 0 0;padding:0}.count{font-size:62px;color:#1688e8;font-weight:700}.count small{font-size:20px}.table{overflow:auto;max-height:450px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:12px;text-align:left;border-bottom:1px solid #dce7f1}th{background:#eff6fc}.selected{background:#e7f4ff}li{line-height:1.9;font-size:14px}pre{background:#172c40;color:#e0edf8;padding:16px;overflow:auto;max-height:350px}details{margin-top:20px}footer{position:fixed;z-index:20;left:50%;bottom:16px;transform:translateX(-50%);width:min(calc(100% - 32px),1400px);box-sizing:border-box;display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:0;padding:12px 16px;border:1px solid #dce7f1;border-radius:14px;background:#fff;box-shadow:0 8px 28px rgba(41,83,121,.16)}footer .el-button{margin:0}@media(max-width:1000px){.layout{grid-template-columns:1fr}aside{position:static}}@media(max-width:760px){.axis-controls{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.grid{grid-template-columns:1fr}nav,header{flex-wrap:wrap}nav button{min-width:130px}footer{bottom:8px;width:calc(100% - 16px);padding:8px;gap:8px}footer .el-button{flex:1;min-width:0;padding-left:8px;padding-right:8px}}

.header-actions,.run-heading,.run-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.run-panel{margin-top:24px}.run-heading{justify-content:space-between;margin-bottom:20px}.run-heading h3{font-size:26px;margin:0}.batch-id{margin:8px 0 0;font-size:12px;overflow-wrap:anywhere}.run-panel>.el-alert{margin:12px 0}.run-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:24px 0}.run-summary>div{padding:20px;background:#eef5fb;border-radius:12px;display:flex;flex-direction:column;gap:10px}.run-summary strong{font-size:26px}.run-summary span{font-size:12px;color:#667e94}.run-summary progress{width:100%;height:10px;accent-color:#1688e8}.current-operation{padding:24px;background:#eaf5ff;border-left:4px solid #1688e8;border-radius:10px}.current-operation h3{margin:10px 0}.current-operation p{margin:0}.run-stages{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px;list-style:none;padding:0;margin:24px 0}.run-stages li{display:flex;flex-direction:column;gap:8px;padding:16px 12px;background:#f5f8fc;border:1px solid #dce7f1;border-radius:10px;font-size:13px}.run-stages b{font-size:18px}.run-stages .current{background:#eaf5ff;border-color:#1688e8;color:#1680d6}.run-table{max-height:500px}.run-table td:nth-child(2){white-space:nowrap}@media(max-width:1000px){.run-stages{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:600px){.run-summary{grid-template-columns:1fr}.run-stages{grid-template-columns:repeat(2,minmax(0,1fr))}.run-panel{padding:16px}}

.batch-sidebar .batch-count{display:flex;align-items:baseline;gap:8px;margin:20px 0}.batch-count strong{font-size:36px;color:#1688e8;line-height:1}.batch-count span{font-size:14px}.batch-count small{margin-left:auto;font-size:12px;color:#48786b}.batch-placeholder{padding:18px 16px;margin:18px 0;background:#f3f7fb;border-radius:10px}.batch-placeholder strong{font-size:14px;font-weight:500;color:#526b83}.batch-placeholder p{margin:6px 0 0;font-size:12px}.batch-details{margin:14px 0;font-size:12px}.batch-details summary{cursor:pointer;color:#526b83}.batch-details dl{margin:14px 0}.batch-details dl>div{display:flex;justify-content:space-between;gap:10px;margin:10px 0}.batch-details dt{color:#667e94}.batch-details dd{margin:0;white-space:nowrap}.batch-details small{font-size:11px;line-height:1.6}.preflight-summary{border-top:1px solid #e3ebf3;margin:20px 0;padding-top:18px}.preflight-summary h4{margin:0;font-size:15px}.plumbing-summary{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.plumbing-summary span{padding:5px 8px;border-radius:6px;background:#eef5fb;color:#526b83;font-size:12px}.batch-sidebar .start-caption{text-align:center;font-size:12px;margin:10px 0 0;color:#73899d}

.number-unit{display:flex;align-items:center;gap:8px;min-width:0}.number-unit input{width:140px;min-width:0;box-sizing:border-box}.number-unit>span{flex-shrink:0;color:#667e94;font-size:12px}.axis-controls .number-unit input{width:100%}.compact-fields{max-width:620px;gap:18px 28px}.direction-field{max-width:180px}.compact-notice{padding:10px 14px;font-size:13px;line-height:1.6}.compact-notice p{margin:4px 0}.readonly-value{padding:10px 0;font-size:14px}.form-group{border:1px solid #dce7f1;border-radius:10px;padding:18px;margin:18px 0}.form-group h4{margin:0 0 16px;font-size:14px}.pump-initialization{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.pump-initialization strong{font-size:13px;align-self:center}.pump-initialization label{font-size:12px;gap:5px}.pump-initialization select{padding:7px;font-size:12px}
.guided footer .el-button:not(.is-disabled):not(.is-loading){filter:none;transform:none;transition:background-color .15s,color .15s,border-color .15s;box-shadow:none}.guided footer .el-button:focus-visible{outline:2px solid #1688e8;outline-offset:3px}
@media(max-width:600px){.guided{padding-bottom:148px}.axis-controls{grid-template-columns:1fr}.compact-fields{grid-template-columns:1fr}footer .el-button:last-child{flex-basis:100%}.form-group{padding:14px}.number-unit input{max-width:100%}}

.activity-heading{display:flex;justify-content:space-between;align-items:start;gap:18px}.current-operation h3{font-size:25px;line-height:1.45}.activity-status{padding:7px 12px;border-radius:20px;background:#fff;white-space:nowrap;font-size:13px}.activity-readings{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:20px}.reading{background:#fff;padding:16px;border-radius:10px;display:flex;flex-direction:column;gap:8px;min-width:0}.reading strong{font-size:19px;overflow-wrap:anywhere}.reading span,.reading b{font-size:12px}.reading b{color:#346b69}.current-operation.stale{border-color:#a87925;background:#fff7e8}.control-feedback{padding:12px!important;margin-top:14px!important;background:#fff;border-radius:8px}.run-stages svg{width:28px;height:28px}.run-stages .running{background:#176fbb;border-color:#105692;color:#fff}.run-stages .running small{color:#e5f3ff}.run-stages .completed{background:#eff7f3;border-color:#aacdbb;color:#347455}.run-stages .paused,.run-stages .stopping,.run-stages .cleanup{background:#fff4dd;border-color:#c99b46;color:#80551d}.run-stages .failed{background:#fdf0ed;border-color:#d58a7d;color:#ae4535}.group-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.result-summary{padding:18px;border:1px solid #cbdde9;border-radius:12px;margin:20px 0}.field-error{color:#b83e2e;line-height:1.5}.guided [aria-invalid=true]{border-color:#c54e3f;outline-color:#c54e3f}button:focus-visible{outline:2px solid #176fbb;outline-offset:3px}
.completed-snapshot{padding:16px 20px;background:#f7fafd;border:1px solid #dce7f1;margin-top:14px}.completed-snapshot summary{cursor:pointer;color:#55758f;font-size:13px}.completed-snapshot[open] summary{margin-bottom:20px}
@media(max-width:600px){.activity-heading{flex-direction:column}.activity-readings{grid-template-columns:1fr}.current-operation{padding:18px}.current-operation h3{font-size:22px}.run-stages{grid-template-columns:1fr}.run-stages li{display:grid;grid-template-columns:30px 1fr;align-items:center}.run-stages li small{grid-column:2}}
</style>
