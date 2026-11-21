import {useCallback, useEffect, useId, useLayoutEffect, useRef, useState} from 'react'
import {createPortal} from 'react-dom'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import './ProgressVisual.css'
import {faIcon} from '../../icons/faIcon'
import type {ProgressStep} from '../../types/progress'

const STEP_ICONS = {
    pending: faIcon('fass', 'circle'), running: faIcon('fass', 'spinner'), waiting: faIcon('fass', 'clock'),
    completed: faIcon('fass', 'circle-check'), skipped: faIcon('fass', 'ban'), failed: faIcon('fass', 'circle-xmark'),
    canceled: faIcon('fass', 'xmark'),
}
const STEP_STATES = {
    pending: 'To do', running: 'Running', waiting: 'Waiting', completed: 'Done', skipped: 'Skipped', failed: 'Failed',
    canceled: 'Canceled',
}

type PopoverPosition = {
    top: number
    left: number
}

const POPOVER_GAP = 6
const VIEWPORT_GUTTER = 8
const POPOVER_WIDTH = 260

export default function ProgressExplanation({detail, steps, buttonClassName = 'icon-btn'}: {
    detail: string
    /** The steps of the action's plan, listed under its detail. */
    steps?: ProgressStep[]
    buttonClassName?: string
}) {
    const [open, setOpen] = useState(false)
    const [position, setPosition] = useState<PopoverPosition>({top: 0, left: 0})
    const id = useId()
    const triggerRef = useRef<HTMLButtonElement>(null)
    const popoverRef = useRef<HTMLSpanElement>(null)

    const positionPopover = useCallback(() => {
        const trigger = triggerRef.current
        const popover = popoverRef.current
        if (!trigger || !popover) return

        const triggerRect = trigger.getBoundingClientRect()
        const width = Math.min(POPOVER_WIDTH, window.innerWidth - VIEWPORT_GUTTER * 2)
        const left = Math.max(
            VIEWPORT_GUTTER,
            Math.min(triggerRect.right - width, window.innerWidth - width - VIEWPORT_GUTTER),
        )

        const below = triggerRect.bottom + POPOVER_GAP
        const above = triggerRect.top - popover.offsetHeight - POPOVER_GAP
        const top = below + popover.offsetHeight <= window.innerHeight - VIEWPORT_GUTTER || above < VIEWPORT_GUTTER
            ? below
            : above

        setPosition({top, left})
    }, [])

    useLayoutEffect(() => {
        if (open) positionPopover()
    }, [detail, steps, open, positionPopover])

    useEffect(() => {
        if (!open) return

        const closeOnOutsidePointer = (event: PointerEvent) => {
            const target = event.target
            if (!(target instanceof Node)) return
            if (triggerRef.current?.contains(target) || popoverRef.current?.contains(target)) return
            setOpen(false)
        }
        const closeOnEscape = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return
            // Handled here, so a modal around it stays open.
            event.preventDefault()
            setOpen(false)
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
    }, [open, positionPopover])

    const popover = open && typeof document !== 'undefined'
        ? createPortal(
            <span
                id={id}
                ref={popoverRef}
                className="vl-progress-explanation-text"
                role="note"
                style={{top: position.top, left: position.left}}
            >
                {detail}
                {steps && steps.length > 1 && (
                    <span className="vl-progress-steps" role="list" aria-label="Steps">
                        {steps.map((step) => (
                            <span key={step.id} role="listitem" className={`vl-progress-step is-${step.state}`}>
                                <FontAwesomeIcon
                                    icon={STEP_ICONS[step.state]} spin={step.state === 'running'}
                                    aria-label={STEP_STATES[step.state]} fixedWidth
                                />
                                <span className="vl-progress-step-label">
                                    {step.label}
                                    {step.state === 'running' && step.count && (
                                        <small className="vl-progress-step-count">{step.count}</small>
                                    )}
                                </span>
                                {step.state === 'running' && step.percent != null && (
                                    <span className="vl-progress-step-percent">{step.percent}%</span>
                                )}
                            </span>
                        ))}
                    </span>
                )}
            </span>,
            document.body,
        )
        : null

    return <span className="vl-progress-explanation">
        <button
            ref={triggerRef}
            type="button"
            className={buttonClassName}
            aria-label="Progress details"
            aria-expanded={open}
            aria-controls={id}
            onClick={event => {
                event.stopPropagation()
                setOpen(value => !value)
            }}
        >
            <FontAwesomeIcon icon={faIcon('fass', 'circle-info')}/>
        </button>
        {popover}
    </span>
}
