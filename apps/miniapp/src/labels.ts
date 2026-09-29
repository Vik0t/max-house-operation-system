import type { Issue } from './types'

export function pluralRu(count: number, one: string, few: string, many: string): string {
  const lastTwo = count % 100
  const last = count % 10
  if (lastTwo >= 11 && lastTwo <= 14) return many
  if (last === 1) return one
  if (last >= 2 && last <= 4) return few
  return many
}

const categoryLabels: Record<string, string> = {
  elevator: 'Лифт',
  lighting: 'Освещение',
  water: 'Вода и отопление',
  heating: 'Отопление',
  door: 'Дверь и домофон',
  cleaning: 'Уборка',
  parking: 'Парковка',
  other: 'Другое',
}

export function issueAssetLabel(issue: Pick<Issue, 'asset_name' | 'asset_id' | 'category' | 'title'>): string {
  const name = issue.asset_name?.trim()
  if (name && !name.toLowerCase().startsWith('lighting')) {
    if (issue.category === 'lighting' && name.toLowerCase().includes('лифт')) return 'Освещение'
    return name
  }
  if (issue.category && categoryLabels[issue.category]) return categoryLabels[issue.category]
  if (issue.title.includes(':')) return issue.title.split(':', 1)[0]
  return 'Объект уточняется'
}

export function issueTitle(issue: Pick<Issue, 'asset_name' | 'asset_id' | 'category' | 'title'>): string {
  const asset = issueAssetLabel(issue)
  if (issue.title.includes(':')) return `${asset}:${issue.title.split(':').slice(1).join(':')}`
  return issue.title || asset
}

export function provenanceLabel(value: string): string {
  return {
    OFFICIAL: 'официальный источник',
    USER: 'сообщение жителя',
    CALCULATED: 'расчёт системы',
    AI_INFERENCE: 'вывод ИИ, требует проверки',
    SYNTHETIC: 'демонстрационные данные',
  }[value] || 'источник уточняется'
}

const severityLabels: Record<string, string> = {
  LOW: 'Низкая',
  MEDIUM: 'Средняя',
  HIGH: 'Высокая',
  CRITICAL: 'Критичная',
}

export function severityLabel(value: string): string {
  return severityLabels[value] || 'Средняя'
}

export function severityTone(value: string): string {
  if (value === 'CRITICAL' || value === 'HIGH') return 'severity--high'
  if (value === 'LOW') return 'severity--low'
  return 'severity--medium'
}

const roleNames: Record<string, string> = {
  resident: 'Житель',
  representative: 'Домоуправляющий',
  uk: 'УК / диспетчер',
  executor: 'Исполнитель',
  admin: 'Администратор',
}

export function roleName(value: string): string {
  return roleNames[value] || 'Участник'
}
