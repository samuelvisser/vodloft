import ProgressExplanation from '../common/ProgressExplanation'
import type {TaskOperationRead} from '../../types/schemas/operation'
import type {ProgressPresentation} from '../../types/progress'
import {presentOperationProgress} from '../../lib/operationProgress'
import DownloadProgressActionItem from '../DownloadProgress/DownloadProgressActionItem'
import ProgressFill from '../common/ProgressFill'
import DisabledReason from '../common/DisabledReason'
import {useEffect, useId, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import './ActionMenu.css'
import {faIcon} from '../../icons/faIcon'

export type ActionMenuControl = {
    label: string
    icon: any
    onSelect: () => void
    disabled?: boolean
    tone?: 'default' | 'danger'
}

export type ActionMenuItem = {
    label: string
    icon?: any
    disabled?: boolean
    disabledReason?: string
    progress?: number
    operation?: TaskOperationRead
    /** The action's request is on its way and its operation does not exist yet. */
    starting?: boolean
    presentation?: ProgressPresentation
    controls?: ActionMenuControl[]
    tone?: 'default' | 'danger'
    separatorBefore?: boolean
} & (
    | { onSelect: () => void, href?: never }
    /** An item that opens a page renders as a link, so it can also be opened in a new tab. */
    | { href: string, onSelect?: never }
)

type Props = {
    label?: string
    items: ActionMenuItem[]
    className?: string
}

function normalizedProgress(value: number | undefined) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
    return Math.max(0, Math.min(100, Math.round(value)))
}

export default function ActionMenu({label = 'Actions', items, className = ''}: Props) {
    const [open, setOpen] = useState(false)
    const rootRef = useRef<HTMLDivElement>(null)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const menuId = useId()

    useEffect(() => {
        if (!open) return

        const onPointerDown = (event: PointerEvent) => {
            const root = rootRef.current
            if (root && !root.contains(event.target as Node)) setOpen(false)
        }

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return
            setOpen(false)
            triggerRef.current?.focus()
        }

        document.addEventListener('pointerdown', onPointerDown)
        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('pointerdown', onPointerDown)
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [open])

    const selectItem = (item: ActionMenuItem, explain?: () => void) => {
        if (item.disabled || item.starting) {
            explain?.()
            return
        }
        setOpen(false)
        item.onSelect?.()
    }

    const selectControl = (control: ActionMenuControl) => {
        if (control.disabled) return
        setOpen(false)
        control.onSelect()
    }

    if (items.length === 0) return null

    return (
        <div ref={rootRef} className={`action-menu${open ? ' is-open' : ''}${className ? ` ${className}` : ''}`}>
            <div className="action-menu-inline-items" role="group" aria-label={label}>
                {items.map((item, index) => item.href && !item.disabled ? (
                    <Link
                        key={`${item.label}-${index}`}
                        to={item.href}
                        className={`action-menu-item-control${item.tone === 'danger' ? ' is-danger' : ''}`}
                        aria-label={item.label}
                        title={item.label}
                    >
                        {item.icon
                            ? <FontAwesomeIcon icon={item.icon} aria-hidden="true"/>
                            : <span>{item.label}</span>}
                    </Link>
                ) : (
                    <button
                        key={`${item.label}-${index}`}
                        type="button"
                        className={`action-menu-item-control${item.tone === 'danger' ? ' is-danger' : ''}`}
                        aria-label={item.label}
                        title={item.label}
                        disabled={item.disabled}
                        onClick={() => selectItem(item)}
                    >
                        {item.icon
                            ? <FontAwesomeIcon icon={item.icon} aria-hidden="true"/>
                            : <span>{item.label}</span>}
                    </button>
                ))}
            </div>

            <button
                ref={triggerRef}
                type="button"
                className="btn btn-secondary action-menu-trigger"
                aria-haspopup="menu"
                aria-expanded={open}
                aria-controls={menuId}
                onClick={() => setOpen((value) => !value)}
            >
                <span>{label}</span>
                <FontAwesomeIcon className="action-menu-caret" icon={faIcon('fass', 'chevron-down')} aria-hidden="true"/>
            </button>

            {open && (
                <>
                    <div className="action-menu-backdrop" aria-hidden="true" onClick={() => setOpen(false)}/>
                    <div id={menuId} className="action-menu-popover" role="menu" aria-label={label}>
                        {items.map((item, index) => {
                            const progress = normalizedProgress(item.progress)
                            const presentation = item.presentation ?? presentOperationProgress(item.operation, item.starting)
                            const itemContent = (
                                <>
                                    {item.icon && (
                                        <FontAwesomeIcon className="action-menu-item-icon" icon={item.icon} aria-hidden="true"/>
                                    )}
                                    <span>{item.label}</span>
                                    {presentation && <DownloadProgressActionItem presentation={presentation}/>}
                                </>
                            )

                            return (
                                <DisabledReason
                                    key={`${item.label}-${index}`}
                                    as="div"
                                    placement="side"
                                    className="action-menu-entry"
                                    reason={item.disabled ? item.disabledReason : undefined}
                                >
                                    {({describedBy, explain}) => (
                                        <>
                                            {item.separatorBefore && <div className="action-menu-separator" role="separator"/>}
                                            <div className="action-menu-item-row">
                                                {presentation ? (
                                                    <ProgressFill
                                                        presentation={presentation}
                                                        className="action-menu-item-progress"
                                                    />
                                                ) : progress !== undefined && (
                                                    <span
                                                        className="action-menu-item-progress"
                                                        style={{width: `${progress}%`}}
                                                        aria-hidden="true"
                                                    />
                                                )}
                                                {item.href && !item.disabled ? (
                                                    <Link
                                                        to={item.href}
                                                        role="menuitem"
                                                        className={`action-menu-item${item.tone === 'danger' ? ' is-danger' : ''}`}
                                                        aria-label={presentation ? `${item.label}: ${presentation.detail}` : item.label}
                                                        onClick={() => setOpen(false)}
                                                    >
                                                        {itemContent}
                                                    </Link>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        role="menuitem"
                                                        className={`action-menu-item${item.tone === 'danger' ? ' is-danger' : ''}${item.disabled ? ' is-disabled' : ''}`}
                                                        aria-disabled={item.disabled || undefined}
                                                        aria-describedby={describedBy}
                                                        aria-label={presentation ? `${item.label}: ${presentation.detail}` : item.label}
                                                        onClick={() => selectItem(item, explain)}
                                                    >
                                                        {itemContent}
                                                    </button>
                                                )}
                                                {presentation && (
                                                    <ProgressExplanation
                                                        detail={presentation.detail}
                                                        buttonClassName="action-menu-item-control"
                                                    />
                                                )}
                                                {!!item.controls?.length && (
                                                    <div className="action-menu-item-controls" aria-label={`${item.label} task controls`}>
                                                        {item.controls.map((control) => (
                                                            <button
                                                                key={control.label}
                                                                type="button"
                                                                className={`action-menu-item-control${control.tone === 'danger' ? ' is-danger' : ''}`}
                                                                aria-label={control.label}
                                                                title={control.label}
                                                                disabled={control.disabled}
                                                                onClick={() => selectControl(control)}
                                                            >
                                                                <FontAwesomeIcon icon={control.icon} aria-hidden="true"/>
                                                            </button>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </>
                                    )}
                                </DisabledReason>
                            )
                        })}
                    </div>
                </>
            )}
        </div>
    )
}
