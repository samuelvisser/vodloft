import type {CSSProperties, ReactNode} from 'react'
import {useId, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import DialogSwitch from './DialogSwitch'

import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import Modal from '../Modal/Modal'
import './LedgerModal.css'

/** A page of a log that loads more while it is scrolled, such as an infinite query's. */
export type LedgerPages<T> = {
    items: T[]
    isLoading: boolean
    isError: boolean
    hasNextPage: boolean
    isFetchingNextPage: boolean
    isFetchNextPageError: boolean
    fetchNextPage: () => unknown
}

type Column<T> = {
    header: string
    cell: (entry: T) => ReactNode
    className?: string
    /** Left out on a phone. */
    wideOnly?: boolean
}

/** The switch that leaves out what found nothing, such as a sync without new episodes. */
export type LedgerHideEmpty = {
    checked: boolean
    onChange: (checked: boolean) => void
    /** Names what stays, such as "Only syncs that found episodes". */
    label: string
}

type Props<T> = {
    open: boolean
    title: string
    subtitle: ReactNode
    icon: unknown
    /** Names what the log holds, such as "runs" or "syncs". */
    noun: string
    tableLabel: string
    pages: LedgerPages<T>
    columns: Column<T>[]
    /** The CSS grid columns of a row. */
    gridColumns: string
    rowKey: (entry: T) => string | number
    actions: ReactNode
    /** Left out, the log has nothing to hide and shows no switch. */
    hideEmpty?: LedgerHideEmpty
    onClose: () => void
    className?: string
}

/** A modal with a log of past runs that loads older ones while it is scrolled, and actions below it. */
export default function LedgerModal<T>({
    open, title, subtitle, icon, noun, tableLabel, pages, columns, gridColumns, rowKey, actions, hideEmpty, onClose, className,
}: Props<T>) {
    const titleId = useId()
    const {items, isFetchingNextPage: loadingMore, isFetchNextPageError: moreFailed} = pages
    const {rootRef, endRef} = useLoadMoreOnScroll<HTMLDivElement, HTMLDivElement>(
        open && pages.hasNextPage && !loadingMore && !moreFailed,
        () => void pages.fetchNextPage(),
    )

    if (!open) return null

    const rowClass = (column: Column<T>) => [column.className, column.wideOnly ? 'is-wide-only' : undefined].filter(Boolean).join(' ') || undefined
    return (
        <Modal
            onDismiss={onClose}
            className={`modal ledger-modal${className ? ` ${className}` : ''}`}
            labelledBy={titleId}
            style={{'--ledger-columns': gridColumns} as CSSProperties}
        >
            <div className="modal-header ledger-modal__header">
                <div className="modal-icon" aria-hidden>
                    <FontAwesomeIcon icon={icon as never}/>
                </div>
                <div>
                    <h2 id={titleId} className="modal-title">{title}</h2>
                    <div className="ledger-modal__subtitle">{subtitle}</div>
                </div>
            </div>

            {hideEmpty ? (
                <div className="ledger-modal__filters">
                    <DialogSwitch checked={hideEmpty.checked} onChange={hideEmpty.onChange} label={hideEmpty.label}/>
                </div>
            ) : null}

            <div className="ledger-modal__content" ref={rootRef}>
                {pages.isLoading ? (
                    <p className="modal-text">Loading the history...</p>
                ) : pages.isError && items.length === 0 ? (
                    <p className="modal-text">Could not load the history.</p>
                ) : items.length === 0 ? (
                    <p className="modal-text">
                        {hideEmpty?.checked ? `No ${noun} have found anything yet.` : `No ${noun} have been recorded yet.`}
                    </p>
                ) : (
                    <div className="ledger-modal__table" role="table" aria-label={tableLabel}>
                        <div className="ledger-modal__row ledger-modal__row--header" role="row">
                            {columns.map((column) => (
                                <span role="columnheader" key={column.header} className={column.wideOnly ? 'is-wide-only' : undefined}>
                                    {column.header}
                                </span>
                            ))}
                        </div>
                        {items.map((entry) => (
                            <div className="ledger-modal__row" role="row" key={rowKey(entry)}>
                                {columns.map((column) => (
                                    <span role="cell" key={column.header} className={rowClass(column)}>{column.cell(entry)}</span>
                                ))}
                            </div>
                        ))}
                    </div>
                )}
                {items.length > 0 && (
                    <div className="ledger-modal__more" ref={endRef} aria-live="polite">
                        {moreFailed ? (
                            <>
                                Could not load more {noun}.
                                <button type="button" className="btn" onClick={() => void pages.fetchNextPage()}>
                                    Try again
                                </button>
                            </>
                        ) : loadingMore ? `Loading more ${noun}…` : null}
                    </div>
                )}
            </div>

            <div className="ledger-modal__footer">
                <div className="modal-actions ledger-modal__actions">
                    <button type="button" className="btn" onClick={onClose}>Close</button>
                    {actions}
                </div>
            </div>
        </Modal>
    )
}

const HIDE_EMPTY_STORAGE_KEY = 'vodloft.ledger.hideEmpty'

function storedHideEmpty(): boolean {
    try {
        return window.localStorage.getItem(HIDE_EMPTY_STORAGE_KEY) === 'true'
    } catch {
        return false
    }
}

/** Whether task logs leave out what found nothing; each browser remembers the choice for every log. */
export function useLedgerHideEmpty(): [boolean, (checked: boolean) => void] {
    const [hideEmpty, setHideEmpty] = useState(storedHideEmpty)
    const change = (checked: boolean) => {
        setHideEmpty(checked)
        try {
            window.localStorage.setItem(HIDE_EMPTY_STORAGE_KEY, String(checked))
        } catch {
            // The choice then lasts until the page reloads.
        }
    }
    return [hideEmpty, change]
}

export function formatLedgerDate(value: string | null | undefined): string {
    if (!value) return '—'
    const normalized = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`
    return new Date(normalized).toLocaleString()
}
