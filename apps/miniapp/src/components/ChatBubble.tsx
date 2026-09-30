import { useEffect, useRef, useState } from 'react'
import { askMax, type ChatMessage } from '../chat'
import { mascot } from '../mascot'
import { getMaxLaunchContext } from '../maxBridge'

type Bubble = { role: 'user' | 'assistant'; content: string }

const SUGGESTIONS = [
  'Что такое «Дом.Среда»?',
  'Как передать проблему в УК?',
  'Кто такой домоуправляющий?',
]

export function ChatBubble({ houseId }: { houseId?: string }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Bubble[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'OPENROUTER' | 'LOCAL_RULES' | null>(null)
  const [providerEnabled, setProviderEnabled] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, busy, open])
  useEffect(() => {
    if (!open) return
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
    void fetch(`${apiUrl}/assistant/status`).then((response) => response.json()).then((status) => setProviderEnabled(status.mode === 'OPENROUTER' && Boolean(getMaxLaunchContext().initData))).catch(() => setProviderEnabled(false))
  }, [open])

  async function send(text: string) {
    const value = text.trim()
    if (!value || busy) return
    const history: ChatMessage[] = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [...prev, { role: 'user', content: value }])
    setInput('')
    setBusy(true)
    setError(null)
    try {
      const result = await askMax([...history, { role: 'user', content: value }], houseId)
      setMode(result.mode)
      setMessages((prev) => [...prev, { role: 'assistant', content: result.answer }])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось получить ответ')
    } finally {
      setBusy(false)
    }
  }

  return <>
    <button className="chat-fab" aria-label="Чат с Максом" onClick={() => setOpen((value) => !value)}>
      <img src={mascot.hero} alt="" />
    </button>

    {open ? <section className="chat-panel" aria-label="Чат с Максом">
      <header className="chat-head">
        <img className="chat-head-avatar" src={mascot.tip} alt="" />
        <div className="chat-head-info">
          <strong>Макс</strong>
          <span>{mode === 'OPENROUTER' ? 'ИИ-помощник' : mode === 'LOCAL_RULES' ? 'помощник по проверенным правилам' : 'помощник по дому'}</span>
        </div>
        <button className="chat-close" onClick={() => setOpen(false)} aria-label="Закрыть чат">×</button>
      </header>

      <div className="chat-log" ref={logRef}>
        {messages.length === 0 ? <div className="chat-intro">
          <img src={mascot.hero} alt="Макс" />
          <p>Привет! Я Макс 🕊️ Спросите про дом, обращения или роли. Если внешний ИИ недоступен, отвечу по проверенным правилам.</p>
          <div className="chat-suggestions">
            {SUGGESTIONS.map((text) => <button key={text} className="chip" onClick={() => void send(text)}>{text}</button>)}
          </div>
        </div> : messages.map((message, index) => (
          <div key={index} className={`chat-msg chat-msg--${message.role}`}>{message.content}</div>
        ))}
        {busy ? <div className="chat-msg chat-msg--assistant chat-typing">Макс печатает…</div> : null}
        {error ? <div className="chat-error">{error}</div> : null}
      </div>

      <form className="chat-input" onSubmit={(event) => { event.preventDefault(); void send(input) }}>
        <p className="disclosure" style={{ width: '100%' }}>{providerEnabled ? 'Только ваши сообщения в этом чате отправляются внешнему ИИ OpenRouter. Не пишите здесь личные данные. Обращения и сообщения из групп не передаются.' : 'Помощник отвечает по локальным правилам. Обращения и сообщения из групп не передаются внешнему ИИ.'}</p>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Спросите Макса…"
          disabled={busy}
          aria-label="Сообщение Максу"
        />
        <button className="max-btn max-btn--primary" type="submit" disabled={busy || !input.trim()}>Отправить</button>
      </form>
    </section> : null}
  </>
}
