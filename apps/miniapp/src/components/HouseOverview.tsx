import type { HouseState } from '../types'
import { StatusBadge } from './StatusBadge'

type Props = {
  state: HouseState
  onIssue: (id: string) => void
  onAsset: (id: string) => void
}

export function HouseOverview({ state, onIssue, onAsset }: Props) {
  const metrics = [
    ['Активные проблемы', state.metrics.active_issues],
    ['Работы', state.metrics.work_in_progress],
    ['Повторяются', state.metrics.recurring_issues],
    ['Инициативы', state.metrics.initiatives],
  ]
  return (
    <>
      <section className="metrics" aria-label="Сводка состояния дома">
        {metrics.map(([label, value]) => (
          <article className="metric" key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </article>
        ))}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">House state graph</p>
            <h2>Объекты дома</h2>
          </div>
          <span className="muted">{state.assets.length} объектов</span>
        </div>
        <div className="asset-grid">
          {state.assets.map((asset) => (
            <button className="asset-card" key={asset.id} onClick={() => onAsset(asset.id)}>
              <span className="asset-icon">{asset.type === 'elevator' ? '↕' : '✦'}</span>
              <span>
                <strong>{asset.name}</strong>
                <small>{asset.zone_id.replaceAll('-', ' ')}</small>
              </span>
              <StatusBadge value={asset.operational_state} />
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Operational memory</p>
            <h2>Последние проблемы</h2>
          </div>
        </div>
        <div className="issue-list">
          {state.issues.length === 0 ? <p className="empty">Активных и исторических проблем пока нет.</p> : null}
          {state.issues.slice(0, 8).map((issue) => (
            <button className="issue-row" key={issue.id} onClick={() => onIssue(issue.id)}>
              <span>
                <strong>{issue.title}</strong>
                <small>{issue.confirmations_count} подтверждений · {issue.recurrence_count}-й инцидент</small>
              </span>
              <StatusBadge value={issue.state} />
            </button>
          ))}
        </div>
      </section>
    </>
  )
}

