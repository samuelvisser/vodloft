import {useCallback, useState, type ReactNode} from 'react'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'

/** The parts of the dialogs that say what numbering episodes again does: one framed row per thing it does, and the
 * episodes that get a new number. Their styles are in ChangeIdentificationDialog.css, under a dialog with the
 * change-identification-dialog class. */

export type IdentificationChange = {title: string; before: string; after: string}

// Shown before the list is opened up.
const EXAMPLES = 3
// Rows added each time the end of the opened list scrolls into view.
const PAGE = 50

/** A few episodes by their titles, which open up into a list of all of them, as ``ChangeList`` does. */
export function TitleList({titles, total}: {titles: string[], total: number}) {
    return <ChangeList changes={titles.map((title) => ({title, before: '', after: ''}))} total={total} titlesOnly/>
}

/** A few renumbered episodes, which open up into a list of all of them that renders more as it scrolls. */
export function ChangeList({changes, total = changes.length, titlesOnly = false}: {
    changes: IdentificationChange[]
    /** How many there are, when ``changes`` holds only the first of them. */
    total?: number
    titlesOnly?: boolean
}) {
    const [shown, setShown] = useState(EXAMPLES)
    const all = shown > EXAMPLES
    const more = useCallback(() => setShown((current) => Math.min(changes.length, current + PAGE)), [changes.length])
    const {rootRef, endRef} = useLoadMoreOnScroll<HTMLUListElement, HTMLLIElement>(all && shown < changes.length, more)
    return (
        <>
            <ul ref={rootRef} className={`change-identification-examples${all ? ' is-all' : ''}`}>
                {changes.slice(0, shown).map((change, index) => (
                    <li key={index} className={titlesOnly ? 'is-title-only' : undefined}>
                        {!titlesOnly && (
                            <>
                                <span className="change-identification-before">{change.before}</span>
                                <span className="change-identification-arrow" aria-label="becomes">→</span>
                                <b className="change-identification-after">{change.after}</b>
                            </>
                        )}
                        <span className="change-identification-title">{change.title}</span>
                    </li>
                ))}
                {all && shown < changes.length && (
                    <li ref={endRef} className="change-identification-end" role="status">
                        <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>
                        Loading more…
                    </li>
                )}
            </ul>
            {total > EXAMPLES && (all ? (
                <button type="button" className="change-identification-show-fewer" aria-expanded={true} onClick={() => setShown(EXAMPLES)}>
                    Show fewer
                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                </button>
            ) : (
                <button type="button" className="btn change-identification-show-all" aria-expanded={false} onClick={more}>
                    {total > changes.length ? `Show the newest ${changes.length.toLocaleString()}` : `Show all ${total.toLocaleString()}`}
                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                </button>
            ))}
        </>
    )
}

/** One thing the change does: an icon, what it is, and how many it touches. */
export function Step({icon, headline, detail, value, danger = false, children}: {
    /** How many it touches, or a word where that is not known yet, such as After. */
    icon: IconProp; headline: string; detail: ReactNode; value: number | string; danger?: boolean; children?: ReactNode
}) {
    return (
        <li className={`change-identification-step${danger ? ' is-danger' : ''}`}>
            <span className="change-identification-step-icon" aria-hidden="true"><FontAwesomeIcon icon={icon}/></span>
            <span className="change-identification-step-text">
                <b>{headline}</b>
                <span>{detail}</span>
            </span>
            <span className={`change-identification-step-count${typeof value === 'string' ? ' is-text' : ''}`}>
                {typeof value === 'number' ? value.toLocaleString() : value}
            </span>
            {children && <div className="change-identification-step-more">{children}</div>}
        </li>
    )
}

export function names(items: string[]) {
    if (items.length <= 1) return items.join('')
    return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}
