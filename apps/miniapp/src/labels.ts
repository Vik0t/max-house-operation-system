import type { Issue } from './types'

const categoryLabels: Record<string, string> = {
  elevator: 'Лифт',
  lighting: 'Освещение',
  water: 'Вода и отопление',
  door: 'Дверь и домофон',
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
