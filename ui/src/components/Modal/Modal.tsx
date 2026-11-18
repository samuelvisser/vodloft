import type {CSSProperties, FormEventHandler, ReactNode} from 'react'
import {useDismissOnEscape} from './useDismissOnEscape'

type ModalProps = {
    children: ReactNode
    /** Closes the modal without doing anything, as its Cancel or Close button does. */
    onDismiss: () => void
    /** False while Escape would lose the person's unsaved work or break off a running action. */
    dismissOnEscape?: boolean
    dismissOnOverlayClick?: boolean
    className?: string
    labelledBy?: string
    describedBy?: string
    style?: CSSProperties
    /** A modal that is itself a form, such as a bulk change. */
    onSubmit?: FormEventHandler<HTMLFormElement>
}

/** A modal dialog over a dimmed page. Escape and a click beside it dismiss it, unless turned off. */
export default function Modal({
    children,
    onDismiss,
    dismissOnEscape = true,
    dismissOnOverlayClick = true,
    className = 'modal',
    labelledBy,
    describedBy,
    style,
    onSubmit,
}: ModalProps) {
    useDismissOnEscape(onDismiss, dismissOnEscape)

    const dialogProps = {
        className,
        role: 'dialog',
        'aria-modal': true,
        'aria-labelledby': labelledBy,
        'aria-describedby': describedBy,
        style,
        onClick: (event: {stopPropagation: () => void}) => event.stopPropagation(),
    } as const

    return (
        <div className="modal-overlay" role="presentation" onClick={dismissOnOverlayClick ? onDismiss : undefined}>
            {onSubmit
                ? <form {...dialogProps} onSubmit={onSubmit} noValidate>{children}</form>
                : <div {...dialogProps}>{children}</div>}
        </div>
    )
}
