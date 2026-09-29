import type { Initiative } from '../types'
import { StatusBadge } from './StatusBadge'

type Props = {
  initiative: Initiative
  busy: boolean
  canVote: boolean
  canHandoff: boolean
  onVote: (option: string) => void
  onHandoff: () => void
}

export function InitiativeCard({ initiative, busy, canVote, canHandoff, onVote, onHandoff }: Props) {
  const total = Object.values(initiative.votes).reduce((sum, value) => sum + value, 0)
  return (
    <div className="initiative-card">
      <div className="initiative-header">
        <span className="initiative-title">{initiative.title}</span>
        <StatusBadge value={initiative.state} />
      </div>
      <p className="initiative-desc">{initiative.summary}</p>
      <p style={{ fontSize: 'var(--fs-tag)', color: 'var(--text-tertiary)', marginBottom: 'var(--spacing-xl)' }}>
        Предварительный неофициальный опрос · {total} голосов
      </p>
      <div className="flex-col gap-m">
        {initiative.options.map((option) => {
          const votes = initiative.votes[option] || 0
          const width = total ? Math.round((votes / total) * 100) : 0
          const isAgainst = option.toLowerCase().includes('против')
          return (
            <button key={option} className={`poll-option${isAgainst ? ' poll-option--against' : ''}`} disabled={busy || !canVote || initiative.state !== 'INFORMAL_POLL'} onClick={() => onVote(option)}>
              <div className="poll-option-bar" style={{ width: `${width}%` }} />
              <span className="poll-option-text">
                {option}
                <span className="poll-option-pct">{total ? `${Math.round((votes / total) * 100)}%` : '0%'}</span>
              </span>
            </button>
          )
        })}
      </div>
      {canHandoff && initiative.state === 'INFORMAL_POLL' ? <div className="btn-row" style={{ marginTop: 'var(--spacing-xl)' }}>
        <button className="max-btn max-btn--secondary" disabled={busy} onClick={onHandoff}>Зафиксировать результат</button>
      </div> : null}
      {initiative.state === 'FORMAL_HANDOFF_REQUIRED' ? <div className="drawer-honesty" style={{ marginTop: 'var(--spacing-xl)' }}>
        <b>НУЖНА ОФИЦИАЛЬНАЯ ПЕРЕДАЧА</b>
        Опрос не является юридически значимым ОСС.
      </div> : null}
    </div>
  )
}
