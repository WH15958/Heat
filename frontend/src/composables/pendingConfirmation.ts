import { inject, hasInjectionContext, onScopeDispose, type InjectionKey, type Ref } from 'vue'

export const confirmationEpochKey: InjectionKey<Ref<number>> = Symbol('control-confirmations')

// Cancels only commands which have not yet passed their user confirmation.
export function usePendingConfirmation(epoch = hasInjectionContext() ? inject(confirmationEpochKey, undefined) : undefined) {
  let alive = true, generation = 0
  const pending = new Set<string>()
  onScopeDispose(() => { alive = false; generation++ })
  return {
    isActive() { return alive },
    cancel() { generation++ },
    async confirm(key: string, prompt: () => Promise<unknown>, stillValid = () => true) {
      if (!alive || pending.has(key)) return false
      pending.add(key)
      const current = generation, shared = epoch?.value
      try {
        await prompt()
        return alive && current === generation && shared === epoch?.value && stillValid()
      } catch { return false }
      finally { pending.delete(key) }
    },
  }
}
