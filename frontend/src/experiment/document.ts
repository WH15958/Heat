import { isAlias, isMap, isNode, isSeq, parseAllDocuments, visit, type Document } from 'yaml'

export type Path = (string | number)[]
export interface Step {
  id: string; type: string; params?: Record<string, any>; wait?: Record<string, any>
  enabled?: boolean; on_error?: string; [key: string]: any
}
export const emptySource = 'name: 新实验\ndescription: ""\nmetadata: {}\nsteps: []\n'

export function inspectSource(source: string) {
  const docs = parseAllDocuments(source, { keepSourceTokens: true, version: '1.1' })
  const doc = docs[0]
  const errors = docs.flatMap(d => d.errors.map(e => `${e.linePos?.[0]?.line ?? '?'}:${e.linePos?.[0]?.col ?? '?'} ${e.message}`))
  let restriction = ''
  if (docs.length !== 1) restriction = '多文档 YAML 只能在 YAML 模式编辑。'
  if (doc) {
    visit(doc, (_, node) => {
      if (isAlias(node) || (node && typeof node === 'object' && ('anchor' in node && node.anchor || 'tag' in node && node.tag))) {
        restriction = '包含锚点、别名或显式标签，请在 YAML 模式编辑，以保留原始含义。'
      }
      if (isMap(node) && node.items.some(p => String(p.key) === '<<' || (p.key && typeof p.key === 'object' && 'value' in p.key && typeof p.key.value === 'symbol'))) restriction = '包含合并键，请在 YAML 模式编辑。'
    })
    if (!isMap(doc.contents) || !isSeq(doc.get('steps', true))) restriction ||= '图形模式需要顶层对象及 steps 列表。'
    const steps = doc.get('steps', true)
    if (isSeq(steps) && steps.items.some(s => !isMap(s))) restriction ||= '每个步骤必须是对象。'
    if (isSeq(steps)) for (const s of steps.items) if (isMap(s)) {
      if (typeof s.get('type') !== 'string') restriction ||= '每个步骤需要文本动作类型。'
      if (s.has('id') && typeof s.get('id') !== 'string') restriction ||= '步骤 ID 必须是文本。'
      for (const key of ['params', 'wait']) if (s.has(key) && !isMap(s.get(key, true))) restriction ||= `${key} 必须是对象。`
      const segments = s.getIn(['params', 'segments'], true)
      if (segments && (!isSeq(segments) || segments.items.some(item => !isMap(item)))) restriction ||= '微波段参数必须为对象列表。'
    }
    if (doc.has('metadata') && doc.get('metadata') != null && !isMap(doc.get('metadata', true))) restriction ||= 'metadata 必须是对象。'
  }
  return { doc, errors, restriction, editable: !!doc && !errors.length && !restriction }
}

export function editSource(source: string, change: (doc: Document) => void) {
  const state = inspectSource(source)
  if (!state.editable) throw new Error(state.errors.join('\n') || state.restriction)
  change(state.doc!)
  return state.doc!.toString()
}

export function setValue(doc: Document, path: Path, value: unknown) {
  if (value === undefined || value === '') { doc.deleteIn(path); return }
  doc.setIn(path, value)
}

// Patch existing maps instead of replacing them so untouched values and comments survive.
export function patchMap(doc: Document, path: Path, value: Record<string, unknown>) {
  const previous = doc.getIn(path, true)
  if (!isMap(previous)) { doc.setIn(path, value); return }
  for (const pair of [...previous.items]) if (!(String(pair.key) in value)) doc.deleteIn([...path, String(pair.key)])
  for (const [key, next] of Object.entries(value)) {
    if (next && typeof next === 'object' && !Array.isArray(next)) patchMap(doc, [...path, key], next as Record<string, unknown>)
    else {
      const old = doc.getIn([...path, key], true)
      const plain = isNode(old) ? old.toJSON() : old
      if (JSON.stringify(plain) !== JSON.stringify(next)) doc.setIn([...path, key], next)
    }
  }
}

export function uniqueId(doc: Document, type: string) {
  const list = doc.get('steps', true)
  const ids = new Set(isSeq(list) ? list.items.filter(isMap).map(s => s.get('id')) : [])
  const prefix = type.replaceAll('.', '_')
  let n = 1
  while (ids.has(`${prefix}_${n}`)) n++
  return `${prefix}_${n}`
}

export function moveStep(doc: Document, from: number, to: number) {
  const steps = doc.get('steps', true)
  if (!isSeq(steps) || from < 0 || to < 0 || from >= steps.items.length || to >= steps.items.length) return
  const [item] = steps.items.splice(from, 1)
  steps.items.splice(to, 0, item!)
}

export function duplicateStep(doc: Document, index: number) {
  const list = doc.get('steps', true)
  if (!isSeq(list)) return
  const original = list.items[index]
  if (!isMap(original)) return
  const copy = original.clone()
  copy.set('id', uniqueId(doc, String(copy.get('type'))))
  list.items.splice(index + 1, 0, copy)
}

export function stepsFrom(doc: Document | undefined): Step[] {
  if (!doc) return []
  return doc.toJS({ maxAliasCount: 50 })?.steps ?? []
}
