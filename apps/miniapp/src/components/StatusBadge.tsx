const labels: Record<string, string> = {
  NEEDS_CONFIRMATION: 'Нужно подтверждение',
  ACTION_READY: 'Готово к передаче',
  SUBMITTED: 'Передано',
  ACCEPTED: 'Принято УК',
  WORK_IN_PROGRESS: 'Работа выполняется',
  DONE_PENDING_VERIFICATION: 'Ждёт проверки',
  CLOSED: 'Подтверждено и закрыто',
  REOPENED: 'Переоткрыто',
  ACTIVE_ISSUE: 'Активная проблема',
  RECURRING: 'Повторяется',
  HEALTHY: 'Штатно',
  UNKNOWN: 'Нет данных',
  INFORMAL_POLL: 'Неофициальный опрос',
  FORMAL_HANDOFF_REQUIRED: 'Нужен формальный процесс',
}

export function StatusBadge({ value }: { value: string }) {
  const tone = ['CLOSED', 'HEALTHY'].includes(value)
    ? 'positive'
    : ['REOPENED', 'ACTIVE_ISSUE', 'RECURRING'].includes(value)
      ? 'danger'
      : 'neutral'
  return <span className={`status status--${tone}`}>{labels[value] || value}</span>
}

