import { useEffect, useRef, useState } from 'react'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faIcon } from '../../icons/faIcon'
import './PullToRefresh.css'

// How far the finger moves for each pixel the indicator moves, and how far the indicator must come down to reload.
const RESISTANCE = 0.5
const MAX_PULL = 110
const TRIGGER = 70

function installedApp(): boolean {
    return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
}

/** Whether the touch began inside something that is itself scrolled down, such as a dialog or a long list. */
function insideScrolledArea(target: EventTarget | null): boolean {
    for (let element = target instanceof Element ? target : null; element && element !== document.body; element = element.parentElement) {
        if (element.scrollTop > 0) return true
    }
    return false
}

/**
 * Pull down at the top of the page to reload, in the installed app only: a browser tab has its own, but the
 * home screen app on iPhone and iPad has none.
 */
export default function PullToRefresh() {
    const [pull, setPull] = useState(0)
    const [reloading, setReloading] = useState(false)
    const start = useRef<number | null>(null)
    const distance = useRef(0)

    useEffect(() => {
        if (!installedApp()) return

        const onStart = (event: TouchEvent) => {
            const scrolled = window.scrollY > 0 || document.documentElement.scrollTop > 0
            start.current = event.touches.length === 1 && !scrolled && !insideScrolledArea(event.target)
                ? event.touches[0].clientY : null
        }
        const onMove = (event: TouchEvent) => {
            if (start.current === null) return
            const moved = (event.touches[0].clientY - start.current) * RESISTANCE
            if (moved <= 0 || window.scrollY > 0) {
                start.current = null
                distance.current = 0
                setPull(0)
                return
            }
            distance.current = Math.min(moved, MAX_PULL)
            setPull(distance.current)
        }
        const onEnd = () => {
            if (start.current === null) return
            start.current = null
            if (distance.current >= TRIGGER) {
                setReloading(true)
                setPull(TRIGGER)
                window.location.reload()
            } else {
                setPull(0)
            }
            distance.current = 0
        }

        window.addEventListener('touchstart', onStart, { passive: true })
        window.addEventListener('touchmove', onMove, { passive: true })
        window.addEventListener('touchend', onEnd)
        window.addEventListener('touchcancel', onEnd)
        return () => {
            window.removeEventListener('touchstart', onStart)
            window.removeEventListener('touchmove', onMove)
            window.removeEventListener('touchend', onEnd)
            window.removeEventListener('touchcancel', onEnd)
        }
    }, [])

    if (pull <= 0 && !reloading) return null
    const ready = pull >= TRIGGER
    return (
        <div
            className={`pull-to-refresh${ready ? ' is-ready' : ''}`}
            style={{ transform: `translate(-50%, ${pull}px)`, opacity: Math.min(1, pull / TRIGGER) }}
            role="status"
            aria-label={reloading ? 'Reloading' : ready ? 'Release to reload' : 'Pull to reload'}
        >
            <FontAwesomeIcon
                icon={faIcon('fass', reloading ? 'spinner' : 'rotate-right')}
                spin={reloading}
                style={reloading ? undefined : { transform: `rotate(${(pull / TRIGGER) * 270}deg)` }}
                aria-hidden="true"
            />
        </div>
    )
}
