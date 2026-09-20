const labels: Record<string, string> = {
  DETECTED: 'Требует уточнения',
  NEEDS_CONFIRMATION: 'Нужно подтверждение',
  CONFIRMED: 'Подтверждено',
  ACTION_READY: 'Готово к передаче',
  SUBMITTED: 'Передано',
  ACCEPTED: 'Принято УК',
  WORK_IN_PROGRESS: 'Работа выполняется',
  DONE_PENDING_VERIFICATION: 'Ждёт проверки',
  VERIFIED: 'Результат подтверждён',
  CLOSED: 'Подтверждено и закрыто',
  REOPENED: 'Переоткрыто',
  DUPLICATE: 'Объединено с другой проблемой',
  NEW: 'Новая работа',
  ASSIGNED: 'Назначена исполнителю',
  IN_PROGRESS: 'Исполняется',
  DONE: 'Выполнена, ждёт проверки',
  REWORK_REQUIRED: 'Нужна доработка',
  ACTIVE_ISSUE: 'Активная проблема',
  RECURRING: 'Повторяется',
  HEALTHY: 'Штатно',
  UNKNOWN: 'Нет данных',
  INFORMAL_POLL: 'Неофициальный опрос',
  RESULT: 'Результат опроса',
  FORMAL_HANDOFF_REQUIRED: 'Нужна официальная передача',
}

export function StatusBadge({ value }: { value: string }) {
  const tone = ['CLOSED', 'HEALTHY'].includes(value)
    ? 'positive'
    : ['REOPENED', 'ACTIVE_ISSUE', 'RECURRING'].includes(value)
      ? 'danger'
      : 'neutral'
  return <span className={`status status--${tone}`}>{labels[value] || 'Состояние уточняется'}</span>
}
