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

function badgeClass(value: string): string {
  if (['CLOSED', 'HEALTHY', 'VERIFIED'].includes(value)) return 'status-badge status-badge--done'
  if (['REOPENED', 'ACTIVE_ISSUE', 'RECURRING', 'REWORK_REQUIRED'].includes(value)) return 'status-badge status-badge--danger'
  if (['IN_PROGRESS', 'WORK_IN_PROGRESS', 'ASSIGNED', 'DONE_PENDING_VERIFICATION'].includes(value)) return 'status-badge status-badge--progress'
  if (['CONFIRMED'].includes(value)) return 'status-badge status-badge--confirmed'
  if (['ACTION_READY', 'SUBMITTED'].includes(value)) return 'status-badge status-badge--submitted'
  if (['DETECTED', 'NEEDS_CONFIRMATION', 'NEW'].includes(value)) return 'status-badge status-badge--new'
  return 'status-badge status-badge--new'
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={badgeClass(value)}>{labels[value] || 'Состояние уточняется'}</span>
}
