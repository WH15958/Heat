<template>
  <div class="parameter-fields">
    <label v-for="field in fields" :key="field.key">
      <span>{{ field.label }}<b v-if="field.required"> *</b></span>
      <select v-if="field.kind === 'device'" :value="values[field.key] ?? ''" @change="selectValue(field, $event)">
        <option value="">请选择设备</option>
        <option v-if="values[field.key] && !devices.some(d => d.value === values[field.key])" :value="values[field.key]">{{ values[field.key] }}（未知设备）</option>
        <option v-for="d in devices" :key="d.value" :value="d.value">{{ d.label }}</option>
      </select>
      <select v-else-if="field.kind === 'select'" :value="values[field.key] ?? ''" @change="selectValue(field, $event)">
        <option value="">未设置</option>
        <option v-if="values[field.key] != null && !field.options?.some(o => o.value === values[field.key])" :value="values[field.key]">{{ values[field.key] }}（未知选项）</option>
        <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <input v-else-if="field.kind === 'boolean'" type="checkbox" :checked="values[field.key] === true" @change="emit('change', field.key, ($event.target as HTMLInputElement).checked)" />
      <input v-else :type="field.kind === 'number' ? 'number' : 'text'" :min="field.min" :max="field.max" :step="field.integer ? 1 : 'any'" :value="values[field.key] ?? ''" @change="inputValue(field, $event)" />
    </label>
  </div>
</template>
<script setup lang="ts">
import type { Field } from '../../experiment/catalog'
defineProps<{ fields: Field[]; values: Record<string, any>; devices: { value: string; label: string }[] }>()
const emit = defineEmits<{ change: [key: string, value: any] }>()
function selectValue(field: Field, e: Event) {
  const raw = (e.target as HTMLSelectElement).value
  emit('change', field.key, raw === '' ? undefined : field.options?.find(o => String(o.value) === raw)?.value ?? raw)
}
function inputValue(field: Field, e: Event) {
  const raw = (e.target as HTMLInputElement).value
  emit('change', field.key, raw === '' ? undefined : field.kind === 'number' ? Number(raw) : raw)
}
</script>
<style scoped>
.parameter-fields { display: grid; gap: 12px; }
label { display: flex; flex-direction: column; gap: 5px; min-width: 0; font-size: 13px; }
label b { color: #bd394e; }
input, select { box-sizing: border-box; width: 100%; min-width: 0; padding: 8px; border: 1px solid #b9cddd; border-radius: 5px; background: white; color: #243a4b; }
input[type=checkbox] { width: 20px; height: 20px; }
</style>
