import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { HouseOverview } from './components/HouseOverview'
import { InitiativeCard } from './components/InitiativeCard'
import { IssuePanel } from './components/IssuePanel'
import { StatusBadge } from './components/StatusBadge'
import { getMaxLaunchContext, notifyMax, shareIssue } from './maxBridge'
import type { House, HouseState, Issue, SignalResult, ViewerRole } from './types'

const roles: Array<{ id: ViewerRole; label: string; intro: string }> = [
  { id: 'resident', label: 'Житель', intro: 'Сообщить о проблеме и проверить результат' },
  { id: 'representative', label: 'Домоуправляющий', intro: 'Проверить сигналы и решить, что передать' },
  { id: 'uk', label: 'УК / диспетчер', intro: 'Принять обращение и организовать работу' },
  { id: 'executor', label: 'Исполнитель', intro: 'Выполнить назначенную работу и приложить фото' },
]
const demoMessages = ['лифт опять встал, второй подъезд', 'на парковке нужен второй фонарь']

function roleFromQuery(): ViewerRole {
  const value = new URLSearchParams(window.location.search).get('role')
  return roles.some((item) => item.id === value) ? value as ViewerRole : 'resident'
}
function roleLabel(role: ViewerRole) { return roles.find((item) => item.id === role)?.label || 'Житель' }
function roleIntro(role: ViewerRole) { return roles.find((item) => item.id === role)?.intro || '' }

type TaskIssue = Issue & { next_action?: { id: string; label: string } }

function fallbackTasks(state: HouseState, role: ViewerRole): TaskIssue[] {
  // Keeps the public demo useful while an older API image is being rolled out.
  // The server-provided queue remains authoritative whenever it is available.
  const states: Record<ViewerRole, string[]> = {
    resident: ['NEEDS_CONFIRMATION', 'DONE_PENDING_VERIFICATION', 'REOPENED'],
    representative: ['NEEDS_CONFIRMATION', 'CONFIRMED', 'ACTION_READY', 'REOPENED'],
    uk: ['SUBMITTED', 'ACCEPTED', 'WORK_IN_PROGRESS'],
    executor: ['ACCEPTED', 'WORK_IN_PROGRESS'],
  }
  const labels: Record<ViewerRole, Record<string, string>> = {
    resident: { NEEDS_CONFIRMATION: 'У меня тоже', DONE_PENDING_VERIFICATION: 'Проверить результат', REOPENED: 'Посмотреть переоткрытую проблему' },
    representative: { NEEDS_CONFIRMATION: 'Проверить подтверждения', CONFIRMED: 'Выбрать маршрут', ACTION_READY: 'Передать в УК', REOPENED: 'Проверить повторно' },
    uk: { SUBMITTED: 'Принять обращение', ACCEPTED: 'Назначить исполнителя', WORK_IN_PROGRESS: 'Открыть работу' },
    executor: { ACCEPTED: 'Начать работу', WORK_IN_PROGRESS: 'Продолжить работу' },
  }
  const pool = role === 'resident' ? (state.my_issues || []) : state.issues
  return pool.filter((item) => states[role].includes(item.state)).map((item) => ({ ...item, next_action: { id: 'open', label: labels[role][item.state] || 'Открыть' } }))
}

function TaskCard({ issue, onOpen }: { issue: Issue & { next_action?: { id: string; label: string } }; onOpen: () => void }) {
  return <button className="task-card" onClick={onOpen}>
    <div className="task-card__top"><span className="task-dot" /><span>{issue.zone_name || 'Дом'} · {issue.asset_name || issue.category}</span></div>
    <strong>{issue.title}</strong><p>{issue.description || 'Проблема зарегистрирована в доме.'}</p>
    <div className="task-card__bottom"><span>{issue.confirmations_count || 0} подтверждений{issue.recurrence_count ? ` · ${issue.recurrence_count}-й случай` : ''}</span><b>{issue.next_action?.label || 'Открыть'} →</b></div>
  </button>
}

