import { useRef, useState } from 'react'

type Props = {
  photos: string[]
  onChange: (photos: string[]) => void
  label?: string
  max?: number
}

async function fileToDataUrl(file: File, maxSide = 900, quality = 0.72): Promise<string> {
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const element = new Image()
    const url = URL.createObjectURL(file)
    element.onload = () => { URL.revokeObjectURL(url); resolve(element) }
    element.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Не удалось прочитать изображение')) }
    element.src = url
  })
  const scale = Math.min(1, maxSide / Math.max(image.width, image.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(image.width * scale))
  canvas.height = Math.max(1, Math.round(image.height * scale))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas недоступен')
  context.drawImage(image, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', quality)
}

export function PhotoInput({ photos, onChange, label = 'Приложить фото', max = 4 }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function pick(files: FileList | null) {
    if (!files?.length) return
    setBusy(true)
    setError(null)
    try {
      const next = [...photos]
      for (const file of Array.from(files).slice(0, Math.max(0, max - photos.length))) {
        if (!file.type.startsWith('image/')) throw new Error('Выберите файл изображения')
        const encoded = await fileToDataUrl(file)
        if (encoded.length > 700_000) throw new Error('Фото слишком большое. Выберите другое изображение')
        next.push(encoded)
      }
      onChange(next)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось прочитать фото') } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return <div className="photo-input">
    <div className="photo-thumbs">
      {photos.map((source, index) => <div className="photo-thumb" key={index}>
        <img src={source} alt="" />
        <button type="button" className="photo-remove" aria-label="Удалить фото" onClick={() => onChange(photos.filter((_, i) => i !== index))}>×</button>
      </div>)}
      {photos.length < max ? <button type="button" className="photo-add" onClick={() => inputRef.current?.click()} disabled={busy} aria-label={label}>
        <span>{busy ? '…' : '+'}</span>
      </button> : null}
    </div>
    <span className="photo-hint">{label} · {photos.length}/{max}</span>
    {error ? <span className="photo-hint" role="alert">{error}</span> : null}
    <input ref={inputRef} type="file" accept="image/*" multiple hidden onChange={(event) => void pick(event.target.files)} />
  </div>
}
