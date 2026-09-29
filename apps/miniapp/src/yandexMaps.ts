// Яндекс.Карты (JS API 2.1). Ключ берётся из VITE_YANDEX_MAPS_API_KEY.
// Если ключ не задан, карта не загружается, но выбора адреса из списка
// и ручного добавления дома достаточно для работы приложения.
const API_KEY = String(import.meta.env.VITE_YANDEX_MAPS_API_KEY || '').trim()

export const mapsConfigured = API_KEY.length > 0

type Loader = Promise<any>
let loader: Loader | null = null

export function loadYmaps(): Promise<any> {
  if (!mapsConfigured) return Promise.reject(new Error('Ключ Яндекс.Карт не задан'))
  if (loader) return loader
  loader = new Promise((resolve, reject) => {
    const existing = (window as any).ymaps
    if (existing?.ready) { existing.ready(() => resolve(existing)); return }
    const script = document.createElement('script')
    script.src = `https://api-maps.yandex.ru/2.1/?apikey=${encodeURIComponent(API_KEY)}&lang=ru_RU`
    script.async = true
    script.onload = () => {
      const ymaps = (window as any).ymaps
      if (ymaps?.ready) ymaps.ready(() => resolve(ymaps))
      else reject(new Error('Не удалось инициализировать Яндекс.Карты'))
    }
    script.onerror = () => reject(new Error('Не удалось загрузить Яндекс.Карты'))
    document.head.appendChild(script)
  })
  return loader
}

export async function geocodeAddress(query: string): Promise<{ lat: number; lng: number; address: string } | null> {
  const ymaps = await loadYmaps()
  const result = await ymaps.geocode(query)
  const first = result?.geoObjects?.get?.(0)
  if (!first) return null
  const coords = first.geometry.getCoordinates() as [number, number]
  return { lat: coords[0], lng: coords[1], address: String(first.getAddressLine() || query) }
}

export async function reverseGeocode(lat: number, lng: number): Promise<string | null> {
  const ymaps = await loadYmaps()
  // Try the most precise match first, then relax. The Geocoder service must be
  // enabled on the API key («JavaScript API и HTTP Геокодер»).
  for (const options of [{ kind: 'house' }, { kind: 'street' }, {}] as Array<Record<string, unknown>>) {
    try {
      const result = await ymaps.geocode([lat, lng], options)
      const first = result?.geoObjects?.get?.(0)
      const line = first ? String(first.getAddressLine() || '').trim() : ''
      if (line) return line
    } catch { /* try the next variant */ }
  }
  return null
}
