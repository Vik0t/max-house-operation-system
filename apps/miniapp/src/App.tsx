import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { HouseOverview } from './components/HouseOverview'
import { InitiativeCard } from './components/InitiativeCard'
import { IssuePanel } from './components/IssuePanel'
import { StatusBadge } from './components/StatusBadge'
import { issueAssetLabel, pluralRu, severityLabel, severityTone } from './labels'
import { resetLocalStore } from './localStore'
import { mascot } from './mascot'
import { Tour, type TourStep } from './components/Tour'
import { ChatBubble } from './components/ChatBubble'
import { SignalList } from './components/SignalList'
import { PhotoInput } from './components/PhotoInput'
import { mediaSrc } from './media'
import { HouseMap } from './components/HouseMap'
import { KOLTSOVO_CENTER, koltsovoHouses } from './data/koltsovo'
import { geocodeAddress as geocodeYandex, mapsConfigured, reverseGeocode } from './yandexMaps'
import { getMaxLaunchContext, notifyMax, shareIssue } from './maxBridge'
import type { House, HouseState, Issue, SignalResult, ViewerRole } from './types'

const roles: Array<{ id: ViewerRole; label: string; intro: string }> = [
  { id: 'resident', label: 'Житель', intro: 'Сообщить о проблеме и проверить результат' },
  { id: 'representative', label: 'Домоуправляющий', intro: 'Проверить сигналы и решить, что передать' },
  { id: 'uk', label: 'УК / диспетчер', intro: 'Принять обращение и организовать работу' },
  { id: 'executor', label: 'Исполнитель', intro: 'Выполнить назначенную работу и приложить фото' },
]
const demoMessages = ['лифт опять встал, второй подъезд', 'на парковке нужен второй фонарь', 'протечка в подвале']

const tourSteps: TourStep[] = [
  { title: 'Привет, я Макс!', body: 'Я голубь и помогу разобраться в ЖКХ. За минуту покажу, как всё устроено.', mascot: mascot.hero },
  { tab: 'tasks', target: '[data-tour="role"]', title: 'Ваша роль', body: 'В MAX роль определяется вашим доступом. В отдельном демо-режиме можно посмотреть путь других участников.', mascot: mascot.tip },
  { tab: 'tasks', target: '[data-tour="tasks"]', title: 'Задачи по дому', body: 'Здесь то, что требует внимания: подтвердить проблему, передать в УК или проверить результат.', mascot: mascot.tip },
  { tab: 'tasks', target: '[data-tour="report"]', title: 'Сообщить о проблеме', body: 'Опишите проблему словами — система определит объект и подскажет следующий шаг.', mascot: mascot.report },
  { tab: 'house', target: '[data-tour="house"]', title: 'Раздел «Дом»', body: 'Сводка и состояние дома: активные проблемы, работа, повторяющиеся случаи, инициативы.', mascot: mascot.calm },
  { tab: 'initiatives', target: '[data-tour="initiatives"]', title: 'Раздел «Инициативы»', body: 'Общие решения жителей: голосуйте за предложения и фиксируйте результат.', mascot: mascot.announce },
  { tab: 'more', target: '[data-tour="more"]', title: 'Раздел «Ещё»', body: 'Профиль, доступы и подсказки по работе сервиса.', mascot: mascot.hero },
]

function roleFromQuery(): ViewerRole {
  const query = new URLSearchParams(window.location.search)
  if (query.get('local') !== 'true' && !(import.meta.env.VITE_ALLOW_REMOTE_DEMO === 'true' && query.get('demo') === 'true')) return 'resident'
  const value = new URLSearchParams(window.location.search).get('role')
  return roles.some((item) => item.id === value) ? value as ViewerRole : 'resident'
}
function roleLabel(role: ViewerRole) { return roles.find((item) => item.id === role)?.label || 'Житель' }
function roleIntro(role: ViewerRole) { return roles.find((item) => item.id === role)?.intro || '' }

const chevron = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
const taskIcon = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="m9 14 2 2 4-4"/></svg>
const homeIcon = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
const peopleIcon = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
const bellIcon = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
const plusIcon = <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>

function TaskCard({ issue, onOpen }: { issue: Issue & { next_action?: { id: string; label: string } }; onOpen: () => void }) {
  const isOk = ['DONE_PENDING_VERIFICATION', 'WORK_IN_PROGRESS', 'VERIFIED', 'CLOSED'].includes(issue.state)
  return <button className="task-card" onClick={onOpen}>
    <div className="task-card-top">
      <span className={`task-dot${isOk ? ' task-dot--ok' : ''}`} />
      <span>{issue.zone_name || 'Дом'} · {issueAssetLabel(issue)}</span>
      <span className={`severity ${severityTone(issue.severity)} task-card-top-end`}>{severityLabel(issue.severity)}</span>
    </div>
    <div className="task-card-title">{issue.title}</div>
    <div className="task-card-desc">{issue.description || 'Проблема зарегистрирована в доме.'}</div>
    <div className="task-card-bottom">
      <span>{issue.confirmations_count || 0} {pluralRu(issue.confirmations_count || 0, 'подтверждение', 'подтверждения', 'подтверждений')}{issue.related_issue_count && issue.related_issue_count > 1 ? ` · похожих обращений: ${issue.related_issue_count - 1}` : ''}{issue.recurrence_count ? ` · ${issue.recurrence_count}-й случай` : ''}</span>
      <span className="task-card-action">{issue.next_action?.label || 'Открыть'} →</span>
    </div>
  </button>
}

type NavTab = 'tasks' | 'house' | 'initiatives' | 'archive' | 'more'

