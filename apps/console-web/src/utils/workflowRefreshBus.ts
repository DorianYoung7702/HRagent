import type { WorkflowEvent } from '../types'

type RefreshListener = (reason: string) => void

const listeners = new Map<string, Set<RefreshListener>>()

export function subscribeWorkflowRefresh(workflowId: string, listener: RefreshListener): () => void {
  let set = listeners.get(workflowId)
  if (!set) {
    set = new Set()
    listeners.set(workflowId, set)
  }
  set.add(listener)
  return () => {
    set?.delete(listener)
    if (set?.size === 0) {
      listeners.delete(workflowId)
    }
  }
}

export function notifyWorkflowRefresh(workflowId: string, reason: string) {
  listeners.get(workflowId)?.forEach((listener) => listener(reason))
}

/** SSE 事件是否应触发清单/进度刷新 */
export function shouldRefreshFromEvent(ev: WorkflowEvent): boolean {
  const phase = ev.meta?.phase as string | undefined
  if (ev.category === 'screen') {
    return phase === 'complete' || phase === 'decision' || phase === 'error'
  }
  if (ev.category === 'control') return true
  if (ev.category === 'search' || ev.category === 'fetch') return true
  return false
}
