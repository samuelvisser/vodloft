import {useCallback, useEffect, useState, type CSSProperties} from 'react'

type Shape = 'square' | 'portrait' | 'landscape'
type EdgeColors = {left: string, right: string, top: string, bottom: string}

// Artwork within this ratio of square fills the tile; anything further off is shown whole.
const SQUARE_MIN = 0.85
const SQUARE_MAX = 1.18

function shapeOf(image: HTMLImageElement): Shape {
    const ratio = image.naturalWidth / image.naturalHeight
    if (ratio < SQUARE_MIN) return 'portrait'
    if (ratio > SQUARE_MAX) return 'landscape'
    return 'square'
}

// One sample per image URL for the whole session: tiles remount on every filter change.
const edgeColorCache = new Map<string, Promise<EdgeColors | null>>()
const SAMPLE_SIZE = 32
const STRIP = 2

function sampleEdgeColors(image: HTMLImageElement): EdgeColors | null {
    const canvas = document.createElement('canvas')
    canvas.width = SAMPLE_SIZE
    canvas.height = SAMPLE_SIZE
    const context = canvas.getContext('2d', {willReadFrequently: true})
    if (!context) return null
    context.drawImage(image, 0, 0, SAMPLE_SIZE, SAMPLE_SIZE)
    const average = (x: number, y: number, width: number, height: number) => {
        const data = context.getImageData(x, y, width, height).data
        let red = 0, green = 0, blue = 0
        for (let i = 0; i < data.length; i += 4) {
            red += data[i]
            green += data[i + 1]
            blue += data[i + 2]
        }
        const pixels = data.length / 4
        return `rgb(${Math.round(red / pixels)}, ${Math.round(green / pixels)}, ${Math.round(blue / pixels)})`
    }
    try {
        return {
            left: average(0, 0, STRIP, SAMPLE_SIZE),
            right: average(SAMPLE_SIZE - STRIP, 0, STRIP, SAMPLE_SIZE),
            top: average(0, 0, SAMPLE_SIZE, STRIP),
            bottom: average(0, SAMPLE_SIZE - STRIP, SAMPLE_SIZE, STRIP),
        }
    } catch {
        // The image host sent no CORS headers, so the browser will not let us read its pixels.
        return null
    }
}

function edgeColors(src: string): Promise<EdgeColors | null> {
    let pending = edgeColorCache.get(src)
    if (!pending) {
        pending = new Promise((resolve) => {
            // A separate CORS request: the visible <img> must not need CORS to load.
            const probe = new Image()
            probe.crossOrigin = 'anonymous'
            probe.onload = () => resolve(sampleEdgeColors(probe))
            probe.onerror = () => resolve(null)
            probe.src = src
        })
        edgeColorCache.set(src, pending)
    }
    return pending
}

/**
 * Square Library artwork. Square artwork (channel avatars) fills the tile. Posters and wide
 * thumbnails are shown whole, on the colour of their own edges, so a poster stands upright and
 * a thumbnail sits across the middle. When the image host does not allow reading those colours,
 * a blurred copy of the artwork fills the tile instead.
 */
export default function CollectionTileArt({src}: {src: string}) {
    const [shape, setShape] = useState<Shape | null>(null)
    const [edges, setEdges] = useState<EdgeColors | null | undefined>(undefined)

    // Callers key this component by src, so a new image starts from a fresh state.
    useEffect(() => {
        if (!shape || shape === 'square') return
        let current = true
        edgeColors(src).then((colors) => {
            if (current) setEdges(colors)
        })
        return () => {
            current = false
        }
    }, [shape, src])

    const measure = useCallback((image: HTMLImageElement | null) => {
        if (image?.complete && image.naturalWidth) setShape(shapeOf(image))
    }, [])

    let background: CSSProperties | undefined
    if (edges && shape === 'portrait') background = {background: `linear-gradient(90deg, ${edges.left} 50%, ${edges.right} 50%)`}
    if (edges && shape === 'landscape') background = {background: `linear-gradient(180deg, ${edges.top} 50%, ${edges.bottom} 50%)`}

    return (
        <span className={`library-tile-artwork${shape ? ` is-${shape}` : ''}`} style={background}>
            {edges === null && (
                <img className="library-tile-backdrop" src={src} alt="" aria-hidden="true" loading="lazy" decoding="async"/>
            )}
            <img
                ref={measure}
                className="library-tile-image"
                src={src}
                alt=""
                loading="lazy"
                decoding="async"
                onLoad={(event) => setShape(shapeOf(event.currentTarget))}
            />
        </span>
    )
}
