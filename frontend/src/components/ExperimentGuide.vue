<template>
  <el-card class="experiment-guide" shadow="never">
    <div class="guide-heading"><strong>仪器自动化实验指南</strong><span>点击仪器名称，展开设置流程与注意事项</span></div>
    <el-collapse accordion>
      <el-collapse-item v-for="guide in guides" :key="guide.name" :name="guide.name" :title="guide.name">
        <div class="guide-content">
          <section><h4>设置方法</h4><p>{{ guide.settings }}</p></section>
          <section><h4>编排流程</h4><ol><li v-for="item in guide.steps" :key="item">{{ item }}</li></ol></section>
          <section class="guide-notes"><h4>注意事项</h4><ul><li v-for="item in guide.notes" :key="item">{{ item }}</li></ul></section>
        </div>
      </el-collapse-item>
    </el-collapse>
    <p class="guide-footer">开始前在设备控制页连接并核对设备；在“新建实验”或“编辑此实验”中编排，校验、保存后返回本页明确启动。校验通过不代表现场安全已确认。实时状态请查看仪表盘。</p>
  </el-card>
</template>

<script setup lang="ts">
const guides = [
  {
    name: '加热器',
    settings: '选择目标加热器，填写目标温度（°C）。等待到温时设置温度容差与超时；保温使用独立的“等待时长”步骤。',
    steps: ['添加“设置温度”，选择设备并填写温度。', '添加“启动加热”，附加“等待加热器到温”，等待设备与加热设备保持一致。', '添加“等待”并选择“等待时长”，填写保温秒数。', '添加“停止加热”，选择同一设备。'],
    notes: ['到温与定时保温是两个阶段；仅设置温度不等于启动加热。', '暂停实验不会自动停止加热。停止或失败会尝试清理本实验启动的设备；停机失败需现场处理。', '温度、容差及超时按实验要求设置，确认探头、温度限值和现场加热状态。'],
  },
  {
    name: '蠕动泵',
    settings: '选择设备、通道、运行模式、方向、软管型号及流速单位。定时模式填写运行时长与时间单位；定量模式填写分装体积与体积单位；重复运行填写次数和间隔。',
    steps: ['添加“启动泵通道”，填写设备、通道和对应模式参数。', '单次有限运行可附加“等待泵通道完成”，设置同一设备、通道与超时。', '连续流量或重复运行使用有界“等待时长”控制实验持续时间。', '添加“停止泵通道”；需要停止所有通道时使用“停止整台泵”。'],
    notes: ['重复次数 0 表示无限重复。重复或无限运行不能使用“等待泵通道完成”，应定时后明确停止。', '暂停实验不会自动停止泵；不要把暂停当作停止出液。', '检查软管、方向、出口与流量校准。页面流量为设备设定或报告值，不是独立测得的实际出液量。'],
  },
  {
    name: '微波仪',
    settings: '按实验选择手动功率、自动功率或恒速率配置，填写各段温度、功率或升温时间等参数；“启动微波”的模式必须与配置一致。',
    steps: ['添加对应模式的配置动作，填写段参数。', '添加“启动微波”，选择相应模式。', '温控流程附加“等待微波到温”，填写物料目标温度、容差与超时。', '添加有界“等待时长”进行外层计时，再添加“停止微波”。'],
    notes: ['程序完成信号尚需实机确认，不应仅依赖“等待微波完成”结束真实实验。', '确认炉门联锁、非空载、探头安装、接地与散热；运行时需要现场看护。', '暂停不会自动关闭微波输出。停止未确认时需现场按 SOP 处理；关闭浏览器也不会停止设备。'],
  },
  {
    name: '注射泵',
    settings: '选择注射泵，按安装方向设置初始化；吸取或排出填写体积、单位、速度（Hz）和动作超时。绝对定位使用步数；先确认注射器容量、步进模式与当前位置。',
    steps: ['在设备控制页完成安装与液路核对；位置未确认时明确初始化，或在编排中添加“初始化（会运动）”并确认。', '按需添加“切换阀位”，选择进液口、排液口或旁路。', '添加“吸取”或“排出”，填写体积、速度及超时；执行器等待动作完成后进入下一步。', '需要额外等待既有动作时使用“等待注射泵完成”；使用有限程序时设置明确的执行超时。'],
    notes: ['初始化会发生运动；体积为理论活塞排量，需现场核对液体实际输运。', '暂停让已下发动作或有限程序继续完成，不再下发后续动作；恢复不重放。立即中断请使用停止或全局急停。', '超时、过载或位置失信后不要直接继续运动，先核对并恢复可信位置；实验占用期间不能插入手动运动。'],
  },
  {
    name: '三通阀',
    settings: '选择阀门，并明确选择“切到 NO 出口（断电）”或“切到 NC 出口（通电）”。当前接线下对应公共入口通向所选出口。',
    steps: ['先现场确认公共入口、NO/NC 出口与管路连接，并在设备控制页连接阀门。', '在动作库点击目标出口，检查步骤中的设备与目标流路。', '需要切换稳定时间时附加“等待时长”，按实物要求填写秒数。', '后续需要换出口时再添加另一个切换步骤；出液需另行编排泵动作。'],
    notes: ['切换流路不会启动泵；显示位置来自继电器寄存器读回，不能证明实际液路已切换。', '暂停、停止、完成及失败均保持当前阀位；仅由明确步骤切换。实验占用期间禁止手动切换或断开。', 'NO 与 NC 是流体出口标识。两个位置都有通路，断电或急停不代表所有出口关闭；切换失败必须停止实验，不能跳过。'],
  },
]
</script>

<style scoped>
.experiment-guide { margin-bottom: 18px; }
.guide-heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
.guide-heading strong { font-size: 16px; }
.guide-heading span, .guide-footer { color: var(--el-text-color-secondary); font-size: 12px; }
.guide-content { display: grid; grid-template-columns: 1fr 1.2fr 1.2fr; gap: 20px; padding: 8px 4px 12px; }
.guide-content h4 { margin: 0 0 8px; color: var(--el-text-color-primary); }
.guide-content p, .guide-content ol, .guide-content ul { margin: 0; line-height: 1.8; }
.guide-content ol, .guide-content ul { padding-left: 20px; }
.guide-content li + li { margin-top: 6px; }
.guide-notes { border-left: 1px solid var(--el-border-color-lighter); padding-left: 20px; }
.guide-footer { margin: 12px 0 0; line-height: 1.7; }
@media (max-width: 900px) {
  .guide-content { grid-template-columns: 1fr; gap: 16px; }
  .guide-notes { border-left: 0; padding-left: 0; }
}
</style>
