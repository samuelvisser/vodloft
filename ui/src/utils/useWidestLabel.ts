import {useEffect, useMemo, useState} from 'react'

/** What a select adds around its label: padding, the separator and the arrow. */
const SELECT_CHROME = 64

/**
 * How wide, in pixels, a select has to be to show the longest of these labels in full, in the page's font. Selects
 * that share it line up at the same width, the widest one's.
 */
export function useWidestLabel(labels: readonly string[]): number | undefined {
    // The page's own font can still be loading, and is narrower or wider than the one before it.
    const [fontsReady, setFontsReady] = useState(0)
    useEffect(() => {
        let live = true
        document.fonts?.ready.then(() => { if (live) setFontsReady((count) => count + 1) })
        return () => { live = false }
    }, [])
    const key = labels.join('\n')
    return useMemo(() => {
        if (!labels.length || typeof document === 'undefined') return undefined
        const context = document.createElement('canvas').getContext('2d')
        if (!context) return undefined
        context.font = getComputedStyle(document.body).font
        const widest = Math.max(...labels.map((label) => context.measureText(label).width))
        return Math.ceil(widest + SELECT_CHROME)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, fontsReady])
}
