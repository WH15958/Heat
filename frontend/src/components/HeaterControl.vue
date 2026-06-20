<template>
  <el-card shadow="hover" style="margin-bottom: 20px">
    <template #header>
      <div class="card-header">
        <span>加热器 {{ heaterId }} 控制</span>
        <div class="header-tags">
          <el-tag type="info" size="small">串口 {{ heater.connectionPort || '--' }}</el-tag>
          <el-tag :type="heater.connected ? 'success' : 'info'" size="small">
            {{ heater.connected ? '已连接' : '未连接' }}
          </el-tag>
        </div>
      </div>
    </template>
    <el-form label-width="80px" size="default">
      <el-form-item label="连接">
        <el-button v-if="!heater.connected" type="primary" @click="$emit('connect', heaterId)" :loading="heater.loading">
          连接设备
        </el-button>
        <el-button v-else type="danger" @click="$emit('disconnect', heaterId)" :loading="heater.loading">
          断开连接
        </el-button>
      </el-form-item>
      <el-form-item label="目标温度">
        <el-input-number v-model="heater.targetTemp" :min="0" :max="450" :step="1" :precision="1" />
        <el-button type="primary" @click="$emit('setTemp', heaterId, heater.targetTemp)" style="margin-left: 10px">
          设置
        </el-button>
      </el-form-item>
      <el-form-item label="运行控制">
        <el-button type="success" @click="$emit('start', heaterId)" :loading="heater.starting">启动</el-button>
        <el-button type="warning" @click="$emit('stop', heaterId)" :loading="heater.stopping">停止</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  heaterId: string
  heater: {
    connected: boolean
    loading: boolean
    connectionPort?: string
    targetTemp: number
    starting: boolean
    stopping: boolean
  }
}>()

defineEmits<{
  connect: [id: string]
  disconnect: [id: string]
  setTemp: [id: string, temp: number]
  start: [id: string]
  stop: [id: string]
}>()
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.header-tags { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
