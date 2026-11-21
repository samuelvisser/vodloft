import {useEffect, useState} from 'react'

/** How long work runs before what shows its progress appears. */
const SLOW_AFTER_MS = 600

/** Whether ``active`` work has been running a while: work that is done in a moment, such as a creator lookup that
 * was found already, would only flash its progress by, so it shows none. */
export function useSlow(active: boolean): boolean {
    const [slow, setSlow] = useState(false)
    useEffect(() => {
        if (!active) {
            setSlow(false)
            return
        }
        const timer = window.setTimeout(() => setSlow(true), SLOW_AFTER_MS)
        return () => window.clearTimeout(timer)
    }, [active])
    return active && slow
}
