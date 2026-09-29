<template><div ref="host" class="yaml-editor" /></template>
<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { basicSetup } from 'codemirror'
import { EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { yaml } from '@codemirror/lang-yaml'
const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const host = ref<HTMLElement>()
let view: EditorView | undefined
onMounted(() => {
  view = new EditorView({ parent: host.value, state: EditorState.create({ doc: props.modelValue, extensions: [
    basicSetup, yaml(), EditorView.lineWrapping,
    EditorView.contentAttributes.of({ 'aria-label': '实验 YAML 编辑器' }),
    EditorView.updateListener.of(update => { if (update.docChanged) emit('update:modelValue', update.state.doc.toString()) }),
    EditorView.theme({ '&': { maxHeight: '65vh', minHeight: '320px' }, '.cm-scroller': { overflow: 'auto' } }),
  ] }) })
})
watch(() => props.modelValue, value => {
  if (view && view.state.doc.toString() !== value) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
})
onBeforeUnmount(() => view?.destroy())
</script>
<style scoped>.yaml-editor { border: 1px solid var(--el-border-color); border-radius: 6px; overflow: hidden; text-align: left; }</style>
