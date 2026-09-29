import { getMaxLaunchContext } from './maxBridge'

export type ChatRole = 'user' | 'assistant'
export type ChatMessage = { role: ChatRole; content: string }

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/** A server-side helper: provider keys never enter the GitHub Pages bundle. */
export async function askMax(messages: ChatMessage[], houseId?: string): Promise<{ answer: string; mode: 'OPENROUTER' | 'LOCAL_RULES' }> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 15_000)
  try {
    const initData = getMaxLaunchContext().initData
    const response = await fetch(`${API_URL}/assistant/chat`, {
      method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(initData ? { 'X-Max-Init-Data': initData } : {}) },
      body: JSON.stringify({ messages: messages.slice(-10), house_id: houseId }),
    })
    if (!response.ok) throw new Error('Помощник сейчас недоступен. Попробуйте позже.')
    return await response.json()
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('Макс не успел ответить. Попробуйте ещё раз.')
    throw error instanceof Error ? error : new Error('Не удалось получить ответ')
  } finally {
    window.clearTimeout(timer)
  }
}
