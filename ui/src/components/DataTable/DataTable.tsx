import {CSSProperties, HTMLAttributes, ReactNode, useId, useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {Link, useNavigate} from 'react-router-dom'
import {faIcon} from '../../icons/faIcon'
import {linkAreaHandlers} from '../../lib/linkClicks'

export type Column<T> = {
    id?: string
    header: ReactNode
    accessor?: keyof T | ((row: T) => ReactNode)
    cell?: (row: T) => ReactNode
    width?: number | string
    align?: 'left' | 'right' | 'center'
    headerStyle?: CSSProperties
    cellStyle?: CSSProperties
    dataLabel?: string
    /** Hide this column from the expanded mobile details (usually the title shown in mobileSummary). */
    mobileHidden?: boolean
    /** When set, the column header becomes clickable and sorts rows by this value. */
    sortAccessor?: (row: T) => string | number | Date | null | undefined
}

type SortDirection = 'asc' | 'desc'
type SortState = { id: string; direction: SortDirection }

function compareSortValues(a: string | number | Date, b: string | number | Date): number {
    if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime()
    if (typeof a === 'number' && typeof b === 'number') return a - b
    return String(a).localeCompare(String(b), undefined, {sensitivity: 'base', numeric: true})
}

export type DataTableAction<T> = {
    icon: IconProp
    text: string
    classes?: string
} & (
    | { onClick: (row: T) => void, href?: never }
    /** An action that opens a page renders as a link, so it can also be opened in a new tab. */
    | { href: string, onClick?: never }
)

export type DataTableProps<T> = {
    columns: Column<T>[]
    data?: T[]
    loading?: boolean
    error?: unknown
    ariaLabel: string
    loadingMessage?: ReactNode
    emptyMessage?: ReactNode
    rowKey: (row: T) => string | number
    /** The page a row opens. Clicking the row opens it; middle-click or ctrl/cmd-click opens it in a new tab. */
    rowHref?: (row: T) => string | undefined
    rowAriaLabel?: (row: T) => string
    getRowProps?: (row: T) => HTMLAttributes<HTMLTableRowElement>
    className?: string
    wrapperClassName?: string
    actions?: (row: T) => DataTableAction<T>[]
    /** Compact, always-visible content at the top of each mobile accordion card. */
    mobileSummary?: (row: T) => ReactNode
    /** Adds a mobile-only action that opens rowHref after the card is expanded. */
    mobileRowActionLabel?: string
    /** Bulk edit: a checkbox on every row, and clicking a row selects it instead of opening it. */
    selection?: DataTableSelection
}

export type DataTableSelection = {
    isSelected: (key: string) => boolean
    onToggle: (key: string) => void
    /** The header checkbox, for every row the filters match. */
    allState: 'none' | 'some' | 'all'
    onToggleAll: () => void
}

/** A click on a control inside a row, such as an Enabled switch, works the control and leaves the selection alone. */
function isControlClick(target: EventTarget | null) {
    return target instanceof Element && !!target.closest('a, button, input, select, textarea, label, [role="switch"], .react-switch-bg, .react-switch-handle')
}

function SelectCheckbox({checked, indeterminate = false, label, onChange}: {
    checked: boolean
    indeterminate?: boolean
    label: string
    onChange: () => void
}) {
    return (
        <input
            type="checkbox"
            className="bulk-check"
            aria-label={label}
            checked={checked}
            ref={(element) => { if (element) element.indeterminate = indeterminate }}
            onChange={onChange}
            onClick={(event) => event.stopPropagation()}
        />
    )
}

export function DataTable<T>(props: DataTableProps<T>) {
    const {
        columns,
        data,
        loading,
        error,
        ariaLabel,
        loadingMessage = 'Loading... ',
        emptyMessage = 'No data found',
        rowKey,
        rowAriaLabel,
        getRowProps,
        className,
        wrapperClassName,
        mobileSummary,
        mobileRowActionLabel,
        selection,
    } = props
    // Bulk edit replaces opening a row and its own actions.
    const actions = selection ? undefined : props.actions
    const rowHref = selection ? undefined : props.rowHref

    const navigate = useNavigate()
    const tableId = useId().replace(/:/g, '')
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())

    const colSpan = (columns.length + (actions ? 1 : 0) + (selection ? 1 : 0)) || 1

    const [sortState, setSortState] = useState<SortState | null>(null)
    const toggleSort = (id: string) => {
        setSortState((prev) => {
            if (!prev || prev.id !== id) return {id, direction: 'asc'}
            if (prev.direction === 'asc') return {id, direction: 'desc'}
            return null
        })
    }

    const sortedData = useMemo(() => {
        if (!data || !sortState) return data
        const col = columns.find((c, idx) => (c.id ?? String(idx)) === sortState.id)
        const accessor = col?.sortAccessor
        if (!accessor) return data
        const dir = sortState.direction === 'asc' ? 1 : -1
        return [...data].sort((rowA, rowB) => {
            const a = accessor(rowA)
            const b = accessor(rowB)
            const aEmpty = a === null || a === undefined
            const bEmpty = b === null || b === undefined
            if (aEmpty && bEmpty) return 0
            if (aEmpty) return 1
            if (bEmpty) return -1
            return compareSortValues(a, b) * dir
        })
    }, [data, sortState, columns])

    const cellContent = (column: Column<T>, row: T): ReactNode =>
        column.cell
            ? column.cell(row)
            : typeof column.accessor === 'function'
                ? column.accessor(row)
                : column.accessor
                    ? (row as any)[column.accessor as any]
                    : null

    const toggleMobileRow = (key: string) => {
        setExpandedRows((previous) => {
            const next = new Set(previous)
            if (next.has(key)) next.delete(key)
            else next.add(key)
            return next
        })
    }

    const renderMobileMessage = () => {
        if (loading && (!sortedData || sortedData.length === 0)) return loadingMessage
        if (!sortedData || sortedData.length === 0) return (error as any)?.message ?? emptyMessage
        return null
    }

    return (
        <div className={wrapperClassName ?? 'table-wrapper'}>
            <table className={`${className ?? 'table'} desktop-data-table`} aria-label={ariaLabel}>
                <thead>
                <tr>
                    {selection && (
                        <th scope="col" className="bulk-check-cell">
                            <SelectCheckbox
                                label="Select every matching profile"
                                checked={selection.allState === 'all'}
                                indeterminate={selection.allState === 'some'}
                                onChange={selection.onToggleAll}
                            />
                        </th>
                    )}
                    {columns.map((c, idx) => {
                        const id = c.id ?? String(idx)
                        const style: CSSProperties = {
                            width: c.width,
                            textAlign: c.align,
                            ...c.headerStyle,
                        }
                        if (!c.sortAccessor) {
                            return (
                                <th key={id} scope="col" style={style}>
                                    {c.header}
                                </th>
                            )
                        }
                        const isSorted = sortState?.id === id
                        const direction = isSorted ? sortState!.direction : undefined
                        const sortIcon = direction === 'asc' ? (faIcon('fass', 'sort-up')) : direction === 'desc' ? (faIcon('fass', 'sort-down')) : (faIcon('fass', 'sort'))
                        return (
                            <th key={id} scope="col" style={style} aria-sort={direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'}>
                                <button type="button" className="th-sort-btn" onClick={() => toggleSort(id)}>
                                    <span>{c.header}</span>
                                    <FontAwesomeIcon className="th-sort-icon" icon={sortIcon as any}/>
                                </button>
                            </th>
                        )
                    })}
                    {actions && (
                        <th key="actions" scope="col" style={{width: 100, textAlign: 'right'}}>Actions</th>
                    )}
                </tr>
                </thead>
                <tbody>
                {loading && (!sortedData || sortedData.length === 0) ? (
                    <tr>
                        <td colSpan={colSpan}>{loadingMessage}</td>
                    </tr>
                ) : !sortedData || sortedData.length === 0 ? (
                    <tr>
                        <td colSpan={colSpan}>{(error as any)?.message ?? emptyMessage}</td>
                    </tr>
                ) : (
                    sortedData.map((row) => {
                        const href = rowHref?.(row)
                        const rowKeyValue = String(rowKey(row))
                        const externalProps = getRowProps ? getRowProps(row) : {}
                        const rowProps: HTMLAttributes<HTMLTableRowElement> = {...externalProps}
                        if (href) {
                            const linkHandlers = linkAreaHandlers(href, navigate)
                            rowProps.tabIndex = rowProps.tabIndex ?? 0
                            rowProps.style = {cursor: 'pointer', ...(rowProps.style || {})}
                            rowProps.onClick = (e) => {
                                // Preserve any external onClick
                                externalProps.onClick?.(e)
                                linkHandlers.onClick(e)
                            }
                            rowProps.onMouseDown = (e) => {
                                externalProps.onMouseDown?.(e)
                                linkHandlers.onMouseDown(e)
                            }
                            rowProps.onAuxClick = (e) => {
                                externalProps.onAuxClick?.(e)
                                linkHandlers.onAuxClick(e)
                            }
                            rowProps.onKeyDown = (e) => {
                                if (e.target !== e.currentTarget) return
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    navigate(href)
                                }
                            }
                        }
                        const aria = rowAriaLabel?.(row)
                        if (aria) (rowProps as any)['aria-label'] = aria
                        const selected = selection?.isSelected(rowKeyValue) ?? false
                        if (selection) {
                            rowProps.onClick = (event) => {
                                if (!isControlClick(event.target)) selection.onToggle(rowKeyValue)
                            }
                            rowProps.style = {cursor: 'pointer', ...(rowProps.style || {})}
                            rowProps.className = [rowProps.className, 'bulk-row', selected && 'is-selected'].filter(Boolean).join(' ')
                            rowProps['aria-selected'] = selected
                        }

                        return (
                            <tr key={rowKeyValue} {...rowProps}>
                                {selection && (
                                    <td className="bulk-check-cell">
                                        <SelectCheckbox
                                            label={`Select ${aria ?? 'profile'}`}
                                            checked={selected}
                                            onChange={() => selection.onToggle(rowKeyValue)}
                                        />
                                    </td>
                                )}
                                {columns.map((c, idx) => {
                                    const content = cellContent(c, row)
                                    const style: CSSProperties = {
                                        textAlign: c.align,
                                        ...c.cellStyle,
                                    }
                                    return (
                                        <td key={(c.id ?? String(idx)) + '-cell'} style={style} data-label={c.dataLabel ?? String(c.header)}>
                                            {content}
                                        </td>
                                    )
                                })}
                                {actions && (
                                    <td key={'actions-cell'} style={{textAlign: 'right'}} data-label={'Actions'}>
                                        <div style={{display: 'inline-flex', gap: 6, flexWrap: 'wrap'}}>
                                            {actions(row).map((a, i) => a.href ? (
                                                <Link
                                                    key={i}
                                                    to={a.href}
                                                    className="icon-btn"
                                                    aria-label={`${a.text}${rowAriaLabel ? ' ' + (rowAriaLabel(row) ?? '') : ''}`}
                                                    title={a.text}
                                                >
                                                    <FontAwesomeIcon icon={a.icon}/>
                                                </Link>
                                            ) : (
                                                <button
                                                    key={i}
                                                    type="button"
                                                    className="icon-btn"
                                                    aria-label={`${a.text}${rowAriaLabel ? ' ' + (rowAriaLabel(row) ?? '') : ''}`}
                                                    title={a.text}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        a.onClick?.(row)
                                                    }}
                                                >
                                                    <FontAwesomeIcon icon={a.icon}/>
                                                </button>
                                            ))}
                                        </div>
                                    </td>
                                )}
                            </tr>
                        )
                    })
                )}
                </tbody>
            </table>

            <div className="mobile-data-list" role="list" aria-label={ariaLabel}>
                {renderMobileMessage() ? (
                    <div className="mobile-data-message">{renderMobileMessage()}</div>
                ) : (
                    sortedData?.map((row, rowIndex) => {
                        const rowKeyValue = String(rowKey(row))
                        const isExpanded = expandedRows.has(rowKeyValue)
                        const detailsId = `${tableId}-details-${rowIndex}`
                        const rowActions = actions?.(row) ?? []
                        const href = rowHref?.(row)

                        const showRowAction = Boolean(mobileRowActionLabel && href)

                        return (
                            <article
                                className={`mobile-data-card${isExpanded ? ' is-expanded' : ''}${selection ? ' bulk-card' : ''}${selection?.isSelected(rowKeyValue) ? ' is-selected' : ''}`}
                                role="listitem"
                                key={rowKeyValue}
                            >
                                {selection && (
                                    // The card's own button selects it; this box only shows that it is.
                                    <span className="bulk-card-check" aria-hidden="true" onClick={() => selection.onToggle(rowKeyValue)}>
                                        <input type="checkbox" className="bulk-check" tabIndex={-1} readOnly checked={selection.isSelected(rowKeyValue)}/>
                                    </span>
                                )}
                                <button
                                    type="button"
                                    className="mobile-data-summary"
                                    aria-expanded={selection ? undefined : isExpanded}
                                    aria-controls={selection ? undefined : detailsId}
                                    aria-label={rowAriaLabel ? (selection ? `Select ${rowAriaLabel(row)}` : `${rowAriaLabel(row)} details`) : undefined}
                                    aria-pressed={selection ? selection.isSelected(rowKeyValue) : undefined}
                                    onClick={() => selection ? selection.onToggle(rowKeyValue) : toggleMobileRow(rowKeyValue)}
                                >
                                    <span className="mobile-data-summary-content">
                                        {mobileSummary ? mobileSummary(row) : cellContent(columns[0], row)}
                                    </span>
                                    <FontAwesomeIcon
                                        className="mobile-data-chevron"
                                        icon={(isExpanded ? faIcon('fass', 'chevron-up') : faIcon('fass', 'chevron-down')) as IconProp}
                                        aria-hidden="true"
                                    />
                                </button>

                                {isExpanded && !selection && (
                                    <div className="mobile-data-details" id={detailsId}>
                                        {columns.filter((column) => !column.mobileHidden).map((column, columnIndex) => (
                                            <div className="mobile-data-detail-row" key={(column.id ?? String(columnIndex)) + '-mobile'}>
                                                <span className="mobile-data-detail-label">
                                                    {column.dataLabel ?? column.header}
                                                </span>
                                                <div className="mobile-data-detail-value">
                                                    {cellContent(column, row)}
                                                </div>
                                            </div>
                                        ))}

                                        {(showRowAction || rowActions.length > 0) && (
                                            <div className="mobile-data-detail-row mobile-data-actions-row">
                                                <span className="mobile-data-detail-label">Actions</span>
                                                <div className="mobile-data-actions">
                                                    {showRowAction && href && (
                                                        <Link to={href} className="btn">
                                                            {mobileRowActionLabel}
                                                        </Link>
                                                    )}
                                                    {rowActions.map((action, actionIndex) => action.href ? (
                                                        <Link key={actionIndex} to={action.href} className={action.classes ?? 'btn'}>
                                                            {action.text}
                                                        </Link>
                                                    ) : (
                                                        <button
                                                            key={actionIndex}
                                                            type="button"
                                                            className={action.classes ?? 'btn'}
                                                            onClick={() => action.onClick?.(row)}
                                                        >
                                                            {action.text}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </article>
                        )
                    })
                )}
            </div>
        </div>
    )
}

export default DataTable
