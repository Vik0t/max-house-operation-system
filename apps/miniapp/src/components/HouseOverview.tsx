import type { HouseState } from '../types'
import { issueAssetLabel } from '../labels'
import { StatusBadge } from './StatusBadge'

const chevron = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
const houseSvg = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
const parkingSvg = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>
const elevatorSvg = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>

type Props = {
  state: HouseState
  onIssue: (id: string) => void
  onAsset: (id: string) => void
}

function zoneIcon(zoneId: string) {
  const id = zoneId.toLowerCase()
  if (id.includes('elevator') || id.includes('лифт')) return elevatorSvg
  if (id.includes('parking') || id.includes('парковк')) return parkingSvg
  return houseSvg
}

function fallbackZoneName(zoneId: string): string {
  const id = zoneId.toLowerCase()
  if (id.includes('entrance-1') || id.includes('подъезд-1') || id.includes('entrance_1')) return 'Подъезд 1'
  if (id.includes('entrance-2') || id.includes('подъезд-2') || id.includes('entrance_2')) return 'Подъезд 2'
  if (id.includes('parking') || id.includes('парковк')) return 'Парковка'
  if (id.includes('elevator') || id.includes('лифт')) return 'Лифт'
  return zoneId.replaceAll('-', ' ')
}

export function HouseOverview({ state, onIssue, onAsset }: Props) {
  const zoneIssues = (state.zones || []).reduce<Record<string, { assetCount: number; issueCount: number; hasActive: boolean }>>((acc, zone) => {
    acc[zone.id] = { assetCount: 0, issueCount: 0, hasActive: false }
    return acc
  }, {})
  state.assets.reduce<Record<string, { assetCount: number; issueCount: number; hasActive: boolean }>>((acc, asset) => {
    const zone = asset.zone_id
    if (!acc[zone]) acc[zone] = { assetCount: 0, issueCount: 0, hasActive: false }
    acc[zone].assetCount++
    return acc
  }, {})

  state.issues.forEach((issue) => {
    const zone = issue.zone_id || 'unknown'
    if (zoneIssues[zone]) {
      zoneIssues[zone].issueCount++
      zoneIssues[zone].hasActive = true
    }
  })

  const zones = Object.entries(zoneIssues)
  const zoneNames = new Map((state.zones || []).map((zone) => [zone.id, zone.name]))

  return <div className="desktop-grid">
    {/* ─── HOUSE OVERVIEW ──────────────────────────────────────────── */}
    <section className="section">
      <div className="section-header">
        <span className="section-header-label">Состояние дома</span>
      </div>

      <div className="cell-list">
        {zones.length === 0 ? <div className="empty-state" style={{ minHeight: 120 }}>
          <div className="empty-state-title">Нет данных об объектах</div>
        </div> : zones.map(([zoneId, info]) => <button className="cell-simple" key={zoneId} disabled={!state.assets.some((asset) => asset.zone_id === zoneId) && !state.issues.some((issue) => issue.zone_id === zoneId)} onClick={() => {
          const asset = state.assets.find((a) => a.zone_id === zoneId)
          if (asset) onAsset(asset.id)
          else { const issue = state.issues.find((item) => item.zone_id === zoneId); if (issue) onIssue(issue.id) }
        }}>
          <div className={`cell-before ${info.hasActive ? 'cell-before--default' : 'cell-before--muted'}`}>
            {zoneIcon(zoneId)}
          </div>
          <div className="cell-content">
            <span className="cell-title">{zoneNames.get(zoneId) || fallbackZoneName(zoneId)}</span>
            <span className="cell-subtitle">{info.hasActive ? `${info.issueCount} активн${info.issueCount === 1 ? 'ая' : 'ых'} проблем${info.issueCount === 1 ? 'а' : 'ы'}` : 'Нет активных проблем'}</span>
          </div>
          <div className="cell-after">
            {info.hasActive ? <span className="counter counter--themed">{info.issueCount}</span> : <span className="counter" style={{ visibility: 'hidden' }}>0</span>}
            <span className="cell-chevron">{chevron}</span>
          </div>
        </button>)}
      </div>
    </section>

    {/* ─── ISSUES ──────────────────────────────────────────────────── */}
    <section className="section">
      <div className="section-header">
        <span className="section-header-label">Текущие проблемы</span>
        <span className="section-header-count">{state.issues.length}</span>
      </div>

      <div className="cell-list">
        {state.issues.length === 0 ? <div className="empty-state" style={{ minHeight: 120 }}>
          <div className="empty-state-title">Открытых проблем нет</div>
        </div> : state.issues.slice(0, 8).map((issue) => <button className="cell-simple" key={issue.id} onClick={() => onIssue(issue.id)}>
          <div className="cell-before cell-before--default">
            {zoneIcon(issue.zone_id || '')}
          </div>
          <div className="cell-content">
            <span className="cell-title">{issueAssetLabel(issue)}</span>
            <span className="cell-subtitle">{issue.confirmations_count} подтверждений · {issue.recurrence_count}-й случай{issue.related_issue_count && issue.related_issue_count > 1 ? ` · ${issue.related_issue_count} сообщения` : ''}</span>
          </div>
          <div className="cell-after">
            <StatusBadge value={issue.state} />
            <span className="cell-chevron">{chevron}</span>
          </div>
        </button>)}
      </div>

      {state.history_issues?.length ? <>
        <div className="section-header" style={{ marginTop: 'var(--spacing-2xl)' }}>
          <span className="section-header-label">Закрытые случаи</span>
          <span className="section-header-count">{state.history_issues.length}</span>
        </div>
        <div className="cell-list">
          {state.history_issues.slice(0, 6).map((issue) => <button className="cell-simple" key={issue.id} onClick={() => onIssue(issue.id)}>
            <div className="cell-before cell-before--muted">
              {zoneIcon(issue.zone_id || '')}
            </div>
            <div className="cell-content">
              <span className="cell-title">{issueAssetLabel(issue)}</span>
              <span className="cell-subtitle">{issue.confirmations_count} подтверждений · {issue.recurrence_count}-й случай</span>
            </div>
            <div className="cell-after">
              <StatusBadge value={issue.state} />
              <span className="cell-chevron">{chevron}</span>
            </div>
          </button>)}
        </div>
      </> : null}
    </section>
  </div>
}
