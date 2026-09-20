import type { HouseState } from '../types'
import { issueAssetLabel } from '../labels'
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
    ['Ждут подтверждений', state.metrics.awaiting_confirmation || 0],
    ['Ждут проверки', state.metrics.awaiting_verification || 0],
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

      <section className="panel signal-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">MAX · сообщения в реальном времени</p>
            <h2>Сигналы жителей</h2>
          </div>
          <span className="live-indicator"><i /> {state.integration.max === 'REAL' ? 'бот подключён' : 'демо-режим'}</span>
        </div>
        <div className="signal-feed">
          {state.recent_signals.length === 0 ? <p className="empty">Напишите боту о проблеме — сообщение появится здесь.</p> : null}
          {state.recent_signals.slice(0, 8).map((signal) => {
            const content = (
              <>
                <span className="signal-meta">
                  <b>{signal.source_type === 'max_message' ? 'MAX' : 'WEB'}</b>
                  <span>житель · {new Date(signal.created_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span>
                </span>
                <strong>{signal.text}</strong>
                <small className={signal.issue ? 'signal-linked' : 'signal-waiting'}>
                  {signal.issue ? `Связано: ${signal.issue.title}` : 'Ждёт контекста следующего сообщения'}
                </small>
              </>
            )
            return signal.issue ? (
              <button className="signal-message" key={signal.id} onClick={() => onIssue(signal.issue!.id)}>{content}</button>
            ) : (
              <article className="signal-message" key={signal.id}>{content}</article>
            )
          })}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Состояние объектов</p>
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
            <p className="eyebrow">Оперативная память дома</p>
            <h2>Текущие проблемы</h2>
          </div>
        </div>
        <div className="issue-list">
          {state.issues.length === 0 ? <p className="empty">Открытых проблем пока нет.</p> : null}
          {state.issues.slice(0, 8).map((issue) => (
            <button className="issue-row" key={issue.id} onClick={() => onIssue(issue.id)}>
              <span>
                <strong>{issueAssetLabel(issue)}</strong>
                <small>{issue.confirmations_count} подтверждений · {issue.recurrence_count}-й случай{issue.related_issue_count && issue.related_issue_count > 1 ? ` · ${issue.related_issue_count} сообщения объединены` : ''}</small>
              </span>
              <StatusBadge value={issue.state} />
            </button>
          ))}
        </div>
        {state.history_issues?.length ? (
          <div className="issue-list issue-list--history">
            <div className="section-heading"><h3>Закрытые случаи</h3><span className="muted">История объектов</span></div>
            {state.history_issues.slice(0, 6).map((issue) => (
              <button className="issue-row" key={issue.id} onClick={() => onIssue(issue.id)}>
                <span><strong>{issueAssetLabel(issue)}</strong><small>{issue.confirmations_count} подтверждений · {issue.recurrence_count}-й случай</small></span>
                <StatusBadge value={issue.state} />
              </button>
            ))}
          </div>
        ) : null}
      </section>
    </>
  )
}
