import {useEffect, useRef} from 'react'

/** How long the user may pause typing before a link is looked up on its own. */
const TYPING_PAUSE_MS = 600

/** Whether what is in a link field could be a web address, so it is worth looking up without being asked. */
export function looksLikeUrl(value: string): boolean {
    const trimmed = value.trim()
    if (!trimmed || /\s/.test(trimmed)) return false
    try {
        const url = new URL(/^[a-z][a-z\d+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`)
        return (url.protocol === 'http:' || url.protocol === 'https:') && /\.[a-z]{2,}$/i.test(url.hostname)
    } catch {
        return false
    }
}

type AutoLookupOptions = {
    /** Looks the link up. A new lookup replaces the one that may be running. */
    lookUp: (value: string) => void
    /** Stops a running lookup; says whether one was running. */
    cancel: () => boolean
}

/**
 * Looks up the link in a link field as soon as it is pasted, or once the user stops typing, and only when it looks like
 * a web address. A link that was already looked up is not looked up again until it changes; a lookup of a link the
 * user has since changed stops.
 */
export function useAutoLookup({lookUp, cancel}: AutoLookupOptions) {
    const timer = useRef<number | undefined>(undefined)
    const pasted = useRef(false)
    // The link last looked up, whether on its own or by the user.
    const looked = useRef<string | null>(null)

    useEffect(() => () => window.clearTimeout(timer.current), [])

    const run = (value: string) => {
        const trimmed = value.trim()
        if (trimmed === looked.current) return
        looked.current = trimmed
        lookUp(trimmed)
    }

    return {
        /** The input's onPaste: the link it brings is looked up right away. */
        onPaste: () => { pasted.current = true },
        /** Call with each new value of the field. */
        changed: (value: string) => {
            window.clearTimeout(timer.current)
            const fromPaste = pasted.current
            pasted.current = false
            const trimmed = value.trim()
            if (trimmed !== looked.current && cancel()) looked.current = null
            if (!looksLikeUrl(trimmed)) return
            if (fromPaste) run(trimmed)
            else timer.current = window.setTimeout(() => run(trimmed), TYPING_PAUSE_MS)
        },
        /** A lookup the page started itself, such as from its Look up button or its address. */
        remember: (value: string) => {
            window.clearTimeout(timer.current)
            looked.current = value.trim()
        },
        /** The field was cleared. */
        reset: () => {
            window.clearTimeout(timer.current)
            looked.current = null
        },
    }
}
