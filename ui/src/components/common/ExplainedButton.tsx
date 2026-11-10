import {type ButtonHTMLAttributes, useCallback, useId, useRef, useState} from 'react'
import AnchoredNote from './AnchoredNote'

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'disabled'> & {
    /** Why the button is not available right now. A button with a reason is disabled. */
    disabledReason?: string
}

/**
 * A button that, while it is not available, still answers a tap: it shows why instead of doing nothing.
 * A truly disabled button gets no taps at all, and touch screens never show its hover title.
 */
export default function ExplainedButton({disabledReason, onClick, className = '', children, ...props}: Props) {
    const [open, setOpen] = useState(false)
    const id = useId()
    const buttonRef = useRef<HTMLButtonElement>(null)
    const close = useCallback(() => setOpen(false), [])

    if (disabledReason === undefined) {
        return <button {...props} className={className} onClick={onClick}>{children}</button>
    }

    return (
        <>
            <button
                {...props}
                ref={buttonRef}
                className={`${className} is-disabled`.trim()}
                aria-disabled="true"
                aria-describedby={id}
                title={disabledReason}
                onClick={() => setOpen((value) => !value)}
            >
                {children}
            </button>
            {open
                ? <AnchoredNote id={id} anchorRef={buttonRef} onClose={close}>{disabledReason}</AnchoredNote>
                : <span id={id} hidden>{disabledReason}</span>}
        </>
    )
}
