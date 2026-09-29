/** Resolve bundled, explicitly synthetic demo media under Vite's deploy base. */
export function mediaSrc(uri: string): string {
  return uri.startsWith('/demo/') ? `${import.meta.env.BASE_URL}${uri.slice(1)}` : uri
}
