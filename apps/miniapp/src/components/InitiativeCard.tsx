import type { Initiative } from '../types'
import { StatusBadge } from './StatusBadge'

type Props = {
  initiative: Initiative
  busy: boolean
  onVote: (option: string) => void
  onHandoff: () => void
}

export function InitiativeCard({ initiative, busy, onVote, onHandoff }: Props) {
  const total = Object.values(initiative.votes).reduce((sum, value) => sum + value, 0)
  return (
    <section className="panel initiative">
      <div className="section-heading">
        <div><p className="eyebrow">Community to action</p><h2>{initiative.title}</h2></div>
        <StatusBadge value={initiative.state} />
      </div>
      <p>{initiative.summary}</p>
      <p className="muted">Предварительный неофициальный опрос · {total} голосов</p>
      <div className="poll-options">
        {initiative.options.map((option) => {
          const votes = initiative.votes[option] || 0
          const width = total ? Math.round((votes / total) * 100) : 0
          return (
            <button key={option} disabled={busy || initiative.state !== 'INFORMAL_POLL'} onClick={() => onVote(option)}>
              <span><strong>{option}</strong><b>{votes}</b></span>
              <i style={{ width: `${width}%` }} />
            </button>
          )
        })}
      </div>
      {initiative.state === 'INFORMAL_POLL' ? <button className="secondary" disabled={busy} onClick={onHandoff}>Зафиксировать результат</button> : null}
      {initiative.state === 'FORMAL_HANDOFF_REQUIRED' ? <div className="honesty"><b>FORMAL HANDOFF REQUIRED</b> Опрос не является юридически значимым ОСС.</div> : null}
    </section>
  )
}

