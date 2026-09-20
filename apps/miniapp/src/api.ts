import type { House, HouseState, Initiative, Issue, SignalResult, ViewerRole, WorkOrder } from './types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Сервис временно недоступен' }))
    throw new Error(body.detail || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  houses: () => request<House[]>('/houses'),
  state: (houseId: string, viewerId?: string | number, role: ViewerRole = 'resident') => {
    const params = new URLSearchParams({ role })
    if (viewerId) params.set('viewer_id', String(viewerId))
    return request<HouseState>(`/houses/${houseId}/state?${params.toString()}`)
  },
  issue: (issueId: string) => request<Issue>(`/issues/${issueId}`),
  signal: (houseId: string, text: string, manualZoneId?: string, forceAiFailure = false) =>
    request<SignalResult>('/signals', {
      method: 'POST',
      body: JSON.stringify({ house_id: houseId, text, manual_zone_id: manualZoneId, force_ai_failure: forceAiFailure }),
    }),
  resolveDuplicate: (signalId: string, candidateIssueId: string, decision: 'LINK' | 'CREATE_NEW') =>
    request<Issue>(`/signals/${signalId}/resolve-duplicate`, {
      method: 'POST',
      body: JSON.stringify({ candidate_issue_id: candidateIssueId, decision }),
    }),
  maxStatus: () => request<{ mode: string; connected: boolean; api_connected?: boolean; polling_active?: boolean; transport?: string; bot?: { first_name?: string }; error?: string }>('/integrations/max/status'),
  validateMaxContext: (initData: string) => request<{ valid: true; user?: { id: number; first_name: string }; chat?: { id: number; type: string }; start_param?: string }>('/integrations/max/init-data/validate', {
    method: 'POST',
    body: JSON.stringify({ init_data: initData }),
  }),
  confirm: (issueId: string) => request<Issue>(`/issues/${issueId}/confirm`, { method: 'POST', body: '{}' }),
  residentConfirm: (issueId: string, actorId: string) => request<{ issue: Issue }>(`/issues/${issueId}/resident-confirm`, { method: 'POST', body: JSON.stringify({ actor_id: actorId }) }),
  submit: (issueId: string) => request<Issue>(`/issues/${issueId}/submit`, { method: 'POST', body: '{}' }),
  accept: (issueId: string) => request<Issue>(`/issues/${issueId}/accept`, { method: 'POST', body: '{}' }),
  createWorkOrder: (issueId: string) =>
    request<WorkOrder>('/work-orders', { method: 'POST', body: JSON.stringify({ issue_id: issueId }) }),
  updateWorkOrder: (orderId: string, status: string) =>
    request<WorkOrder>(`/work-orders/${orderId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  evidence: (orderId: string) =>
    request<WorkOrder>(`/work-orders/${orderId}/evidence`, {
      method: 'POST',
      body: JSON.stringify({ type: 'after_photo', uri: '/demo/elevator-after.svg', comment: 'Контрольный запуск выполнен, кабина работает штатно.' }),
    }),
  verify: (issueId: string, result: 'confirmed' | 'rejected', verifierId = 'resident-seed-1') =>
    request<Issue>(`/issues/${issueId}/verify`, { method: 'POST', body: JSON.stringify({ result, verifier_type: 'resident', verifier_id: verifierId }) }),
  vote: (initiativeId: string, voterId: string, option: string) =>
    request<Initiative>(`/initiatives/${initiativeId}/poll`, { method: 'POST', body: JSON.stringify({ voter_id: voterId, option }) }),
  handoff: (initiativeId: string) =>
    request<Initiative>(`/initiatives/${initiativeId}/handoff`, { method: 'POST', body: '{}' }),
  timeline: (assetId: string) => request<{ asset: { name: string; operational_state: string }; events: Array<Record<string, unknown>> }>(`/assets/${assetId}/timeline`),
}
