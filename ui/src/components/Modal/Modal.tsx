import type {CSSProperties, FormEventHandler, ReactNode} from 'react'
import {InScrollingDialog} from './dialogMenus'
import {useDismissOnEscape} from './useDismissOnEscape'

type ModalProps = {
    children: ReactNode
    /** Closes the modal without doing anything, as its Cancel or Close button does. */
    onDismiss: () => void
    /** False while Escape would lose the person's unsaved work or break off a running action. */
    dismissOnEscape?: boolean
    dismissOnOverlayClick?: boolean
    /**
     * The dialog stays within the screen: its header and its buttons (``.modal-actions``) stay in place, and its
     * ``.modal-body`` scrolls when the content is taller than the screen. Turn it off only for a dialog that must grow
     * past the screen, such as one whose selects open their menus inside it.
     */
    scrollable?: boolean
    className?: string
    labelledBy?: string
    describedBy?: string
    style?: CSSProperties
    /** A modal that is itself a form, such as a bulk change. */
    onSubmit?: FormEventHandler<HTMLFormElement>
}

/** A modal dialog over a dimmed page, within the screen with its content scrolling between its header and buttons.
 * Escape and a click beside it dismiss it, unless turned off. */
export default function Modal({
    children,
    onDismiss,
    dismissOnEscape = true,
    dismissOnOverlayClick = true,
    scrollable = true,
    className = 'modal',
    labelledBy,
    describedBy,
    style,
    onSubmit,
}: ModalProps) {
    useDismissOnEscape(onDismiss, dismissOnEscape)

    const dialogProps = {
        className: scrollable ? className : `${className} modal-unbounded`,
        role: 'dialog',
        'aria-modal': true,
        'aria-labelledby': labelledBy,
        'aria-describedby': describedBy,
        style,
        onClick: (event: {stopPropagation: () => void}) => event.stopPropagation(),
    } as const

    return (
        <div className="modal-overlay" role="presentation" onClick={dismissOnOverlayClick ? onDismiss : undefined}>
            <InScrollingDialog.Provider value={scrollable}>
                {onSubmit
                    ? <form {...dialogProps} onSubmit={onSubmit} noValidate>{children}</form>
                    : <div {...dialogProps}>{children}</div>}
            </InScrollingDialog.Provider>
        </div>
    )
}
