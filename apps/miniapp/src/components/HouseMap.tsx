import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { House } from '../types'

type Props = {
  center: { lat: number; lng: number }
  houses: House[]
  selectedId?: string
  draft?: { lat: number; lng: number } | null
  onSelect: (house: House) => void
  onPick: (lat: number, lng: number) => void
}

export function HouseMap({ center, houses, selectedId, draft, onSelect, onPick }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const marksRef = useRef<L.LayerGroup | null>(null)
  const draftRef = useRef<L.CircleMarker | null>(null)
  const callbacks = useRef({ onSelect, onPick })
  callbacks.current = { onSelect, onPick }

  useEffect(() => {
    if (!hostRef.current || mapRef.current) return
    const map = L.map(hostRef.current, { scrollWheelZoom: false }).setView([center.lat, center.lng], 14)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors', maxZoom: 19,
    }).addTo(map)
    map.on('click', (event) => callbacks.current.onPick(event.latlng.lat, event.latlng.lng))
    mapRef.current = map
    marksRef.current = L.layerGroup().addTo(map)
    return () => { map.remove(); mapRef.current = null; marksRef.current = null }
  }, [center.lat, center.lng])

  useEffect(() => {
    if (!marksRef.current) return
    marksRef.current.clearLayers()
    for (const house of houses) {
      if (house.lat == null || house.lng == null) continue
      const selected = house.id === selectedId
      const mark = L.circleMarker([house.lat, house.lng], {
        radius: selected ? 11 : 8, color: '#fff', weight: 2,
        fillColor: selected ? '#ee5d4e' : '#348fb6', fillOpacity: 0.96,
        bubblingMouseEvents: false,
      })
      const label = document.createElement('div')
      const title = document.createElement('strong')
      title.textContent = house.address
      const detail = document.createElement('div')
      detail.textContent = house.management_org || 'Управляющая организация не подтверждена'
      label.append(title, detail)
      mark.bindPopup(label)
      mark.on('click', () => callbacks.current.onSelect(house))
      mark.addTo(marksRef.current)
    }
  }, [houses, selectedId])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (draftRef.current) draftRef.current.remove()
    draftRef.current = draft ? L.circleMarker([draft.lat, draft.lng], { radius: 10, color: '#fff', fillColor: '#5a9b60', fillOpacity: 1 }).addTo(map) : null
  }, [draft])

  return <>
    <div className="house-map" ref={hostRef} role="application" aria-label="Карта домов Кольцово" />
    <p className="map-hint">Нажмите на маркер, чтобы выбрать дом. Сведения из справочника жителей требуют проверки; карта работает без ключа.</p>
  </>
}
