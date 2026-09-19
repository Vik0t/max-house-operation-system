import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { HouseOverview } from './components/HouseOverview'
import { InitiativeCard } from './components/InitiativeCard'
import { IssuePanel } from './components/IssuePanel'
import type { House, HouseState, Initiative, Issue, SignalResult } from './types'

const demoMessages = [
  'лифт опять встал, второй подъезд',
  'у меня тоже',
  'вчера уже не работал лифт во втором подъезде',
  'на парковке нужен второй фонарь',
]

export default function App() {
  const [houses, setHouses] = useState<House[]>([])
  const [houseId, setHouseId] = useState('demo-house-a')
  const [state, setState] = useState<HouseState | null>(null)
  const [issue, setIssue] = useState<Issue | null>(null)
  const [message, setMessage] = useState(demoMessages[0])
  const [fallback, setFallback] = useState<SignalResult['fallback']>()
  const [timeline, setTimeline] = useState<{ name: string; events: Array<Record<string, unknown>> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [maxConnection, setMaxConnection] = useState<'CHECKING' | 'CONNECTED' | 'CONFIGURED' | 'SIMULATED'>('CHECKING')
  const [fallbackSignalId, setFallbackSignalId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const next = await api.state(houseId)
    setState(next)
  }, [houseId])

  useEffect(() => {
    Promise.all([api.houses(), api.state(houseId)])
      .then(([houseList, houseState]) => { setHouses(houseList); setState(houseState) })
      .catch((reason: Error) => setError(reason.message))
  }, [houseId])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined)
      if (issue?.id) void api.issue(issue.id).then(setIssue).catch(() => undefined)
    }, 5_000)
    return () => window.clearInterval(timer)
  }, [issue?.id, refresh])

  useEffect(() => {
    const checkMax = () => api.maxStatus()
      .then((result) => setMaxConnection(result.mode === 'SIMULATED' ? 'SIMULATED' : result.connected ? 'CONNECTED' : 'CONFIGURED'))
      .catch(() => setMaxConnection('CONFIGURED'))
    void checkMax()
    const timer = window.setInterval(() => { void checkMax() }, 20_000)
    return () => window.clearInterval(timer)
  }, [])

  async function perform(task: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try { await task() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Неизвестная ошибка') } finally { setBusy(false) }
  }

  function submitSignal(forceAiFailure = false, manualZoneId?: string) {
    void perform(async () => {
      const result = await api.signal(houseId, message, manualZoneId, forceAiFailure)
      setFallback(result.fallback)
      setFallbackSignalId(result.signal?.id || null)
      if (result.issue) setIssue(await api.issue(result.issue.id))
      if (result.initiative) setMessage('')
      await refresh()
    })
  }

  function runIssueAction(action: string) {
    if (!issue) return
    void perform(async () => {
      let nextIssue = issue
      if (action === 'confirm') nextIssue = await api.confirm(issue.id)
      if (action === 'submit') nextIssue = await api.submit(issue.id)
      if (action === 'accept') nextIssue = await api.accept(issue.id)
      if (action === 'create-order') { await api.createWorkOrder(issue.id); nextIssue = await api.issue(issue.id) }
      const order = issue.work_orders?.at(-1)
      if (action === 'start' && order) { await api.updateWorkOrder(order.id, 'IN_PROGRESS'); nextIssue = await api.issue(issue.id) }
      if (action === 'restart' && order) { await api.updateWorkOrder(order.id, 'IN_PROGRESS'); nextIssue = await api.issue(issue.id) }
      if (action === 'evidence' && order) { await api.evidence(order.id); nextIssue = await api.issue(issue.id) }
      if (action === 'done' && order) { await api.updateWorkOrder(order.id, 'DONE'); nextIssue = await api.issue(issue.id) }
      if (action === 'verify-yes') nextIssue = await api.verify(issue.id, 'confirmed')
      if (action === 'verify-no') nextIssue = await api.verify(issue.id, 'rejected')
      setIssue(nextIssue)
      await refresh()
    })
  }

  function updateInitiative(task: () => Promise<Initiative>) {
    void perform(async () => { await task(); await refresh() })
  }

  function resolveDuplicate(decision: 'LINK' | 'CREATE_NEW') {
    const candidateId = fallback?.candidate?.id
    if (!fallbackSignalId || !candidateId) return
    void perform(async () => {
      setIssue(await api.resolveDuplicate(fallbackSignalId, candidateId, decision))
      setFallback(undefined)
      setFallbackSignalId(null)
      await refresh()
    })
  }

  function openIssue(id: string) {
    void perform(async () => setIssue(await api.issue(id)))
  }

  function openAsset(id: string) {
    void perform(async () => {
      const result = await api.timeline(id)
      setTimeline({ name: result.asset.name, events: result.events })
    })
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span>ДП</span><div><strong>ДомПульс</strong><small>операционная память дома</small></div></div>
        <select aria-label="Выбрать дом" value={houseId} onChange={(event) => { setHouseId(event.target.value); setIssue(null); setTimeline(null) }}>
          {houses.map((house) => <option key={house.id} value={house.id}>{house.address}</option>)}
        </select>
      </header>

      <main>
        <section className="hero">
          <div>
            <p className="eyebrow">Состояние дома · сейчас</p>
            <h1>{state?.house.address || 'Загрузка дома…'}</h1>
            <p>{state?.house.management_org}</p>
          </div>
          <div className="integration-badges">
            <span className={maxConnection === 'CONNECTED' ? 'real' : maxConnection === 'SIMULATED' ? 'simulated' : 'configured'}>
              MAX {maxConnection === 'CONNECTED' ? 'REAL · BOT ONLINE' : maxConnection === 'CHECKING' ? 'CHECKING' : maxConnection === 'SIMULATED' ? 'SIMULATED' : 'REAL · CONFIGURED'}
            </span>
            <span className="simulated">УК SIMULATED</span>
          </div>
        </section>

        {error ? <div className="error" role="alert"><b>Не удалось выполнить действие.</b> {error}<button onClick={() => setError(null)}>×</button></div> : null}

        <section className="composer panel">
          <div><p className="eyebrow">MAX / Direct input</p><h2>Сообщение жителя</h2></div>
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Опишите проблему обычными словами" />
          <div className="chips">
            {demoMessages.map((text) => <button key={text} onClick={() => setMessage(text)}>{text}</button>)}
          </div>
          <div className="button-row">
            <button className="primary" disabled={busy || !message.trim()} onClick={() => submitSignal()}>{busy ? 'Разбираем…' : 'Отправить сигнал'}</button>
            <button className="ghost" disabled={busy || !message.trim()} onClick={() => submitSignal(true)}>Проверить AI fallback</button>
          </div>
          {fallback ? (
            <div className="fallback">
              <strong>{fallback.message || 'Требуется выбор пользователя'}</strong>
              {fallback.choices?.map((choice) => <button key={choice.id} onClick={() => submitSignal(false, choice.id)}>{choice.name}</button>)}
              {fallback.type === 'DUPLICATE_CONFIRMATION' ? <button onClick={() => resolveDuplicate('LINK')}>Связать</button> : null}
              {fallback.type === 'DUPLICATE_CONFIRMATION' ? <button onClick={() => resolveDuplicate('CREATE_NEW')}>Создать новую проблему</button> : null}
            </div>
          ) : null}
        </section>

        {state ? <HouseOverview state={state} onIssue={openIssue} onAsset={openAsset} /> : <div className="skeleton">Загружаем состояние дома…</div>}

        {state?.initiatives.map((initiative) => (
          <InitiativeCard
            key={initiative.id}
            initiative={initiative}
            busy={busy}
            onVote={(option) => updateInitiative(() => api.vote(initiative.id, `resident-${Date.now()}`, option))}
            onHandoff={() => updateInitiative(() => api.handoff(initiative.id))}
          />
        ))}
      </main>

      {issue ? <IssuePanel issue={issue} busy={busy} onAction={runIssueAction} onClose={() => setIssue(null)} /> : null}
      {timeline ? (
        <div className="drawer-backdrop" role="presentation" onMouseDown={() => setTimeline(null)}>
          <aside className="drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <button className="icon-button" onClick={() => setTimeline(null)} aria-label="Закрыть timeline">×</button>
            <p className="eyebrow">Asset timeline</p><h2>{timeline.name}</h2>
            <div className="timeline">
              {timeline.events.map((event, index) => (
                <div key={`${String(event.id)}-${index}`}><i /><span><strong>{event.type === 'issue' ? event.title as string : 'Выполненная работа'}</strong><small>{String(event.state || event.status || '')}</small></span></div>
              ))}
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  )
}