export default function App() {
  const remoteDemo = import.meta.env.VITE_ALLOW_REMOTE_DEMO === 'true' && new URLSearchParams(window.location.search).get('demo') === 'true'
  const [launchContext] = useState(() => getMaxLaunchContext())
  const [houses, setHouses] = useState<House[]>([])
  const [houseId, setHouseId] = useState('demo-house-a')
  const [role, setRole] = useState<ViewerRole>(() => roleFromQuery())
  const [maxIdentity, setMaxIdentity] = useState<{ user_id: string; role: ViewerRole; selected_house_id: string | null; verified_resident: boolean } | null>(null)
  const viewerId = maxIdentity?.user_id || ((import.meta.env.DEV || new URLSearchParams(window.location.search).get('local') === 'true' || remoteDemo) ? 'resident-seed-1' : 'guest')
  const localDemo = import.meta.env.DEV || new URLSearchParams(window.location.search).get('local') === 'true'
  const canSelectHouse = Boolean(maxIdentity || localDemo || remoteDemo)
  const canWrite = Boolean(localDemo || remoteDemo || (maxIdentity?.selected_house_id && maxIdentity.selected_house_id === houseId))
  const [state, setState] = useState<HouseState | null>(null)
  const [issue, setIssue] = useState<Issue | null>(null)
  const [message, setMessage] = useState('')
  const [photos, setPhotos] = useState<string[]>([])
  const [houseDraft, setHouseDraft] = useState<{ address: string; management_org: string; condition: string; lat: number | null; lng: number | null }>({ address: '', management_org: '', condition: '', lat: null, lng: null })
  const [resolvingAddress, setResolvingAddress] = useState(false)
  const [mapNotice, setMapNotice] = useState<string | null>(null)
  const [fallback, setFallback] = useState<SignalResult['fallback']>()
  const [timeline, setTimeline] = useState<{ name: string; events: Array<Record<string, unknown>> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [overviewLoading, setOverviewLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [showDemo, setShowDemo] = useState(false)
  const [activeTab, setActiveTab] = useState<NavTab>(() => launchContext.initData || localDemo || remoteDemo ? 'tasks' : 'house')
  const [maxUserName, setMaxUserName] = useState<string | null>(launchContext.unsafe?.user?.first_name || null)
  const [showNotifs, setShowNotifs] = useState(false)
  const [tourOpen, setTourOpen] = useState(false)
  const [mapPreview, setMapPreview] = useState<House | null>(null)
  const [pendingSignalId, setPendingSignalId] = useState<string | null>(null)
  const [fallbackCategory, setFallbackCategory] = useState('other')
  const [houseSearch, setHouseSearch] = useState('')

  const refresh = useCallback(async () => { setState(await api.state(houseId, viewerId, role)) }, [houseId, role, viewerId])
  const loadOverview = useCallback(async () => {
    setOverviewLoading(true)
    setError(null)
    try {
      const [houseList, houseState] = await Promise.all([api.houses(), api.state(houseId, viewerId, role)])
      setHouses(houseList)
      setState(houseState)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось загрузить дом')
    } finally {
      setOverviewLoading(false)
    }
  }, [houseId, role, viewerId])
  useEffect(() => { void loadOverview() }, [loadOverview])
  useEffect(() => {
    let stopped = false
    let timer = 0
    const tick = async () => {
      if (!stopped && document.visibilityState === 'visible') {
        try {
          await refresh()
          if (issue?.id) setIssue(await api.issue(issue.id))
        } catch { /* Keep the last loaded state; the next cycle retries. */ }
      }
      if (!stopped) timer = window.setTimeout(() => void tick(), 30_000)
    }
    timer = window.setTimeout(() => void tick(), 60_000)
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [issue?.id, refresh])
  useEffect(() => { if (!launchContext.initData) return; Promise.all([api.validateMaxContext(launchContext.initData), api.identity(launchContext.initData)]).then(([context, identity]) => { setMaxUserName(context.user?.first_name || null); setMaxIdentity(identity); setRole(identity.role); if (identity.selected_house_id) setHouseId(identity.selected_house_id) }).catch(() => setError('Не удалось подтвердить запуск в MAX. Откройте приложение из сообщения бота ещё раз.')) }, [launchContext.initData])
  useEffect(() => { if (!launchContext.issueId) return; api.issue(launchContext.issueId).then(setIssue).catch(() => undefined) }, [launchContext.issueId])
  useEffect(() => { if (!launchContext.initData && !localDemo && !remoteDemo) return; try { if (!window.localStorage.getItem('dompuls-tour-v1')) setTourOpen(true) } catch { /* ignore */ } }, [launchContext.initData, localDemo, remoteDemo])

  async function perform(task: () => Promise<void>) { setBusy(true); setError(null); try { await task() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось выполнить действие') } finally { setBusy(false) } }
  function submitSignal(forceAiFailure = false) { void perform(async () => { const result = await api.signal(houseId, message, undefined, forceAiFailure, photos, String(viewerId)); setFallback(result.fallback); setPendingSignalId(result.signal?.id || null); setFallbackCategory(result.classification?.category || result.issue?.category || result.fallback?.candidate?.category || 'other'); if (result.issue) setIssue(await api.issue(result.issue.id)); if (!result.fallback) { setMessage(''); setPhotos([]); setShowReport(false) } await refresh() }) }
  function resolveZone(zoneId: string) { if (!pendingSignalId) return; void perform(async () => { const result = await api.resolveSignal(pendingSignalId, fallbackCategory, zoneId); setFallback(undefined); setPendingSignalId(null); if (result.issue) setIssue(await api.issue(result.issue.id)); setMessage(''); setPhotos([]); setShowReport(false); await refresh() }) }
  function resolveCandidate(decision: 'LINK' | 'CREATE_NEW') { if (!pendingSignalId || !fallback?.candidate) return; void perform(async () => { const next = await api.resolveDuplicate(pendingSignalId, fallback.candidate!.id, decision); setIssue(await api.issue(next.id)); setFallback(undefined); setPendingSignalId(null); setMessage(''); setPhotos([]); setShowReport(false); await refresh() }) }
  function runIssueAction(action: string, evidence?: { uri: string; comment: string }) {
    if (!issue) return
    void perform(async () => {
      let nextIssue = issue
      if (action === 'confirm') nextIssue = role === 'resident' ? (await api.residentConfirm(issue.id, String(viewerId))).issue : await api.confirm(issue.id)
      if (action === 'prepare') nextIssue = await api.prepare(issue.id)
      if (action === 'route-management') nextIssue = await api.route(issue.id, 'management_org')
      if (action === 'route-representative') nextIssue = await api.route(issue.id, 'representative')
      if (action === 'submit') nextIssue = await api.submit(issue.id)
      if (action === 'accept') nextIssue = await api.accept(issue.id)
      if (action === 'create-order') { await api.createWorkOrder(issue.id); nextIssue = await api.issue(issue.id) }
      const order = issue.work_orders?.at(-1)
      if ((action === 'start' || action === 'restart') && order) { await api.updateWorkOrder(order.id, 'IN_PROGRESS'); nextIssue = await api.issue(issue.id) }
      if (action === 'complete' && order) { if (evidence) await api.evidence(order.id, evidence.uri, evidence.comment); await api.updateWorkOrder(order.id, 'DONE'); nextIssue = await api.issue(issue.id) }
      if (action === 'verify-yes') nextIssue = await api.verify(issue.id, 'confirmed', String(viewerId))
      if (action === 'verify-no') nextIssue = await api.verify(issue.id, 'rejected', String(viewerId))
      setIssue(nextIssue); await refresh()
    })
  }
  function openIssue(id: string) { void perform(async () => setIssue(await api.issue(id))) }
  function openAsset(id: string) { void perform(async () => { const result = await api.timeline(id); setTimeline({ name: result.asset.name, events: result.events }) }) }
  const mapHouses = useMemo(() => {
    const connected = houses.filter((house) => house.lat != null && house.lng != null && /кольцово/i.test(house.address))
    const catalog = koltsovoHouses.filter((house) => !connected.some((known) => known.address.includes(house.address.split(', р.п.')[0])))
    return [...connected, ...catalog]
  }, [houses])
  function selectHouse(house: House) {
    void perform(async () => {
      let selected = houses.find((item) => item.id === house.id)
      if (!selected) {
        if (!canSelectHouse) throw new Error('Чтобы подключить этот дом, откройте приложение из MAX.')
        selected = await api.addHouse(house)
        setHouses(await api.houses())
      }
      if (launchContext.initData) {
        await api.selectHouse(launchContext.initData, selected.id)
        setMaxIdentity((current) => current ? { ...current, selected_house_id: selected!.id } : current)
      }
      setHouseId(selected.id)
      setIssue(null)
      setTimeline(null)
      setMapPreview(null)
    })
  }
  function shareCurrentIssue() { if (issue) void perform(async () => { await shareIssue(issue.title, issue.id); notifyMax('success') }) }
  function resetDemo() { resetLocalStore(); window.location.reload() }
  function closeTour() { setTourOpen(false); try { window.localStorage.setItem('dompuls-tour-v1', '1') } catch { /* ignore */ } }
  async function geocodeAddress() {
    const address = houseDraft.address.trim()
    if (!address) { setMapNotice('Сначала введите адрес дома.'); return }
    const words = (value: string): string[] => value.toLocaleLowerCase('ru-RU')
      .replace(/\b(?:р\.?п\.?|г\.?)\b/g, ' ')
      .replace(/новосибирская область|новосибирская обл\.?|кольцово/g, ' ')
      .match(/[а-яёa-z]+|\d+[а-яёa-z]?/g) || []
    const queryWords = words(address)
    const known = queryWords.length >= 2 ? mapHouses.find((house) => {
      const houseWords = words(house.address)
      return queryWords.every((word) => houseWords.includes(word)) && house.lat != null && house.lng != null
    }) : null
    if (known) {
      setHouseDraft((draft) => ({ ...draft, lat: known.lat ?? draft.lat, lng: known.lng ?? draft.lng, address: known.address }))
      setMapPreview(known)
      setMapNotice('Дом найден на карте. Проверьте его карточку ниже.')
      return
    }
    if (!mapsConfigured) { setMapNotice('Отметьте дом на карте: точку можно поставить вручную.'); return }
    setMapNotice(null)
    try {
      const query = /кольцово/i.test(address) ? address : `${address}, Кольцово, Новосибирская область`
      const result = await geocodeYandex(query)
      if (result) { setHouseDraft((draft) => ({ ...draft, lat: result.lat, lng: result.lng, address: draft.address.trim() || result.address })); setMapNotice(null) }
      else setMapNotice('Адрес не найден. Проверьте написание или отметьте дом на карте.')
    } catch { setMapNotice('Поиск адреса сейчас недоступен. Отметьте дом на карте вручную.') }
  }
  function pickOnMap(lat: number, lng: number) {
    setHouseDraft((draft) => ({ ...draft, lat, lng }))
    setMapNotice(null)
    if (!mapsConfigured) { setMapNotice('Точка отмечена. Введите адрес дома вручную.'); return }
    setResolvingAddress(true)
    setError(null)
    void reverseGeocode(lat, lng).then((address) => {
      if (address) { setHouseDraft((draft) => (draft.address.trim() ? draft : { ...draft, address })); setMapNotice(null) }
      else setMapNotice('Точка отмечена. Введите адрес дома вручную.')
    }).catch(() => setMapNotice('Точка отмечена. Введите адрес дома вручную.'))
      .finally(() => setResolvingAddress(false))
  }
  function saveHouse() {
    const address = houseDraft.address.trim()
    if (!address) { setError('Укажите адрес дома — точку на карте можно оставить как ориентир'); return }
    void perform(async () => {
      const house: House = {
        id: `koltsovo-${Date.now()}`,
        address,
        region: 'Новосибирская обл., р.п. Кольцово',
        management_org: houseDraft.management_org.trim() || 'не указана',
        configuration_id: 'koltsovo',
        lat: houseDraft.lat,
        lng: houseDraft.lng,
        condition: houseDraft.condition.trim() || 'нет данных',
        metadata: { entrances: 1, provenance: 'USER', verified: false },
      }
      const saved = await api.addHouse(house)
      if (launchContext.initData) {
        await api.selectHouse(launchContext.initData, saved.id)
        setMaxIdentity((current) => current ? { ...current, selected_house_id: saved.id } : current)
      }
      setHouses(await api.houses())
      setHouseId(saved.id)
      setHouseDraft({ address: '', management_org: '', condition: '', lat: null, lng: null })
      setActiveTab('house')
    })
  }

  const tasks = useMemo<TaskIssue[]>(() => state?.my_tasks || [], [state?.my_tasks])
  const visibleMapHouses = useMemo(() => mapHouses.filter((house) => house.address.toLowerCase().includes(houseSearch.trim().toLowerCase())), [mapHouses, houseSearch])
  function openHousePicker() {
    setActiveTab('house')
    window.setTimeout(() => document.getElementById('house-picker')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }
  const goTab = useCallback((tab: string) => setActiveTab(tab as NavTab), [])
  const currentRole = roleLabel(role)
  return <div className="app-shell">
    {/* ─── TOPBAR ──────────────────────────────────────────────────── */}
    <header className="topbar">
      <div className="topbar-brand">
        <img className="topbar-logo" src={mascot.logo} alt="Макс — голубь-помощник" />
        <div className="topbar-info">
          <span className="topbar-title">ДомПульс</span>
          <span className="topbar-subtitle">{maxUserName ? `${maxUserName}, ваш дом` : 'Ваши задачи по дому'}</span>
        </div>
      </div>
      <div className="topbar-actions">
        <select className="topbar-select" aria-label="Выбрать дом" value={houseId} onChange={(event) => { const selected = houses.find((house) => house.id === event.target.value); if (selected) selectHouse(selected) }}>
          {houses.map((house) => <option key={house.id} value={house.id}>{house.address}</option>)}
        </select>
        <button className="icon-btn" aria-label="Уведомления" onClick={() => setShowNotifs(true)}>
          {bellIcon}
          {tasks.length ? <span className="icon-badge">{tasks.length}</span> : null}
        </button>
      </div>
    </header>

    {/* ─── BOTTOM NAV ──────────────────────────────────────────────── */}
    <nav className="bottom-nav">
      <button className={`bottom-nav-item${activeTab === 'tasks' ? ' bottom-nav-item--active' : ''}`} data-tour="tasks" onClick={() => setActiveTab('tasks')}>
        {taskIcon} Задачи
      </button>
      <button className={`bottom-nav-item${activeTab === 'house' ? ' bottom-nav-item--active' : ''}`} data-tour="house" onClick={() => setActiveTab('house')}>
        {homeIcon} Дом
      </button>
      <button className={`bottom-nav-item${activeTab === 'initiatives' ? ' bottom-nav-item--active' : ''}`} data-tour="initiatives" onClick={() => setActiveTab('initiatives')}>
        {peopleIcon} Инициативы
      </button>
      <button className={`bottom-nav-item${activeTab === 'archive' ? ' bottom-nav-item--active' : ''}`} onClick={() => setActiveTab('archive')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
        Архив
      </button>
      <button className={`bottom-nav-item${activeTab === 'more' ? ' bottom-nav-item--active' : ''}`} data-tour="more" onClick={() => setActiveTab('more')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>
        Ещё
      </button>
    </nav>

    {/* ─── HERO ──────────────────────────────────────────────────── */}
    <section className="hero">
      <div className="hero-main">
        <div className="role-pill" data-tour="role">
          <span className="role-pill-dot"></span>
          {currentRole}
        </div>
        <h1>{activeTab === 'tasks' ? 'Ваши обращения' : activeTab === 'house' ? 'Состояние дома' : activeTab === 'initiatives' ? 'Инициативы' : activeTab === 'archive' ? 'Архив' : 'Настройки'}</h1>
        <p className="hero-desc">{roleIntro(role)}</p>
        <p className="hero-meta">{state?.house.address || 'Загрузка дома…'}{maxUserName ? ` · ${maxUserName}` : ''}</p>
      </div>
      <img className="hero-mascot" src={mascot.hero} alt="Макс — голубь-помощник" />
    </section>

    {/* ─── ERROR (conditional) ──────────────────────────────────────── */}
    {error ? <div className="error-banner" role="alert">
      <b>{state ? 'Не удалось выполнить действие.' : 'Не удалось загрузить дом.'}</b> {error}
      {!state ? <button className="max-btn max-btn--secondary" disabled={overviewLoading} onClick={() => void loadOverview()}>{overviewLoading ? 'Пробуем снова…' : 'Повторить'}</button> : null}
      <button className="error-banner-close" aria-label="Закрыть" onClick={() => setError(null)}>×</button>
    </div> : null}
    {!canSelectHouse ? <div className="disclosure public-entry" role="status">
      <span>Сейчас вы смотрите обзор дома. Войдите через MAX, чтобы выбрать свой дом, сообщить о проблеме и следить за результатом.</span>
      <a className="max-btn max-btn--primary public-entry-link" href="https://max.ru/t312_hakaton_max_bot?startapp" target="_blank" rel="noopener noreferrer">Открыть ДомПульс в MAX</a>
    </div> : null}
    {maxIdentity && !maxIdentity.selected_house_id ? <div className="disclosure" role="status">Вы вошли через MAX. Теперь выберите свой дом — после этого сможете отправить обращение и видеть его статус. <button className="max-btn max-btn--primary" onClick={openHousePicker}>Выбрать дом</button></div> : null}
    {maxIdentity ? <p className="disclosure">Вход подтверждён через MAX ID {maxIdentity.user_id}. Дом выбран вами самостоятельно; статус жителя пока не проверен.</p> : null}

    {/* ─── TABS CONTENT ──────────────────────────────────────────── */}
    {activeTab === 'tasks' && <>
      <section className="section"><button className="max-btn max-btn--secondary max-btn--full" onClick={openHousePicker}>⌖ Выбрать другой дом на карте</button></section>
      {/* ─── TASKS SECTION ────────────────────────────────────────────── */}
      <section className="section">
        <div className="section-header">
          <span className="section-header-label">Следующий шаг</span>
          <span className="section-header-count">{tasks.length} задач</span>
        </div>
        {!state ? <div className="skeleton">Загружаем задачи…</div> :
        tasks.length === 0 ? <div className="empty-state">
          <div className="empty-state-icon empty-state-icon--mascot"><img src={mascot.calm} alt="Макс" /></div>
          <div className="empty-state-title">Сейчас ничего не требует действий</div>
          <div className="empty-state-desc">{role === 'resident' ? 'Если что-то случилось, сообщите об этом боту в MAX.' : 'Новые задачи появятся здесь автоматически.'}</div>
        </div> :
        <div className="task-list">
          {tasks.slice(0, 6).map((item) => <TaskCard key={item.id} issue={item} onOpen={() => openIssue(item.id)} />)}
        </div>}
      </section>

      {state?.my_issues?.length ? <section className="section">
        <div className="section-header">
          <span className="section-header-label">Мои обращения</span>
          <span className="section-header-count">{state.my_issues.length}</span>
        </div>
        <div className="cell-list">
          {state.my_issues.slice(0, 8).map((item) => <button className="cell-simple" key={item.id} onClick={() => openIssue(item.id)}>
            <div className="cell-content">
              <span className="cell-title">{item.title}</span>
              <span className="cell-subtitle">{item.asset_name || item.zone_name || 'Место уточняется'}</span>
            </div>
            <div className="cell-after"><StatusBadge value={item.state} /></div>
          </button>)}
        </div>
      </section> : null}

      {/* ─── REPORT BUTTON ────────────────────────────────────────────── */}
      {role === 'resident' ? <section className="section report-cta" data-tour="report" style={{ paddingTop: 0 }}>
        <button className="max-btn max-btn--primary max-btn--full" disabled={!canWrite} onClick={() => setShowReport((value) => !value)}>
          {plusIcon}
          {showReport ? 'Закрыть форму' : 'Сообщить о проблеме'}
        </button>
      </section> : null}

      {/* ─── REPORT FORM (hidden by default) ──────────────────────────── */}
      {showReport ? <section className="section">
        <div className="report-panel">
          <div className="report-panel-header">
            <span className="section-header-label">Новое обращение</span>
            <h2>Что случилось?</h2>
            <p>Опишите проблему своими словами. Если место не определится, мы уточним его здесь.</p>
          </div>
          <textarea className="report-textarea" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Например: в подъезде не горит лампочка" rows={4} />
          <div className="chips">
            {demoMessages.map((text) => <button className="chip" key={text} onClick={() => setMessage(text)}>{text}</button>)}
          </div>
          <PhotoInput photos={photos} onChange={setPhotos} label="Фото проблемы" />
          <div className="btn-row">
            <button className="max-btn max-btn--primary" style={{ flex: 1 }} disabled={busy || !message.trim()} onClick={() => submitSignal()}>
              {busy ? 'Сохраняем…' : 'Зарегистрировать'}
            </button>
            <button className="max-btn max-btn--ghost" onClick={() => { setShowDemo((v) => !v); setFallback(undefined) }}>
              {showDemo ? 'Скрыть' : 'Это демо'}
            </button>
          </div>
          {showDemo ? <div className="fallback-banner">
            <strong>Демо-инструменты</strong>
            <div className="fallback-chips">
              <button className="chip" onClick={() => submitSignal(true)}>Симулировать ошибку ИИ</button>
            </div>
          </div> : null}
          {fallback ? <div className="fallback-banner">
            <strong>{fallback.message || 'Нужно уточнение'}</strong>
            <div className="fallback-chips">
              {fallback.type === 'MANUAL_CLASSIFICATION' ? <div className="fallback-chips">
                {([['elevator', 'Лифт'], ['lighting', 'Освещение'], ['water', 'Вода'], ['heating', 'Отопление'], ['door', 'Дверь'], ['cleaning', 'Уборка'], ['other', 'Другое']] as const).map(([id, label]) => <button className={`chip${fallbackCategory === id ? ' chip--active' : ''}`} key={id} onClick={() => setFallbackCategory(id)}>{label}</button>)}
              </div> : null}
              {(fallback.choices || (fallback.type === 'MANUAL_CLASSIFICATION' ? state?.zones || [] : [])).map((choice) => <button className="chip" key={choice.id} onClick={() => resolveZone(choice.id)}>{choice.name}</button>)}
              {fallback.type === 'DUPLICATE_CONFIRMATION' ? <>
                <button className="chip" onClick={() => resolveCandidate('LINK')}>Связать с найденной проблемой</button>
                <button className="chip" onClick={() => resolveCandidate('CREATE_NEW')}>Создать отдельную проблему</button>
              </> : null}
            </div>
          </div> : null}
        </div>
      </section> : null}

    </>}

    {activeTab === 'house' && state && <>
      <section className="section">
        <div className="section-header">
          <span className="section-header-label">О доме</span>
        </div>
        <div className="info-grid">
          <div className="info-cell"><span className="info-label">Адрес</span><span className="info-value">{state.house.address}</span></div>
          <div className="info-cell"><span className="info-label">Район</span><span className="info-value">{state.house.region}</span></div>
          <div className="info-cell"><span className="info-label">Управляющая организация</span><span className="info-value">{state.house.management_org}</span></div>
          <div className="info-cell"><span className="info-label">Объектов на контроле</span><span className="info-value">{state.assets.length}</span></div>
        </div>
      </section>

      <section className="section">
        <div className="section-header">
          <span className="section-header-label">Сводка</span>
        </div>
        <div className="metrics-grid">
          <div className="metric-cell">
            <span className="metric-value">{state.metrics.active_issues}</span>
            <span className="metric-label">Активных проблем</span>
          </div>
          <div className="metric-cell">
            <span className="metric-value">{state.metrics.work_in_progress}</span>
            <span className="metric-label">В работе</span>
          </div>
          <div className="metric-cell">
            <span className="metric-value">{state.metrics.awaiting_confirmation ?? 0}</span>
            <span className="metric-label">Ждут подтверждения</span>
          </div>
          <div className={`metric-cell${state.metrics.awaiting_verification ? ' metric-cell--alert' : ''}`}>
            <span className="metric-value">{state.metrics.awaiting_verification ?? 0}</span>
            <span className="metric-label">Ждут проверки</span>
          </div>
          <div className="metric-cell">
            <span className="metric-value">{state.metrics.recurring_issues}</span>
            <span className="metric-label">Повторяются</span>
          </div>
          <div className="metric-cell">
            <span className="metric-value">{state.metrics.initiatives}</span>
            <span className="metric-label">Инициатив</span>
          </div>
        </div>
      </section>
      <HouseOverview state={state} onIssue={openIssue} onAsset={openAsset} />
      <section className="section">
        <div className="section-header">
          <span className="section-header-label">Лента дома</span>
          <span className="section-header-count">{state.recent_signals.length}</span>
        </div>
        <SignalList signals={state.recent_signals} onOpen={openIssue} wide />
      </section>

      <section className="section" id="house-picker">
        <div className="section-header">
          <span className="section-header-label">Выбрать дом на карте</span>
        </div>
        <HouseMap
          center={KOLTSOVO_CENTER}
          houses={mapHouses}
          selectedId={houseId}
          draft={houseDraft.lat != null && houseDraft.lng != null ? { lat: houseDraft.lat, lng: houseDraft.lng } : null}
          onSelect={setMapPreview}
          onPick={pickOnMap}
        />
        {mapPreview ? <div className="report-panel" style={{ marginTop: 'var(--spacing-m)' }}>
          <strong>{mapPreview.address}</strong>
          <p>{mapPreview.condition || 'Характеристики дома не указаны'}</p>
          <p>Управляющая организация: {mapPreview.management_org || 'не подтверждена'}</p>
          <p className="disclosure">Данные справочника требуют проверки. {houses.some((item) => item.id === mapPreview.id) ? 'Дом подключён к ДомПульсу.' : 'Карточка дома будет создана при выборе.'}</p>
          {canSelectHouse || houses.some((item) => item.id === mapPreview.id) ? (
            <button className="max-btn max-btn--primary" disabled={busy} onClick={() => selectHouse(mapPreview)}>{houses.some((item) => item.id === mapPreview.id) ? 'Открыть этот дом' : 'Выбрать и подключить дом'}</button>
          ) : (
            <a className="max-btn max-btn--primary public-entry-link" href="https://max.ru/t312_hakaton_max_bot?startapp" target="_blank" rel="noopener noreferrer">Открыть в MAX и подключить дом</a>
          )}
        </div> : null}
        <div className="house-form">
          <input className="house-input" value={houseDraft.address} onChange={(event) => setHouseDraft((draft) => ({ ...draft, address: event.target.value }))} placeholder="Адрес: Никольский проспект, 1" />
          {houseDraft.lat != null && houseDraft.lng != null ? <span className="house-point">Точка: {houseDraft.lat.toFixed(5)}, {houseDraft.lng.toFixed(5)}{resolvingAddress ? ' · определяем адрес…' : ''}</span> : null}
          {mapNotice ? <span className="house-point" role="status">{mapNotice}</span> : null}
          <div className="house-form-row">
            <input className="house-input" value={houseDraft.management_org} onChange={(event) => setHouseDraft((draft) => ({ ...draft, management_org: event.target.value }))} placeholder="Управляющая организация" />
            <input className="house-input" value={houseDraft.condition} onChange={(event) => setHouseDraft((draft) => ({ ...draft, condition: event.target.value }))} placeholder="Состояние дома" />
          </div>
          <div className="house-form-row">
            <button className="max-btn max-btn--secondary" onClick={() => void geocodeAddress()}>Найти адрес</button>
            {canSelectHouse ? (
              <button className="max-btn max-btn--primary" disabled={busy || resolvingAddress || !houseDraft.address.trim() || houseDraft.lat == null || houseDraft.lng == null} onClick={saveHouse}>Добавить дом</button>
            ) : (
              <a className="max-btn max-btn--primary public-entry-link" href="https://max.ru/t312_hakaton_max_bot?startapp" target="_blank" rel="noopener noreferrer">Добавить дом через MAX</a>
            )}
          </div>
        </div>
        <input className="house-input" aria-label="Поиск дома по адресу" value={houseSearch} onChange={(event) => setHouseSearch(event.target.value)} placeholder="Найти дом по адресу" style={{ marginTop: 'var(--spacing-xl)', width: '100%' }} />
        <div className="cell-list" style={{ marginTop: 'var(--spacing-xl)' }}>
          {visibleMapHouses.slice(0, 20).map((house) => <button className="cell-simple" key={house.id} onClick={() => setMapPreview(house)}>
            <div className="cell-before cell-before--muted">{homeIcon}</div>
            <div className="cell-content">
              <span className="cell-title">{house.address}</span>
              <span className="cell-subtitle">{house.management_org}{house.condition ? ` · ${house.condition}` : ''}</span>
            </div>
            {house.id === houseId ? <div className="cell-after"><span className="counter counter--themed">выбран</span></div> : null}
          </button>)}
          {visibleMapHouses.length > 20 ? <p className="disclosure">Показаны первые 20 домов. Уточните адрес в поиске.</p> : null}
        </div>
      </section>
    </>}

    {activeTab === 'initiatives' && <>
      {state?.initiatives.length ? <section className="section">
        <div className="section-header">
          <span className="section-header-label">Общие решения жителей</span>
          <span className="section-header-count">{state.initiatives.length}</span>
        </div>
        <div className="initiative-grid">
          {state.initiatives.map((initiative) => <InitiativeCard key={initiative.id} initiative={initiative} busy={busy} canVote={Boolean(canWrite && ['resident', 'representative'].includes(role))} canHandoff={Boolean(canWrite && role === 'representative')} onVote={(option) => void perform(async () => { await api.vote(initiative.id, String(viewerId), option); await refresh() })} onHandoff={() => void perform(async () => { await api.handoff(initiative.id); await refresh() })} />)}
        </div>
      </section> : <section className="section">
        <div className="empty-state">
          <div className="empty-state-icon empty-state-icon--mascot"><img src={mascot.announce} alt="Макс" /></div>
          <div className="empty-state-title">Нет активных инициатив</div>
          <div className="empty-state-desc">Инициативы жителей появятся здесь.</div>
        </div>
      </section>}
    </>}

    {activeTab === 'archive' && <>
      <section className="section">
        <div className="section-header">
          <span className="section-header-label">Архив обращений</span>
          <span className="section-header-count">{state?.history_issues?.length ?? 0}</span>
        </div>
        {state?.history_issues?.length ? <div className="archive-grid">
          {state.history_issues.map((item) => <button className="archive-card" key={item.id} onClick={() => openIssue(item.id)}>
            <div className="archive-card-top">
              <StatusBadge value={item.state} />
              <span className="archive-card-date">{new Date(item.first_seen_at).toLocaleDateString('ru-RU')}</span>
            </div>
            <span className="archive-card-title">{item.title}</span>
            {item.state === 'DECLINED' && item.decline_reason ? <span className="archive-card-reason">Причина отказа: {item.decline_reason}</span> : null}
          </button>)}
        </div> : <div className="empty-state">
          <div className="empty-state-icon empty-state-icon--mascot"><img src={mascot.calm} alt="Макс" /></div>
          <div className="empty-state-title">Архив пуст</div>
          <div className="empty-state-desc">Здесь появятся закрытые и отклонённые обращения.</div>
        </div>}
      </section>

      {state?.initiatives?.some((initiative) => initiative.state !== 'INFORMAL_POLL') ? <section className="section">
        <div className="section-header">
          <span className="section-header-label">Архив инициатив</span>
          <span className="section-header-count">{state.initiatives.filter((initiative) => initiative.state !== 'INFORMAL_POLL').length}</span>
        </div>
        <div className="archive-grid">
          {state.initiatives.filter((initiative) => initiative.state !== 'INFORMAL_POLL').map((initiative) => <div className="archive-card" key={initiative.id}>
            <div className="archive-card-top"><StatusBadge value={initiative.state} /></div>
            <span className="archive-card-title">{initiative.title}</span>
            <span className="archive-card-reason">{initiative.summary}</span>
          </div>)}
        </div>
      </section> : null}
    </>}

    {activeTab === 'more' && <div className="desktop-grid">
      <section className="section settings-section">
      <div className="section-header">
        <span className="section-header-label">Роль и настройки</span>
      </div>
      <div className="cell-list">
        <div className="cell-simple">
          <div className="cell-before cell-before--default">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          </div>
          <div className="cell-content">
            <span className="cell-title">Ваша роль</span>
            <span className="cell-subtitle">{currentRole}</span>
          </div>
          <div className="cell-after">
            {new URLSearchParams(window.location.search).get('local') === 'true' || remoteDemo ? <select className="settings-select" aria-label="Выбрать роль" value={role} onChange={(event) => setRole(event.target.value as ViewerRole)}>
              {roles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select> : <span>{currentRole}</span>}
          </div>
        </div>
        <div className="cell-simple">
          <div className="cell-before cell-before--muted">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          </div>
          <div className="cell-content">
            <span className="cell-title">Дом</span>
            <span className="cell-subtitle">{state?.house.address || 'Загрузка…'}</span>
          </div>
          <div className="cell-after"><span className="cell-chevron">{chevron}</span></div>
        </div>
        {new URLSearchParams(window.location.search).get('local') === 'true' ? <button className="cell-simple" onClick={resetDemo}>
          <div className="cell-before cell-before--muted">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
          </div>
          <div className="cell-content">
            <span className="cell-title">Сбросить демо-данные</span>
            <span className="cell-subtitle">Вернуть исходный набор обращений</span>
          </div>
          <div className="cell-after"><span className="cell-chevron">{chevron}</span></div>
        </button> : null}
        <button className="cell-simple" onClick={() => setTourOpen(true)}>
          <div className="cell-before cell-before--default">
            <img className="cell-mascot" src={mascot.tip} alt="Макс" />
          </div>
          <div className="cell-content">
            <span className="cell-title">Как это работает</span>
            <span className="cell-subtitle">Показать обучение ещё раз</span>
          </div>
          <div className="cell-after"><span className="cell-chevron">{chevron}</span></div>
        </button>
      </div>
      <p className="disclosure" style={{ marginTop: 'var(--spacing-2xl)' }}>
        В рабочем MAX роль определяется правами пользователя. Выбор дома — самоопределение, не подтверждение права собственности.
      </p>
      </section>

      <section className="section">
        <div className="section-header">
          <span className="section-header-label">Как устроено</span>
        </div>
        <div className="cell-list">
          <div className="cell-simple">
            <div className="cell-before cell-before--default"><strong className="cell-step">1</strong></div>
            <div className="cell-content">
              <span className="cell-title">Житель сообщает о проблеме</span>
              <span className="cell-subtitle">Макс уточняет объект и объединяет похожие сообщения</span>
            </div>
          </div>
          <div className="cell-simple">
            <div className="cell-before cell-before--default"><strong className="cell-step">2</strong></div>
            <div className="cell-content">
              <span className="cell-title">Домоуправляющий подтверждает</span>
              <span className="cell-subtitle">Проблема становится готовой к передаче</span>
            </div>
          </div>
          <div className="cell-simple">
            <div className="cell-before cell-before--default"><strong className="cell-step">3</strong></div>
            <div className="cell-content">
              <span className="cell-title">УК принимает и назначает исполнителя</span>
              <span className="cell-subtitle">Создаётся заявка на работу</span>
            </div>
          </div>
          <div className="cell-simple">
            <div className="cell-before cell-before--default"><strong className="cell-step">4</strong></div>
            <div className="cell-content">
              <span className="cell-title">Исполнитель выполняет, житель проверяет</span>
              <span className="cell-subtitle">Результат подтверждают или переоткрывают</span>
            </div>
          </div>
        </div>
        <div className="cell-list" style={{ marginTop: 'var(--spacing-xl)' }}>
          <div className="cell-simple">
            <div className="cell-before cell-before--muted"><img className="cell-mascot" src={mascot.tip} alt="Макс" /></div>
            <div className="cell-content">
              <span className="cell-title">Спросите Макса</span>
              <span className="cell-subtitle">Чат-помощник в правом нижнем углу</span>
            </div>
          </div>
        </div>
      </section>
    </div>}

    {/* ─── DISCLOSURE (bottom) ──────────────────────────────────────── */}
    {activeTab !== 'more' ? <p className="disclosure">Передача в УК здесь учебная, пока управляющая организация не подключила официальный канал.</p> : null}

    {/* ─── BOTTOM SPACER ──────────────────────────────────────────── */}
    <div className="bottom-spacer"></div>

    {/* ─── ISSUE PANEL (drawer) ────────────────────────────────────── */}
    {issue ? <IssuePanel issue={issue} managementOrg={state?.house.management_org} viewerId={String(viewerId)} alreadyReported={Boolean(state?.my_issues?.some((item) => item.id === issue.id || item.related_issue_ids?.includes(issue.id)))} role={role} busy={busy} readOnly={!canWrite} onAction={runIssueAction} onComment={(text, commentPhotos) => void perform(async () => { setIssue(await api.comment(issue.id, text, role, String(viewerId), commentPhotos)); await refresh() })} onClose={() => setIssue(null)} onShare={shareCurrentIssue} onOpenRelated={openIssue} /> : null}

    {/* ─── TIMELINE DRAWER ────────────────────────────────────────── */}
    {timeline ? <div className="drawer-backdrop" role="presentation" onMouseDown={() => setTimeline(null)}>
      <aside className="drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <button className="drawer-close" onClick={() => setTimeline(null)} aria-label="Закрыть">×</button>
        <p className="eyebrow">История объекта</p>
        <h2>{timeline.name}</h2>
        <p className="lead">Что происходило с объектом и чем закончились работы</p>
        <div className="timeline">
          {timeline.events.length === 0 ? <div className="empty-state">
            <div className="empty-state-title">История пока пуста</div>
            <p>По этому объекту ещё не было обращений и работ. Новые события появятся здесь.</p>
          </div> : null}
          {timeline.events.map((event, index) => {
            const isIssue = event.type === 'issue'
            const dateValue = [event.completed_at, event.started_at, event.assigned_at, event.first_seen_at].find((value): value is string => typeof value === 'string' && Boolean(value))
            const materials = Array.isArray(event.evidence) ? event.evidence as Array<Record<string, unknown>> : []
            return <div className="timeline-item" key={`${String(event.id)}-${index}`}>
            <div className="timeline-dot" />
            <div className="timeline-content">
              <strong>{String(event.title || (isIssue ? 'Обращение жителей' : 'Работа по объекту'))}</strong>
              {dateValue ? <span className="timeline-date">{new Date(dateValue).toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' })}</span> : null}
              <small><StatusBadge value={String(event.state || event.status || 'UNKNOWN')} kind={isIssue ? 'issue' : 'work_order'} /></small>
              {isIssue ? <button className="timeline-link" onClick={() => { setTimeline(null); openIssue(String(event.id)) }}>Открыть обращение</button> : null}
              {!isIssue && typeof event.evidence_count === 'number' && event.evidence_count > 0 ? <span className="timeline-date">Подтверждений работы: {event.evidence_count}</span> : null}
              {materials.map((material, materialIndex) => <div className="timeline-material" key={`${String(material.id)}-${materialIndex}`}>
                <span>{String(material.comment || 'Подтверждение выполненной работы')}{material.provenance === 'SYNTHETIC' ? ' · демонстрационные данные' : ''}</span>
                {typeof material.uri === 'string' && material.uri ? <img src={mediaSrc(material.uri)} alt={material.provenance === 'SYNTHETIC' ? 'Демонстрационная иллюстрация выполненной работы' : 'Фото выполненной работы'} /> : null}
              </div>)}
            </div>
          </div>})}
        </div>
      </aside>
    </div> : null}

    {/* ─── NOTIFICATIONS DRAWER ────────────────────────────────────── */}
    {showNotifs ? <div className="drawer-backdrop" role="presentation" onMouseDown={() => setShowNotifs(false)}>
      <aside className="drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <button className="drawer-close" onClick={() => setShowNotifs(false)} aria-label="Закрыть">×</button>
        <p className="eyebrow">Уведомления</p>
        <h2>Что происходит в доме</h2>
        <SignalList signals={(state?.recent_signals || []).slice(0, 12)} onOpen={(id) => { setShowNotifs(false); openIssue(id) }} />
      </aside>
    </div> : null}

    {/* ─── CHAT (Макс) ─────────────────────────────────────────────── */}
    <ChatBubble houseId={houseId} />

    {/* ─── INTERACTIVE TOUR ────────────────────────────────────────── */}
    {tourOpen ? <Tour steps={tourSteps} onClose={closeTour} onNavigate={goTab} /> : null}
  </div>
}

type TaskIssue = Issue & { next_action?: { id: string; label: string } }
