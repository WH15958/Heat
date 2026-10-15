import { reactive, ref, type InjectionKey } from 'vue'

export interface ConnectionTarget {
  key: string
  name: string
  connected: () => boolean
  blocked: () => string
  connect: () => Promise<boolean>
  read: () => Promise<void>
}
export interface ConnectionResult {
  key: string
  name: string
  status: 'success' | 'failed' | 'skipped' | 'unknown'
  detail: string
}
export function connectionError(error: any): string {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.message || '请求失败'
}

// Only orchestrates existing connection/read calls; never starts a device.
export function createConnectionBatch() {
  const running = ref(false)
  const pending = reactive(new Set<symbol>())
  const current = ref('')
  const results = ref<ConnectionResult[]>([])
  const message = ref('')
  const total = ref(0)
  let cancelled = false
  function cancel() {
    if (running.value) {
      cancelled = true
      message.value = '已取消后续连接；正在执行的请求结束后停止。'
    }
  }
  async function run(load: () => Promise<ConnectionTarget[]>) {
    if (running.value || pending.size) return
    running.value = true
    cancelled = false
    results.value = []
    total.value = 0
    message.value = '正在读取设备列表…'
    try {
      const targets = await load()
      total.value = targets.length
      for (const target of targets) {
        if (cancelled) break
        current.value = target.key
        message.value = `正在连接 ${target.name}`
        const result: ConnectionResult = { key: target.key, name: target.name, status: 'skipped', detail: '' }
        if (target.connected()) result.detail = '已连接，已跳过'
        else if (target.blocked()) result.detail = target.blocked()
        else {
          let connected = false
          try {
            if (!await target.connect()) throw new Error('设备返回连接失败')
            connected = true
            if (!cancelled) await target.read()
            result.status = cancelled ? 'unknown' : 'success'
            result.detail = cancelled ? '已连接，状态未复查' : '连接成功，已读取状态'
          } catch (error: any) {
            result.status = connected ? 'unknown' : 'failed'
            result.detail = `${connected ? '已连接，状态未知：' : ''}${connectionError(error)}`
            if (error?.response?.status === 409) {
              cancelled = true
              message.value = '设备占用或操作冲突，已停止后续连接。'
            }
          }
        }
        results.value.push(result)
      }
      if (!cancelled) message.value = targets.length ? '连接检查完成，请查看各设备结果。' : '暂无可连接设备。'
    } catch (error) {
      message.value = `设备列表读取失败：${connectionError(error)}`
    } finally {
      current.value = ''
      running.value = false
    }
  }
  return { running, pending, current, results, message, total, run, cancel }
}
export const connectionBatchKey: InjectionKey<ReturnType<typeof createConnectionBatch>> = Symbol('connectionBatch')
