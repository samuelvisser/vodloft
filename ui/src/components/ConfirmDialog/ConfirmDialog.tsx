import type {ReactNode} from 'react'
import {useEffect, useId, useRef, useState} from 'react'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

import './ConfirmDialog.css'

export type ConfirmDialogButton = {
    label: ReactNode
    onClick: () => void | Promise<void>
    icon?: IconProp
    iconSpin?: boolean
    className?: string
    disabled?: boolean
}

export type ConfirmDialogCancelButton = Omit<Partial<ConfirmDialogButton>, 'label'> & {
    label?: ReactNode
}

type ConfirmDialogProps = {
    open: boolean
    title: ReactNode
    children: ReactNode
    onDismiss: () => void
    icon?: IconProp
    iconTone?: 'default' | 'danger'
    confirmButton: ConfirmDialogButton
    secondaryButton?: ConfirmDialogButton
    showCancelButton?: boolean
    cancelButton?: ConfirmDialogCancelButton
    dismissOnOverlayClick?: boolean
    className?: string
}

export default function ConfirmDialog({
    open,
    title,
    children,
    onDismiss,
    icon,
    iconTone = 'default',
    confirmButton,
    secondaryButton,
    showCancelButton = true,
    cancelButton,
    dismissOnOverlayClick = true,
    className,
}: ConfirmDialogProps) {
    const autoId = useId()
    const titleId = `confirm-dialog-title-${autoId}`
    const descriptionId = `confirm-dialog-description-${autoId}`

    // While a button's async onClick is still running, every button is disabled and the
    // pressed one shows a spinner, so a slow request can't be started twice.
    const [pending, setPending] = useState<'confirm' | 'secondary' | 'cancel' | null>(null)
    const pendingRef = useRef(false)
    const mountedRef = useRef(true)
    useEffect(() => () => {
        mountedRef.current = false
    }, [])

    if (!open) return null

    const run = (which: 'confirm' | 'secondary' | 'cancel', onClick: () => void | Promise<void>) => {
        if (pendingRef.current) return
        const result = onClick()
        if (!(result instanceof Promise)) return
        pendingRef.current = true
        setPending(which)
        void result.finally(() => {
            pendingRef.current = false
            if (mountedRef.current) setPending(null)
        })
    }

    const busy = pending !== null
    const onOverlayClick = () => {
        if (dismissOnOverlayClick && !busy) onDismiss()
    }
    const onCancel = cancelButton?.onClick ?? onDismiss
    const spinnerIcon = faIcon('fass', 'spinner')

    return (
        <div className="modal-overlay" role="presentation" onClick={onOverlayClick}>
            <div
                className={['modal', className].filter(Boolean).join(' ')}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-describedby={descriptionId}
                onClick={(event) => event.stopPropagation()}
            >
                <div className="modal-header">
                    {icon && (
                        <div className={`modal-icon${iconTone === 'danger' ? ' danger' : ''}`} aria-hidden>
                            <FontAwesomeIcon icon={icon}/>
                        </div>
                    )}
                    <h2 id={titleId} className="modal-title">{title}</h2>
                </div>

                <div id={descriptionId} className="confirm-dialog-content">
                    {children}
                </div>

                <div className="modal-actions">
                    {showCancelButton && (
                        <button
                            type="button"
                            className={cancelButton?.className ?? 'btn'}
                            disabled={cancelButton?.disabled || busy}
                            onClick={() => run('cancel', onCancel)}
                        >
                            {pending === 'cancel' ? (
                                <FontAwesomeIcon icon={spinnerIcon} spin aria-hidden="true"/>
                            ) : cancelButton?.icon && (
                                <FontAwesomeIcon
                                    icon={cancelButton.icon}
                                    spin={cancelButton.iconSpin}
                                    aria-hidden="true"
                                />
                            )}
                            {cancelButton?.label ?? 'Cancel'}
                        </button>
                    )}
                    {secondaryButton && (
                        <button
                            type="button"
                            className={secondaryButton.className ?? 'btn'}
                            disabled={secondaryButton.disabled || busy}
                            onClick={() => run('secondary', secondaryButton.onClick)}
                        >
                            {pending === 'secondary' ? (
                                <FontAwesomeIcon icon={spinnerIcon} spin aria-hidden="true"/>
                            ) : secondaryButton.icon && (
                                <FontAwesomeIcon
                                    icon={secondaryButton.icon}
                                    spin={secondaryButton.iconSpin}
                                    aria-hidden="true"
                                />
                            )}
                            {secondaryButton.label}
                        </button>
                    )}
                    <button
                        type="button"
                        className={confirmButton.className ?? 'btn btn-primary'}
                        disabled={confirmButton.disabled || busy}
                        aria-busy={pending === 'confirm' || undefined}
                        onClick={() => run('confirm', confirmButton.onClick)}
                    >
                        {pending === 'confirm' ? (
                            <FontAwesomeIcon icon={spinnerIcon} spin aria-hidden="true"/>
                        ) : confirmButton.icon && (
                            <FontAwesomeIcon
                                icon={confirmButton.icon}
                                spin={confirmButton.iconSpin}
                                aria-hidden="true"
                            />
                        )}
                        {confirmButton.label}
                    </button>
                </div>
            </div>
        </div>
    )
}
