import type {CSSProperties, ReactNode} from 'react'
import {useId} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
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
    onClose: () => void
    className?: string
}

/** A modal with a log of past runs that loads older ones while it is scrolled, and actions below it. */
export default function LedgerModal<T>({
    open, title, subtitle, icon, noun, tableLabel, pages, columns, gridColumns, rowKey, actions, onClose, className,
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
        <div className="modal-overlay" role="presentation" onClick={onClose}>
            <div
                className={`modal ledger-modal${className ? ` ${className}` : ''}`}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                onClick={(event) => event.stopPropagation()}
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

                <div className="ledger-modal__content" ref={rootRef}>
                    {pages.isLoading ? (
                        <p className="modal-text">Loading the history...</p>
                    ) : pages.isError && items.length === 0 ? (
                        <p className="modal-text">Could not load the history.</p>
                    ) : items.length === 0 ? (
                        <p className="modal-text">No {noun} have been recorded yet.</p>
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
            </div>
        </div>
    )
}

export function formatLedgerDate(value: string | null | undefined): string {
    if (!value) return '—'
    const normalized = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`
    return new Date(normalized).toLocaleString()
}