export default function App() {
  const [launchContext] = useState(() => getMaxLaunchContext())
  const [houses, setHouses] = useState<House[]>([])
  const [houseId, setHouseId] = useState('demo-house-a')
  const [role, setRole] = useState<ViewerRole>(() => roleFromQuery())
  const viewerId = launchContext.unsafe?.user?.id || new URLSearchParams(window.location.search).get('viewer') || 'resident-seed-1'
  const [state, setState] = useState<HouseState | null>(null)
  const [issue, setIssue] = useState<Issue | null>(null)
  const [message, setMessage] = useState('')
  const [fallback, setFallback] = useState<SignalResult['fallback']>()
  const [timeline, setTimeline] = useState<{ name: string; events: Array<Record<string, unknown>> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [showHouse, setShowHouse] = useState(false)
  const [showDemo, setShowDemo] = useState(false)
  const [maxUserName, setMaxUserName] = useState<string | null>(launchContext.unsafe?.user?.first_name || null)

  const refresh = useCallback(async () => { setState(await api.state(houseId, viewerId, role)) }, [houseId, role, viewerId])
  useEffect(() => { Promise.all([api.houses(), api.state(houseId, viewerId, role)]).then(([houseList, houseState]) => { setHouses(houseList); setState(houseState) }).catch((reason: Error) => setError(reason.message)) }, [houseId, role, viewerId])
  useEffect(() => { const timer = window.setInterval(() => { void refresh().catch(() => undefined); if (issue?.id) void api.issue(issue.id).then(setIssue).catch(() => undefined) }, 7_000); return () => window.clearInterval(timer) }, [issue?.id, refresh])
  useEffect(() => { if (!launchContext.initData) return; api.validateMaxContext(launchContext.initData).then((context) => setMaxUserName(context.user?.first_name || null)).catch(() => setError('Не удалось подтвердить запуск в MAX. Откройте приложение из сообщения бота ещё раз.')) }, [launchContext.initData])
  useEffect(() => { if (!launchContext.issueId) return; api.issue(launchContext.issueId).then(setIssue).catch(() => undefined) }, [launchContext.issueId])

  async function perform(task: () => Promise<void>) { setBusy(true); setError(null); try { await task() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось выполнить действие') } finally { setBusy(false) } }
  function submitSignal(forceAiFailure = false) { void perform(async () => { const result = await api.signal(houseId, message, undefined, forceAiFailure); setFallback(result.fallback); if (result.issue) setIssue(await api.issue(result.issue.id)); setMessage(''); await refresh() }) }
  function runIssueAction(action: string) {
    if (!issue) return
    void perform(async () => {
      let nextIssue = issue
      if (action === 'confirm') nextIssue = role === 'resident' ? (await api.residentConfirm(issue.id, String(viewerId))).issue : await api.confirm(issue.id)
      if (action === 'submit') nextIssue = await api.submit(issue.id)
      if (action === 'accept') nextIssue = await api.accept(issue.id)
      if (action === 'create-order') { await api.createWorkOrder(issue.id); nextIssue = await api.issue(issue.id) }
      const order = issue.work_orders?.at(-1)
      if (action === 'start' && order) { await api.updateWorkOrder(order.id, 'IN_PROGRESS'); nextIssue = await api.issue(issue.id) }
      if (action === 'evidence' && order) { await api.evidence(order.id); nextIssue = await api.issue(issue.id) }
      if (action === 'done' && order) { await api.updateWorkOrder(order.id, 'DONE'); nextIssue = await api.issue(issue.id) }
      if (action === 'verify-yes') nextIssue = await api.verify(issue.id, 'confirmed', String(viewerId))
      if (action === 'verify-no') nextIssue = await api.verify(issue.id, 'rejected', String(viewerId))
      setIssue(nextIssue); await refresh()
    })
  }
  function openIssue(id: string) { void perform(async () => setIssue(await api.issue(id))) }
  function openAsset(id: string) { void perform(async () => { const result = await api.timeline(id); setTimeline({ name: result.asset.name, events: result.events }) }) }
  function shareCurrentIssue() { if (issue) void perform(async () => { await shareIssue(issue.title, issue.id); notifyMax('success') }) }

  const tasks = useMemo<TaskIssue[]>(() => {
    if (!state) return []
    return state.my_tasks?.length ? state.my_tasks : fallbackTasks(state, role)
  }, [role, state])
  const currentRole = roleLabel(role)
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span>ДП</span><div><strong>ДомПульс</strong><small>{maxUserName ? `${maxUserName}, ваш дом` : 'Ваши задачи по дому'}</small></div></div><div className="topbar-controls"><select aria-label="Выбрать дом" value={houseId} onChange={(event) => { setHouseId(event.target.value); setIssue(null); setTimeline(null) }}>{houses.map((house) => <option key={house.id} value={house.id}>{house.address}</option>)}</select><select aria-label="Выбрать роль для демонстрации" value={role} onChange={(event) => setRole(event.target.value as ViewerRole)}>{roles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div></header>
    <main>
      <section className="hero hero--product"><div><p className="eyebrow">Ваша рабочая очередь</p><h1>{currentRole}</h1><p>{roleIntro(role)}</p><span className="role-note">{state?.house.address || 'Загрузка дома…'}{maxUserName ? ` · ${maxUserName}` : ''}</span></div><button className="secondary hero-action" onClick={() => setShowHouse((value) => !value)}>{showHouse ? 'Скрыть состояние дома' : 'Посмотреть состояние дома'}</button></section>
      {error ? <div className="error" role="alert"><b>Не удалось выполнить действие.</b> {error}<button onClick={() => setError(null)}>×</button></div> : null}
      <section className="task-section"><div className="section-heading"><div><p className="eyebrow">Следующий шаг</p><h2>{role === 'resident' ? 'Ваши обращения' : 'Требуют вашего внимания'}</h2></div><span className="muted">{tasks.length} задач</span></div>{!state ? <div className="skeleton">Загружаем задачи…</div> : tasks.length === 0 ? <div className="empty empty--product"><strong>Сейчас ничего не требует действий</strong><span>{role === 'resident' ? 'Если что-то случилось, сообщите об этом боту в MAX.' : 'Новые задачи появятся здесь автоматически.'}</span></div> : <div className="task-grid">{tasks.slice(0, 6).map((item) => <TaskCard key={item.id} issue={item} onOpen={() => openIssue(item.id)} />)}</div>}{role === 'resident' ? <button className="primary report-button" onClick={() => setShowReport((value) => !value)}>{showReport ? 'Закрыть форму' : 'Сообщить о проблеме'}</button> : null}</section>
      {showReport ? <section className="panel report-panel"><div><p className="eyebrow">Новое обращение</p><h2>Что случилось?</h2><p className="muted">Опишите проблему своими словами. Если места не хватит, бот уточнит его в MAX.</p></div><textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Например: в подъезде не горит лампочка" />{showDemo ? <div className="chips">{demoMessages.map((text) => <button key={text} onClick={() => setMessage(text)}>{text}</button>)}</div> : null}<div className="button-row"><button className="primary" disabled={busy || !message.trim()} onClick={() => submitSignal()}>{busy ? 'Сохраняем…' : 'Зарегистрировать'}</button><button className="ghost" onClick={() => setShowDemo((value) => !value)}>{showDemo ? 'Скрыть демо-инструменты' : 'Это демо'}</button></div>{fallback ? <div className="fallback"><strong>{fallback.message || 'Нужно уточнение'}</strong>{fallback.choices?.map((choice) => <button key={choice.id} onClick={() => setMessage(choice.name)}>{choice.name}</button>)}</div> : null}</section> : null}
      {showHouse && state ? <div className="house-state"><HouseOverview state={state} onIssue={openIssue} onAsset={openAsset} /></div> : null}
      {state?.initiatives.length ? <section className="initiative-section"><div className="section-heading"><div><p className="eyebrow">Общие решения жителей</p><h2>Инициативы</h2></div><span className="muted">{state.initiatives.length}</span></div>{state.initiatives.map((initiative) => <InitiativeCard key={initiative.id} initiative={initiative} busy={busy} onVote={(option) => void perform(async () => { await api.vote(initiative.id, String(viewerId), option); await refresh() })} onHandoff={() => void perform(async () => { await api.handoff(initiative.id); await refresh() })} />)}</section> : null}
      <p className="demo-disclosure">Демонстрация: роль можно переключить сверху. В рабочем MAX она определяется правами пользователя.</p>
    </main>
    {issue ? <IssuePanel issue={issue} role={role} busy={busy} onAction={runIssueAction} onClose={() => setIssue(null)} onShare={shareCurrentIssue} /> : null}
    {timeline ? <div className="drawer-backdrop" role="presentation" onMouseDown={() => setTimeline(null)}><aside className="drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><button className="icon-button" onClick={() => setTimeline(null)} aria-label="Закрыть историю">×</button><p className="eyebrow">История объекта</p><h2>{timeline.name}</h2><div className="timeline">{timeline.events.map((event, index) => <div key={`${String(event.id)}-${index}`}><i /><span><strong>{event.type === 'issue' ? event.title as string : 'Выполненная работа'}</strong><small><StatusBadge value={String(event.state || event.status || 'UNKNOWN')} /></small></span></div>)}</div></aside></div> : null}
  </div>
}
