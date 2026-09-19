import type { Issue } from '../types'
import { StatusBadge } from './StatusBadge'

type Props = {
  issue: Issue
  busy: boolean
  onAction: (action: string) => void
  onClose: () => void
  onShare: () => void
}

function nextAction(issue: Issue): { action: string; label: string } | null {
  const order = issue.work_orders?.at(-1)
  if (issue.state === 'NEEDS_CONFIRMATION') return { action: 'confirm', label: 'Подтвердить проблему' }
  if (issue.state === 'ACTION_READY') return { action: 'submit', label: 'Передать ответственному' }
  if (issue.state === 'SUBMITTED') return { action: 'accept', label: 'Принять от имени УК' }
  if (issue.state === 'ACCEPTED' && !order) return { action: 'create-order', label: 'Назначить мастера' }
  if (order?.status === 'ASSIGNED') return { action: 'start', label: 'Начать работу' }
  if (order?.status === 'REWORK_REQUIRED') return { action: 'restart', label: 'Начать доработку' }
  if (order?.status === 'IN_PROGRESS' && order.evidence.length === 0) return { action: 'evidence', label: 'Добавить evidence' }
  if (order?.status === 'IN_PROGRESS' && order.evidence.length > 0) return { action: 'done', label: 'Завершить работу' }
  return null
}

export function IssuePanel({ issue, busy, onAction, onClose, onShare }: Props) {
  const next = nextAction(issue)
  const order = issue.work_orders?.at(-1)
  const evidenceCount = issue.signals?.reduce((sum, signal) => sum + signal.attachments.length, 0) || 0
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="issue-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button" onClick={onClose} aria-label="Закрыть карточку">×</button>
        <p className="eyebrow">Issue · Object memory</p>
        <h2 id="issue-title">{issue.title}</h2>
        <div className="badges"><StatusBadge value={issue.state} /><span className="provenance">AI inference</span></div>
        <p className="lead">{issue.description}</p>
        <div className="facts">
          <div><strong>{issue.confirmations_count}</strong><span>жителей подтвердили</span></div>
          <div><strong>{issue.recurrence_count}</strong><span>событий за период</span></div>
          <div><strong>{evidenceCount}</strong><span>evidence из сообщений</span></div>
        </div>
        {issue.recurrence_count >= 3 ? <div className="insight">↻ Повторяющаяся проблема: {issue.recurrence_count} события за 90 дней</div> : null}
        {issue.actions?.at(-1) ? (
          <section className="detail-block">
            <p className="eyebrow">Рекомендованное действие</p>
            <strong>{issue.actions.at(-1)?.suggested_destination}</strong>
            <p>{issue.actions.at(-1)?.rationale}</p>
          </section>
        ) : null}
        {issue.submissions?.at(-1) ? (
          <div className="honesty"><b>SIMULATED</b> Передача в УК показана через demo-adapter, не как официальная отправка.</div>
        ) : null}
        {order ? (
          <section className="detail-block">
            <p className="eyebrow">Work order</p>
            <div className="row-between"><strong>{order.assignee_id}</strong><StatusBadge value={order.status} /></div>
            <p>{order.title}</p>
            {order.evidence.map((item) => <div className="evidence" key={item.id}>✓ {item.comment || item.type}</div>)}
          </section>
        ) : null}
        {next ? <button className="primary full" disabled={busy} onClick={() => onAction(next.action)}>{busy ? 'Выполняется…' : next.label}</button> : null}
        <button className="secondary full" disabled={busy} onClick={onShare}>Поделиться в MAX</button>
        {issue.state === 'DONE_PENDING_VERIFICATION' ? (
          <div className="verification">
            <h3>Проблема устранена?</h3>
            <div className="button-row">
              <button className="primary" disabled={busy} onClick={() => onAction('verify-yes')}>Да, работает</button>
              <button className="secondary" disabled={busy} onClick={() => onAction('verify-no')}>Нет, переоткрыть</button>
            </div>
          </div>
        ) : null}
      </aside>
    </div>
  )
}
