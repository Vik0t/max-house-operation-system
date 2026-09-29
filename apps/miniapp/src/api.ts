import type { House, HouseState, Initiative, Issue, SignalResult, ViewerRole, WorkOrder } from './types'
import { localStore } from './localStore'
import { getMaxLaunchContext } from './maxBridge'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const forcedLocal = new URLSearchParams(window.location.search).get('local') === 'true'

async function remote<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const isRead = !options?.method || options.method.toUpperCase() === 'GET'
  const timeout = window.setTimeout(() => controller.abort(), isRead ? 45_000 : 120_000)
  try {
    for (let attempt = 0; attempt < (isRead ? 3 : 1); attempt++) {
      let response: Response
      try {
        response = await fetch(`${API_URL}${path}`, {
          ...options,
          signal: controller.signal,
          headers: { 'Content-Type': 'application/json', ...(getMaxLaunchContext().initData ? { 'X-Max-Init-Data': getMaxLaunchContext().initData } : {}), ...options?.headers },
        })
      } catch (error) {
        if (isRead && error instanceof TypeError && !controller.signal.aborted && attempt < 2) {
          await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)))
          continue
        }
        throw error
      }
      if (!response.ok) {
        if (isRead && [502, 503, 504].includes(response.status) && attempt < 2) {
          await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)))
          continue
        }
        const body = await response.json().catch(() => ({ detail: 'Сервис временно недоступен' }))
        throw new Error(body.detail || `HTTP ${response.status}`)
      }
      return await response.json() as T
    }
    throw new Error('Сервер временно недоступен. Попробуйте позже.')
  } catch (error) {
    if (controller.signal.aborted) throw new Error(isRead
      ? 'Сервер отвечает слишком долго. Нажмите «Повторить».'
      : 'Ответ задержался. Сначала проверьте статус обращения, прежде чем повторять действие.')
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

// Local demo is explicit (?local=true); production failures must stay visible.
async function withFallback<T>(remoteFn: () => Promise<T>, localFn: () => Promise<T>): Promise<T> {
  if (forcedLocal) return localFn()
  try { return await remoteFn() }
  catch (error) {
    if (error instanceof TypeError) throw new Error('Сервер ДомПульса недоступен. Данные не сохранены — попробуйте позже.')
    throw error
  }
}

export const api = {
  houses: () =>
    withFallback(
      () => remote<House[]>('/houses'),
      () => localStore.houses(),
    ),

  identity: (initData: string) => remote<{ user_id: string; role: ViewerRole; selected_house_id: string | null; residency_status: string | null; verified_resident: boolean }>('/identity/max', { method: 'POST', body: JSON.stringify({ init_data: initData }) }),
  selectHouse: (initData: string, houseId: string) => remote<{ selected_house_id: string }>('/identity/max/house', { method: 'POST', body: JSON.stringify({ init_data: initData, house_id: houseId }) }),

  state: (houseId: string, viewerId?: string | number, role: ViewerRole = 'resident') => {
    const params = new URLSearchParams({ role })
    if (viewerId) params.set('viewer_id', String(viewerId))
    return withFallback(
      () => remote<HouseState>(`/houses/${houseId}/state?${params}`),
      () => localStore.state(houseId, viewerId, role),
    )
  },

  issue: (issueId: string) =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}`),
      () => localStore.issue(issueId),
    ),

  signal: (houseId: string, text: string, manualZoneId?: string, forceAiFailure = false, photos: string[] = [], authorId = 'resident-demo') =>
    withFallback(
      () => remote<SignalResult>('/signals', {
        method: 'POST',
        body: JSON.stringify({ house_id: houseId, text, author_id: authorId, manual_zone_id: manualZoneId, force_ai_failure: forceAiFailure, attachments: photos.map((uri) => ({ type: 'image', uri })) }),
      }),
      () => localStore.signal(houseId, text, manualZoneId, forceAiFailure, photos, authorId),
    ),

  resolveSignal: (signalId: string, category: string, zoneId: string) => remote<SignalResult>(`/signals/${signalId}/resolve`, { method: 'POST', body: JSON.stringify({ category, zone_id: zoneId }) }),

  resolveDuplicate: (signalId: string, candidateIssueId: string, decision: 'LINK' | 'CREATE_NEW') =>
    withFallback(
      () => remote<Issue>(`/signals/${signalId}/resolve-duplicate`, {
        method: 'POST',
        body: JSON.stringify({ candidate_issue_id: candidateIssueId, decision }),
      }),
      () => localStore.resolveDuplicate(signalId, candidateIssueId, decision),
    ),

  comment: (issueId: string, text: string, authorRole: string, authorId: string, photos: string[] = []) =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/comments`, {
        method: 'POST',
        body: JSON.stringify({ text, author_role: authorRole, author_id: authorId, photos }),
      }),
      () => localStore.addComment(issueId, text, authorRole, authorId, photos),
    ),

  addHouse: (house: House) =>
    withFallback(
      () => remote<House>('/houses', { method: 'POST', body: JSON.stringify({ id: house.id, address: house.address, lat: house.lat, lng: house.lng, entrances: house.metadata?.entrances || 1, management_org: house.management_org, condition: house.condition || 'Нет данных' }) }),
      () => localStore.addHouse(house),
    ),

  maxStatus: () =>
    withFallback(
      () => remote<{ mode: string; connected: boolean; api_connected?: boolean; polling_active?: boolean; transport?: string; bot?: { first_name?: string }; error?: string }>('/integrations/max/status'),
      () => localStore.maxStatus(),
    ),

  validateMaxContext: (initData: string) =>
    withFallback(
      () => remote<{ valid: true; user?: { id: number; first_name: string }; chat?: { id: number; type: string }; start_param?: string }>('/integrations/max/init-data/validate', {
        method: 'POST',
        body: JSON.stringify({ init_data: initData }),
      }),
      () => localStore.validateMaxContext(initData),
    ),

  confirm: (issueId: string) =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/confirm`, { method: 'POST', body: '{}' }),
      () => localStore.confirm(issueId),
    ),

  prepare: (issueId: string) =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/prepare`, { method: 'POST', body: '{}' }),
      () => localStore.prepare(issueId),
    ),

  route: (issueId: string, destination: 'management_org' | 'representative') =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/route`, { method: 'POST', body: JSON.stringify({ destination }) }),
      () => localStore.issue(issueId),
    ),

  residentConfirm: (issueId: string, actorId: string) =>
    withFallback(
      () => remote<{ issue: Issue }>(`/issues/${issueId}/resident-confirm`, { method: 'POST', body: JSON.stringify({ actor_id: actorId }) }),
      () => localStore.residentConfirm(issueId, actorId),
    ),

  submit: (issueId: string) =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/submit`, { method: 'POST', body: '{}' }),
      () => localStore.submit(issueId),
    ),

  accept: (issueId: string) =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/accept`, { method: 'POST', body: '{}' }),
      () => localStore.accept(issueId),
    ),

  createWorkOrder: (issueId: string) =>
    withFallback(
      () => remote<WorkOrder>('/work-orders', { method: 'POST', body: JSON.stringify({ issue_id: issueId }) }),
      () => localStore.createWorkOrder(issueId) as Promise<WorkOrder>,
    ),

  updateWorkOrder: (orderId: string, status: string) =>
    withFallback(
      () => remote<WorkOrder>(`/work-orders/${orderId}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
      () => localStore.updateWorkOrder(orderId, status) as Promise<WorkOrder>,
    ),

  evidence: (orderId: string, uri: string, comment: string) =>
    withFallback(
      () => remote<WorkOrder>(`/work-orders/${orderId}/evidence`, {
        method: 'POST',
        body: JSON.stringify({ type: 'after_photo', uri, comment }),
      }),
      () => localStore.evidence(orderId) as Promise<WorkOrder>,
    ),

  verify: (issueId: string, result: 'confirmed' | 'rejected', verifierId = 'resident-seed-1') =>
    withFallback(
      () => remote<Issue>(`/issues/${issueId}/verify`, { method: 'POST', body: JSON.stringify({ result, verifier_type: 'resident', verifier_id: verifierId }) }),
      () => localStore.verify(issueId, result, verifierId),
    ),

  vote: (initiativeId: string, voterId: string, option: string) =>
    withFallback(
      () => remote<Initiative>(`/initiatives/${initiativeId}/poll`, { method: 'POST', body: JSON.stringify({ voter_id: voterId, option }) }),
      () => localStore.vote(initiativeId, voterId, option),
    ),

  handoff: (initiativeId: string) =>
    withFallback(
      () => remote<Initiative>(`/initiatives/${initiativeId}/handoff`, { method: 'POST', body: '{}' }),
      () => localStore.handoff(initiativeId),
    ),

  timeline: (assetId: string) =>
    withFallback(
      () => remote<{ asset: { name: string; operational_state: string }; events: Array<Record<string, unknown>> }>(`/assets/${assetId}/timeline`),
      () => localStore.timeline(assetId),
    ),
}
