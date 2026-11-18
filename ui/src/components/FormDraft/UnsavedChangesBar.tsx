import type {ReactNode} from 'react'

import './UnsavedChangesBar.css'

type Props = {
    title: string
    message: ReactNode
    /** The notice's buttons, such as Discard and the form's own save button. */
    children: ReactNode
}

/**
 * The bar at the bottom of a form with changes that are not saved yet, such as a draft restored from this browser,
 * with the form's Discard and Save buttons.
 */
export default function UnsavedChangesBar({title, message, children}: Props) {
    return (
        <div className="unsaved-changes-bar" role="status" aria-live="polite">
            <div>
                <strong>{title}</strong>
                <span>{message}</span>
            </div>
            <div className="unsaved-changes-bar__buttons">{children}</div>
        </div>
    )
}
