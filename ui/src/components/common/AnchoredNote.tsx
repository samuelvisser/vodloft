import {type ReactNode, type RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react'
import {createPortal} from 'react-dom'
import './ProgressVisual.css'

type PopoverPosition = {
    top: number
    left: number
}

const POPOVER_GAP = 6
const VIEWPORT_GUTTER = 8
const POPOVER_WIDTH = 260

/**
 * A small note shown next to the button that opened it. It closes on Escape and on a tap anywhere
 * outside the button and the note.
 */
export default function AnchoredNote({id, anchorRef, onClose, children}: {
    id: string
    anchorRef: RefObject<HTMLElement | null>
    onClose: () => void
    children: ReactNode
}) {
    const [position, setPosition] = useState<PopoverPosition>({top: 0, left: 0})
    const popoverRef = useRef<HTMLSpanElement>(null)

    const positionPopover = useCallback(() => {
        const anchor = anchorRef.current
        const popover = popoverRef.current
        if (!anchor || !popover) return

        const anchorRect = anchor.getBoundingClientRect()
        const width = Math.min(POPOVER_WIDTH, window.innerWidth - VIEWPORT_GUTTER * 2)
        const left = Math.max(
            VIEWPORT_GUTTER,
            Math.min(anchorRect.right - width, window.innerWidth - width - VIEWPORT_GUTTER),
        )

        const below = anchorRect.bottom + POPOVER_GAP
        const above = anchorRect.top - popover.offsetHeight - POPOVER_GAP
        const top = below + popover.offsetHeight <= window.innerHeight - VIEWPORT_GUTTER || above < VIEWPORT_GUTTER
            ? below
            : above

        setPosition({top, left})
    }, [anchorRef])

    useLayoutEffect(() => {
        positionPopover()
    }, [children, positionPopover])

    useEffect(() => {
        const closeOnOutsidePointer = (event: PointerEvent) => {
            const target = event.target
            if (!(target instanceof Node)) return
            if (anchorRef.current?.contains(target) || popoverRef.current?.contains(target)) return
            onClose()
        }
        const closeOnEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose()
        }

        document.addEventListener('pointerdown', closeOnOutsidePointer)
        document.addEventListener('keydown', closeOnEscape)
        window.addEventListener('resize', positionPopover)
        window.addEventListener('scroll', positionPopover, true)
        return () => {
            document.removeEventListener('pointerdown', closeOnOutsidePointer)
            document.removeEventListener('keydown', closeOnEscape)
            window.removeEventListener('resize', positionPopover)
            window.removeEventListener('scroll', positionPopover, true)
        }
    }, [anchorRef, onClose, positionPopover])

    if (typeof document === 'undefined') return null

    return createPortal(
        <span
            id={id}
            ref={popoverRef}
            className="vl-progress-explanation-text"
            role="note"
            style={{top: position.top, left: position.left}}
        >
            {children}
        </span>,
        document.body,
    )
}
