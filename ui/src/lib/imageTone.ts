import {useEffect, useState} from 'react'

/** Whether a picture is dark or light where something sits over it. */
export type Tone = 'dark' | 'light'

// One sample per image URL for the whole session: Library tiles remount on every filter change.
const toneCache = new Map<string, Promise<Tone | null>>()
const SAMPLE_SIZE = 32
// Linear luminance below which a picture counts as dark (about mid grey to the eye).
const DARK_BELOW = 0.2

const linear = (channel: number) => {
    const value = channel / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
}

/**
 * The tone of the ring between radius `inner` and `outer` (fractions of the side) around the middle of the
 * picture as a square tile with `background-size: cover` shows it, or null when the host does not allow
 * reading its pixels.
 */
function sampleRingTone(image: HTMLImageElement, inner: number, outer: number): Tone | null {
    const canvas = document.createElement('canvas')
    canvas.width = SAMPLE_SIZE
    canvas.height = SAMPLE_SIZE
    const context = canvas.getContext('2d', {willReadFrequently: true})
    if (!context) return null
    // The middle square of the picture, as a cover background in a square tile crops it.
    const side = Math.min(image.naturalWidth, image.naturalHeight)
    const x = (image.naturalWidth - side) / 2
    const y = (image.naturalHeight - side) / 2
    context.drawImage(image, x, y, side, side, 0, 0, SAMPLE_SIZE, SAMPLE_SIZE)
    let data: Uint8ClampedArray
    try {
        data = context.getImageData(0, 0, SAMPLE_SIZE, SAMPLE_SIZE).data
    } catch {
        // The image host sent no CORS headers, so the browser will not let us read its pixels.
        return null
    }
    const centre = SAMPLE_SIZE / 2
    let total = 0, count = 0
    for (let row = 0; row < SAMPLE_SIZE; row++) {
        for (let column = 0; column < SAMPLE_SIZE; column++) {
            const distance = Math.hypot(column + 0.5 - centre, row + 0.5 - centre) / SAMPLE_SIZE
            if (distance < inner || distance > outer) continue
            const i = (row * SAMPLE_SIZE + column) * 4
            total += 0.2126 * linear(data[i]) + 0.7152 * linear(data[i + 1]) + 0.0722 * linear(data[i + 2])
            count++
        }
    }
    if (!count) return null
    return total / count < DARK_BELOW ? 'dark' : 'light'
}

function ringTone(src: string, inner: number, outer: number): Promise<Tone | null> {
    const key = `${inner}:${outer}:${src}`
    let pending = toneCache.get(key)
    if (!pending) {
        pending = new Promise((resolve) => {
            // A separate CORS request: the visible picture must not need CORS to load.
            const probe = new Image()
            probe.crossOrigin = 'anonymous'
            probe.onload = () => resolve(sampleRingTone(probe, inner, outer))
            probe.onerror = () => resolve(null)
            probe.src = src
        })
        toneCache.set(key, pending)
    }
    return pending
}

/**
 * The tone of a cover picture in a square tile around a circle in its middle, between radius `inner` and `outer`
 * (fractions of the tile's side). Undefined while it loads and null when it cannot be read.
 */
export function useRingTone(src: string | undefined, inner: number, outer: number): Tone | null | undefined {
    const [tone, setTone] = useState<{src: string, tone: Tone | null} | null>(null)
    useEffect(() => {
        if (!src) return
        let current = true
        ringTone(src, inner, outer).then((found) => {
            if (current) setTone({src, tone: found})
        })
        return () => {
            current = false
        }
    }, [src, inner, outer])
    if (!src) return null
    return tone?.src === src ? tone.tone : undefined
}
