import {type ReactNode, useEffect, useId, useRef, useState} from 'react'
import './DisabledReason.css'

export type DisabledReasonControl = {
    /** Points the unavailable control at its explanation. */
    describedBy?: string
    /** Shows or hides the explanation; call it when the unavailable control is tapped or clicked. */
    explain: () => void
}

type Props = {
    /** Why the control inside is not available right now. Without one, nothing is explained. */
    reason?: string
    /** Where the explanation appears: beside the control (above it on phones), or below it, lined up with its
     *  right edge (``below``) or its left edge (``below-start``). */
    placement: 'side' | 'below' | 'below-start'
    as?: 'div' | 'span'
    className?: string
    children: (control: DisabledReasonControl) => ReactNode
}

/**
 * Explains why a control is not available. The explanation shows while the pointer is over the
 * control or keyboard focus is on it, and a tap or click on the control shows it until the next tap
 * elsewhere. Touch screens have no hover, so the tap is what explains it there.
 */
export default function DisabledReason({reason, placement, as: Host = 'span', className = '', children}: Props) {
    const [shown, setShown] = useState(false)
    const hostRef = useRef<HTMLElement>(null)
    const id = useId()

    useEffect(() => {
        if (!reason) setShown(false)
    }, [reason])

    useEffect(() => {
        if (!shown) return

        const hideOnOutsidePointer = (event: PointerEvent) => {
            if (event.target instanceof Node && hostRef.current?.contains(event.target)) return
            setShown(false)
        }
        const hideOnEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setShown(false)
        }

        document.addEventListener('pointerdown', hideOnOutsidePointer)
        document.addEventListener('keydown', hideOnEscape)
        return () => {
            document.removeEventListener('pointerdown', hideOnOutsidePointer)
            document.removeEventListener('keydown', hideOnEscape)
        }
    }, [shown])

    const classes = [
        'vl-disabled-reason',
        `vl-disabled-reason--${placement}`,
        reason ? 'has-reason' : '',
        shown ? 'is-shown' : '',
        className,
    ].filter(Boolean).join(' ')

    return (
        <Host ref={hostRef as never} className={classes}>
            {children({
                describedBy: reason ? id : undefined,
                explain: () => setShown((value) => reason ? !value : false),
            })}
            {reason && (
                <span id={id} role="tooltip" className="vl-disabled-reason-tooltip">
                    {reason}
                </span>
            )}
        </Host>
    )
}
