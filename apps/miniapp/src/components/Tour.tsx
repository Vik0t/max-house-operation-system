import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

export type TourStep = {
  /** CSS selector of the element to spotlight; if missing, the card is centered. */
  target?: string
  /** Bottom-nav tab to activate before showing this step. */
  tab?: string
  title: string
  body: string
  mascot: string
}

type Props = {
  steps: TourStep[]
  onClose: () => void
  onNavigate?: (tab: string) => void
}

type Rect = { top: number; left: number; width: number; height: number }

export function Tour({ steps, onClose, onNavigate }: Props) {
  const [index, setIndex] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const step = steps[index]

  const measure = useCallback(() => {
    if (!step?.target) { setRect(null); return }
    const el = document.querySelector(step.target)
    if (!el) { setRect(null); return }
    const r = el.getBoundingClientRect()
    setRect({ top: r.top, left: r.left, width: r.width, height: r.height })
  }, [step])

  // When the step changes, switch to its tab (if any), bring the target into
  // view, then measure it. The delayed pass covers targets that appear only
  // after the tab has rendered.
  useLayoutEffect(() => {
    const run = () => {
      const el = step?.target ? document.querySelector(step.target) : null
      if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      measure()
    }
    if (step?.tab) onNavigate?.(step.tab)
    run()
    const timer = window.setTimeout(run, 300)
    return () => window.clearTimeout(timer)
  }, [measure, step, onNavigate])

  useEffect(() => {
    const onChange = () => measure()
    window.addEventListener('resize', onChange)
    window.addEventListener('scroll', onChange, true)
    return () => {
      window.removeEventListener('resize', onChange)
      window.removeEventListener('scroll', onChange, true)
    }
  }, [measure])

  const last = index === steps.length - 1
  const next = () => { if (last) onClose(); else setIndex((i) => i + 1) }
  const back = () => setIndex((i) => Math.max(0, i - 1))

  let cardStyle: CSSProperties = { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
  if (rect) {
    const cardW = Math.min(340, window.innerWidth - 32)
    let left = rect.left + rect.width / 2 - cardW / 2
    left = Math.max(16, Math.min(left, window.innerWidth - cardW - 16))
    const spaceBelow = window.innerHeight - (rect.top + rect.height)
    const below = spaceBelow >= rect.top
    cardStyle = below
      ? { left, top: rect.top + rect.height + 14, width: cardW }
      : { left, bottom: window.innerHeight - rect.top + 14, width: cardW }
  }

  return <div className="tour-overlay" role="presentation" onClick={next}>
    {rect
      ? <div className="tour-spotlight" style={{ top: rect.top - 8, left: rect.left - 8, width: rect.width + 16, height: rect.height + 16 }} />
      : <div className="tour-dim" />}
    <div ref={cardRef} className="tour-card" style={cardStyle} onClick={(event) => event.stopPropagation()}>
      <button className="tour-skip" onClick={onClose} aria-label="Пропустить обучение">Пропустить</button>
      <div className="tour-main">
        <img className="tour-mascot" src={step.mascot} alt="Макс" />
        <div className="tour-body">
          <div className="tour-title">{step.title}</div>
          <div className="tour-text">{step.body}</div>
        </div>
      </div>
      <div className="tour-footer">
        <div className="tour-dots">
          {steps.map((_, i) => <span key={i} className={`tour-dot${i === index ? ' tour-dot--on' : ''}`} />)}
        </div>
        <div className="tour-actions">
          {index > 0 ? <button className="max-btn max-btn--ghost" onClick={back}>Назад</button> : null}
          <button className="max-btn max-btn--primary" onClick={next}>{last ? 'Понятно' : 'Далее'}</button>
        </div>
      </div>
    </div>
  </div>
}
