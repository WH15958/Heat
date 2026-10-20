import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

const source = readFileSync(new URL('../src/components/BatchCompletionPanel.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'batch-completion', inlineTemplate: true }).content
const compiled = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const exports = {} as any
runInNewContext(compiled, { exports, require: () => vue })

async function render(persistenceStatus?: string) {
  const app = vue.createSSRApp(exports.default, { experimentName: '本次水测', completedCount: 3, totalCount: 3, persistenceStatus })
  app.component('el-button', { template: '<button><slot /></button>' })
  return renderToString(app)
}

test('completed batch highlights experiment, groups and exact record state with result actions', async () => {
  const html = await render('ok')
  assert.match(html, /本批实验已完成/)
  assert.match(html, /本次水测/)
  assert.match(html, /3 <span>\/ 3 组/)
  assert.match(html, /已保存/)
  assert.doesNotMatch(html, /清理已确认/)
  assert.match(html, /查看本批历史/)
  assert.match(html, /导出本批记录/)
  assert.doesNotMatch(html, /最后动作快照/)
})

test('record failures and unknown persistence never claim saved records', async () => {
  const failed = await render('error')
  assert.match(failed, /保存失败/)
  assert.match(failed, /请先处理记录恢复/)
  assert.doesNotMatch(failed, /已保存/)
  const unknown = await render()
  assert.match(unknown, /保存状态未确认/)
  assert.doesNotMatch(unknown, /已保存/)
})
