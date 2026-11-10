import {type ReactNode, useEffect, useRef, useState} from 'react'

import './PathChangeList.css'

export type PathChange = {
    key: string | number
    /** The path a file has now. */
    from: string
    /** The path it gets; null when it has no new one, such as a file that stays where it is. */
    to: string | null
    /** Shown above the paths, such as the episode and what happens to it. */
    header?: ReactNode
    /** Shown in place of the new path when there is none. */
    toNote?: ReactNode
    /** Grays out a file that does not change, such as one that stays where it is. */
    muted?: boolean
}

const PAGE = 50

/** Where two paths first differ, so the rest of each can stand out. */
function splitAtDifference(left: string, right: string): number {
    let index = 0
    while (index < left.length && index < right.length && left[index] === right[index]) index += 1
    // Start at the folder or word the difference is in, so the highlight reads as whole names.
    const boundary = Math.max(left.lastIndexOf('/', index - 1), left.lastIndexOf(' ', index - 1))
    return boundary >= 0 ? boundary + 1 : 0
}

function PathPair({change, fromLabel, toLabel}: {change: PathChange, fromLabel: string, toLabel: string}) {
    const {from, to} = change
    const at = to === null ? from.length : splitAtDifference(from, to)
    return (
        <li className={`path-change${change.muted ? ' is-muted' : ''}`}>
            {change.header && <div className="path-change__header">{change.header}</div>}
            <span className="path-change__label">{fromLabel}</span>
            <code><span className="is-same">{from.slice(0, at)}</span>{from.slice(at)}</code>
            {(to !== null || change.toNote) && (
                <>
                    <span className="path-change__label">{toLabel}</span>
                    {to !== null
                        ? <code><span className="is-same">{to.slice(0, at)}</span><mark>{to.slice(at)}</mark></code>
                        : <span className="path-change__note">{change.toNote}</span>}
                </>
            )}
        </li>
    )
}

/**
 * Files with the path they have now and the one they get, the part that changes highlighted. An endless list
 * scrolls, and renders more as its end comes into view.
 */
export default function PathChangeList({changes, fromLabel, toLabel, endless = false}: {
    changes: readonly PathChange[]
    fromLabel: string
    toLabel: string
    endless?: boolean
}) {
    const [shown, setShown] = useState(PAGE)
    const list = useRef<HTMLUListElement | null>(null)
    const end = useRef<HTMLLIElement | null>(null)
    useEffect(() => {
        const sentinel = end.current
        if (!endless || !sentinel || shown >= changes.length) return
        const observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
                setShown((current) => Math.min(changes.length, current + PAGE))
            }
        }, {root: list.current, rootMargin: '200px'})
        observer.observe(sentinel)
        return () => observer.disconnect()
    }, [endless, shown, changes.length])
    const visible = endless ? changes.slice(0, shown) : changes
    return (
        <ul ref={list} className={`path-change-list${endless ? ' is-endless' : ''}`}>
            {visible.map((change) => <PathPair key={change.key} change={change} fromLabel={fromLabel} toLabel={toLabel}/>)}
            {endless && shown < changes.length && <li ref={end} className="path-change-list__end" aria-hidden="true"/>}
        </ul>
    )
}
