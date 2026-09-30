export type MaxUser = {
  id: number
  first_name: string
  last_name?: string
  username?: string | null
  language_code?: string
  photo_url?: string | null
}

export type MaxChat = {
  id: number
  type: 'DIALOG' | 'CHAT' | 'CHANNEL'
}

export type MaxInitData = {
  user?: MaxUser
  chat?: MaxChat
  start_param?: string
  auth_date?: number
  query_id?: string
}

type MaxWebApp = {
  initData?: string
  initDataUnsafe?: MaxInitData
  platform?: string
  version?: string
  shareMaxContent?: (params: { text?: string; link?: string } | { mid: string; chatType: 'DIALOG' | 'CHAT' }) => Promise<unknown>
  HapticFeedback?: { notificationOccurred?: (style: 'error' | 'success' | 'warning') => void }
}

declare global {
  interface Window {
    WebApp?: MaxWebApp
  }
}

export function getMaxLaunchContext() {
  const webApp = window.WebApp
  // MAX also puts the signed data in the URL fragment. The Bridge may become
  // available after React's first render (notably in some mobile webviews),
  // so read both sources every time instead of caching an empty first value.
  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const initData = webApp?.initData || fragment.get('WebAppData') || ''
  const signedParams = new URLSearchParams(initData)
  const queryIssue = new URLSearchParams(window.location.search).get('issue')
  const startParam = webApp?.initDataUnsafe?.start_param || fragment.get('WebAppStartParam') || signedParams.get('start_param') || undefined
  const startIssue = startParam?.startsWith('issue_') ? startParam.slice('issue_'.length) : undefined
  return {
    available: Boolean(initData),
    initData,
    unsafe: webApp?.initDataUnsafe,
    platform: webApp?.platform || fragment.get('WebAppPlatform') || undefined,
    version: webApp?.version,
    issueId: queryIssue || startIssue,
  }
}

export async function shareIssue(title: string, issueId: string) {
  const webApp = window.WebApp
  const url = `${window.location.origin}${import.meta.env.BASE_URL}?issue=${encodeURIComponent(issueId)}`
  if (webApp?.shareMaxContent) {
    await webApp.shareMaxContent({ text: `${title}\n${url}` })
    return
  }
  await navigator.clipboard.writeText(url)
}

export function notifyMax(style: 'error' | 'success' | 'warning') {
  window.WebApp?.HapticFeedback?.notificationOccurred?.(style)
}
