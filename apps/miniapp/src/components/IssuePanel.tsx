import { useState } from 'react'
import type { Issue, ViewerRole } from '../types'
import { issueTitle, pluralRu, provenanceLabel, roleName, severityLabel, severityTone } from '../labels'
import { StatusBadge } from './StatusBadge'
import { PhotoInput } from './PhotoInput'

type Props = {
  issue: Issue
  managementOrg?: string
  viewerId?: string
  alreadyReported?: boolean
  role: ViewerRole
  busy: boolean
  readOnly?: boolean
  onAction: (action: string, evidence?: { uri: string; comment: string }) => void
  onComment: (text: string, photos: string[]) => void
  onClose: () => void
  onShare: () => void
  onOpenRelated?: (id: string) => void
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function routeLabel(destination: string, managementOrg?: string): string {
  if (/uk|management|управляющ/i.test(destination)) return managementOrg || 'Управляющая организация'
  if (/representative|домоуправляющ/i.test(destination)) return 'Домоуправляющий'
  if (/contractor|подряд/i.test(destination)) return 'Подрядная организация'
  return 'Ответственный по дому'
}

function signalSourceLabel(sourceType: string): string {
  return ['max_message', 'max_webapp', 'bot_dialog'].includes(sourceType) ? 'MAX' : 'Приложение'
}

function nextAction(issue: Issue, role: ViewerRole, viewerId?: string, alreadyReported = false): { action: string; label: string } | null {
  const order = issue.work_orders?.at(-1)
  // Only an order that is still being worked on offers executor actions.
  const active = order && ['ASSIGNED', 'IN_PROGRESS', 'REWORK_REQUIRED'].includes(order.status) ? order : undefined
  if (role === 'resident' && ['NEEDS_CONFIRMATION', 'DETECTED'].includes(issue.state)) {
    return alreadyReported || issue.signals?.some((signal) => signal.author_id === viewerId) ? null : { action: 'confirm', label: 'У меня тоже' }
  }
  if (role === 'representative' && ['NEEDS_CONFIRMATION', 'DETECTED'].includes(issue.state)) return { action: 'confirm', label: 'Подтвердить проблему' }
  if (role === 'representative' && issue.state === 'CONFIRMED') return { action: 'prepare', label: 'Подготовить действие' }
  if (role === 'representative' && issue.state === 'ACTION_READY' && (issue.actions?.at(-1)?.confidence ?? 0) >= 0.7) return { action: 'submit', label: 'Передать в УК' }
  if (role === 'uk' && issue.state === 'SUBMITTED') return { action: 'accept', label: 'Принять обращение' }
  if (role === 'uk' && ['ACCEPTED', 'REOPENED'].includes(issue.state) && !active) return { action: 'create-order', label: 'Назначить исполнителя' }
  if (role === 'executor' && active?.status === 'ASSIGNED') return { action: 'start', label: 'Начать работу' }
  if (role === 'executor' && active?.status === 'REWORK_REQUIRED') return { action: 'restart', label: 'Начать доработку' }
  return null
}

export function IssuePanel({ issue, managementOrg, viewerId, alreadyReported, role, busy, readOnly, onAction, onComment, onClose, onShare, onOpenRelated }: Props) {
  const next = readOnly ? null : nextAction(issue, role, viewerId, alreadyReported)
  const order = issue.work_orders?.at(-1)
  const freshEvidence = Boolean(order?.started_at && order.evidence.some((item) => new Date(item.created_at).getTime() >= new Date(order.started_at!).getTime()))
  const evidenceCount = issue.work_orders?.reduce((sum, wo) => sum + wo.evidence.length, 0) || 0
  const [note, setNote] = useState('')
  const [notePhotos, setNotePhotos] = useState<string[]>([])
  const [workPhotos, setWorkPhotos] = useState<string[]>([])
  const [workNote, setWorkNote] = useState('')
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="issue-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="drawer-close" onClick={onClose} aria-label="Закрыть карточку">×</button>
        <p className="eyebrow">{role === 'resident' ? 'Обращение жителей' : 'Рабочая задача'}</p>
        <h2 id="issue-title">{issueTitle(issue)}</h2>
        <div className="drawer-badges">
          <StatusBadge value={issue.state} />
          <span className={`severity ${severityTone(issue.severity)}`}>{severityLabel(issue.severity)}</span>
          <span style={{ fontSize: 'var(--fs-tag)', color: 'var(--text-tertiary)' }}>Источник: {provenanceLabel(issue.provenance)}</span>
        </div>
        <p className="lead">{issue.description}</p>

        {issue.photos?.length ? <div className="issue-photos">
          {issue.photos.map((source, index) => <img key={index} src={source} alt="" />)}
        </div> : null}

        {issue.state === 'DECLINED' && issue.decline_reason ? <div className="drawer-insight">Причина отказа: {issue.decline_reason}</div> : null}

        <div className="drawer-facts">
          <div className="drawer-fact">
            <strong>{issue.confirmations_count}</strong>
            <span>подтверждений</span>
          </div>
          <div className="drawer-fact">
            <strong>{issue.recurrence_count}</strong>
            <span>событий за период</span>
          </div>
          <div className="drawer-fact">
            <strong>{evidenceCount}</strong>
            <span>фото и материалы</span>
          </div>
        </div>

        {issue.recurrence_count >= 3 ? <div className="drawer-insight">↻ Повторяющаяся проблема: {issue.recurrence_count} {pluralRu(issue.recurrence_count, 'событие', 'события', 'событий')} за 90 дней</div> : null}

        {issue.related_issue_ids?.length ? <div className="drawer-block">
          <p className="eyebrow">Похожие открытые обращения</p>
          <p>По этому объекту есть другие открытые обращения ({issue.related_issue_ids.length}). Они не закрываются автоматически вместе с текущим.</p>
          {issue.related_issue_ids.map((id, index) => <button className="max-btn max-btn--secondary" key={id} onClick={() => onOpenRelated?.(id)}>Открыть похожее обращение №{index + 1}</button>)}
        </div> : null}

        {issue.signals?.length ? (
          <div className="drawer-block">
            <p className="eyebrow" style={{ marginBottom: 'var(--spacing-m)' }}>Исходные сообщения</p>
            <div className="flex-col gap-m">
              {issue.signals.map((signal) => (
                <div className="source-signal" key={signal.id}>
                  <span>{signalSourceLabel(signal.source_type)} · житель</span>
                  <strong>{signal.text}</strong>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {issue.actions?.at(-1) ? (
          <div className="drawer-block">
            <p className="eyebrow" style={{ marginBottom: 'var(--spacing-m)' }}>Рекомендованный маршрут</p>
            <span className="drawer-action-label">{routeLabel(issue.actions.at(-1)!.suggested_destination, managementOrg)}</span>
            <p style={{ fontSize: 'var(--fs-description)', color: 'var(--text-secondary)', marginTop: 'var(--spacing-xs)' }}>{issue.actions.at(-1)?.rationale}</p>
          </div>
        ) : null}

        {!readOnly && role === 'representative' && issue.state === 'ACTION_READY' && (issue.actions?.at(-1)?.confidence ?? 0) < 0.7 ? <div className="drawer-block">
          <p className="eyebrow">Нужно выбрать адресата</p>
          <p>Автоматический маршрут не подтверждён. Проверьте организацию и выберите, кому передать обращение.</p>
          <div className="btn-row">
            <button className="max-btn max-btn--primary" disabled={busy} onClick={() => onAction('route-management')}>В управляющую компанию</button>
            <button className="max-btn max-btn--secondary" disabled={busy} onClick={() => onAction('route-representative')}>Домоуправляющему</button>
          </div>
        </div> : null}

        {issue.submissions?.at(-1) ? (
          <div className="drawer-honesty">
            <b>ДЕМО</b>
            Передача в УК показана через демонстрационный канал, не как официальная отправка.
          </div>
        ) : null}

        {order ? (
          <div className="drawer-block">
            <p className="eyebrow" style={{ marginBottom: 'var(--spacing-m)' }}>Работа</p>
            <div className="drawer-work-order">
              <span className="drawer-action-label">Назначенный исполнитель</span>
              <StatusBadge value={order.status} />
            </div>
            <p style={{ fontSize: 'var(--fs-description)', color: 'var(--text-secondary)' }}>{order.title}</p>
            {order.evidence.map((item) => <div className="drawer-evidence" key={item.id}>✓ {item.comment || item.type}</div>)}
          </div>
        ) : null}

        {!readOnly ? <div className="drawer-block">
          <p className="eyebrow" style={{ marginBottom: 'var(--spacing-m)' }}>Заметки по обращению</p>
          {issue.comments?.length ? <div className="flex-col gap-m">
            {issue.comments.map((comment) => <div className="comment-item" key={comment.id}>
              <span className="comment-meta">{roleName(comment.author_role)}{comment.created_at ? ` · ${formatDate(comment.created_at)}` : ''}</span>
              <span className="comment-text">{comment.text}</span>
              {comment.photos?.length ? <div className="issue-photos issue-photos--sm">
                {comment.photos.map((source, index) => <img key={index} src={source} alt="" />)}
              </div> : null}
            </div>)}
          </div> : <p className="comment-empty">Пока нет заметок. Добавьте уточнение или статус работ.</p>}
          <div className="comment-form">
            <textarea
              className="comment-textarea"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={role === 'resident' ? 'Добавить уточнение к обращению…' : 'Добавить заметку для жителей и коллег…'}
              rows={2}
            />
            <PhotoInput photos={notePhotos} onChange={setNotePhotos} label="Фото к заметке" max={3} />
            <button
              className="max-btn max-btn--secondary"
              disabled={busy || (!note.trim() && !notePhotos.length)}
              onClick={() => { const text = note.trim() || 'Фото'; onComment(text, notePhotos); setNote(''); setNotePhotos([]) }}
            >
              Добавить заметку
            </button>
          </div>
        </div> : null}

        {!readOnly && role === 'executor' && order?.status === 'IN_PROGRESS' ? <div className="drawer-block">
          <p className="eyebrow" style={{ marginBottom: 'var(--spacing-m)' }}>Подтверждение выполненной работы</p>
          {freshEvidence ? <p>Подтверждение этой работы добавлено.</p> : order.evidence.length ? <p>После доработки нужно новое подтверждение.</p> : null}
          <PhotoInput photos={workPhotos} onChange={setWorkPhotos} label="Фото после работы" max={1} />
          <textarea className="comment-textarea" value={workNote} onChange={(event) => setWorkNote(event.target.value)} placeholder="Что именно сделали?" rows={2} />
          <button className="max-btn max-btn--primary max-btn--full" disabled={busy || (!workPhotos.length && !freshEvidence)} onClick={() => onAction('complete', workPhotos.length ? { uri: workPhotos[0], comment: workNote.trim() || 'Работа выполнена' } : undefined)}>Завершить и отправить на проверку</button>
        </div> : null}

        {next ? <button className="max-btn max-btn--primary max-btn--full" style={{ marginTop: 'var(--spacing-xl)' }} disabled={busy} onClick={() => onAction(next.action)}>
          {busy ? 'Выполняется…' : next.label}
        </button> : null}
        <button className="max-btn max-btn--secondary max-btn--full" style={{ marginTop: 'var(--spacing-m)' }} disabled={busy} onClick={onShare}>Поделиться в MAX</button>

        {!readOnly && role === 'resident' && issue.state === 'DONE_PENDING_VERIFICATION' ? (
          <div className="drawer-verify">
            <h3>Проблема устранена?</h3>
            <div className="btn-row">
              <button className="max-btn max-btn--primary" disabled={busy} onClick={() => onAction('verify-yes')}>Да, работает</button>
              <button className="max-btn max-btn--secondary" disabled={busy} onClick={() => onAction('verify-no')}>Нет, переоткрыть</button>
            </div>
          </div>
        ) : null}
      </aside>
    </div>
  )
}
