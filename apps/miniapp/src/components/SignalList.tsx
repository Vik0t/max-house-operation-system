import type { Signal } from '../types'
import { StatusBadge } from './StatusBadge'

type Props = {
  signals: Signal[]
  onOpen: (issueId: string) => void
  wide?: boolean
}

export function SignalList({ signals, onOpen, wide }: Props) {
  if (!signals.length) {
    return <div className="empty-state" style={{ minHeight: 120 }}>
      <div className="empty-state-title">Пока нет событий</div>
      <div className="empty-state-desc">Сообщения жителей появятся здесь.</div>
    </div>
  }
  return <div className={`signal-grid${wide ? ' signal-grid--wide' : ''}`}>
    {signals.map((signal) => <button className="notif-item" key={signal.id} onClick={() => { if (signal.issue?.id) onOpen(signal.issue.id) }}>
      <span className="notif-dot" />
      <span className="notif-body">
        <span className="notif-text">{signal.text}</span>
        <span className="notif-meta">
          {signal.source_type === 'max_message' ? 'MAX' : 'Приложение'} · {new Date(signal.created_at).toLocaleDateString('ru-RU')}
          {signal.issue ? <StatusBadge value={signal.issue.state} /> : null}
        </span>
      </span>
    </button>)}
  </div>
}
