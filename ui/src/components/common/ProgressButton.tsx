import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useEffect, useLayoutEffect, useRef, useState, type ReactNode} from 'react'
import {faIcon} from '../../icons/faIcon'

import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import type {FrontendOperationDefinition} from '../../lib/operationDefinitions'
import type {ProgressPresentation} from '../../types/progress'
import {presentOperationProgress} from '../../lib/operationProgress'
import {workingPresentation} from '../../lib/progressPresentation'
import ProgressFill from './ProgressFill'
import ProgressExplanation from './ProgressExplanation'
import './ProgressButton.css'

export type ProgressButtonRetryAction = {
    onClick: () => void
    disabled?: boolean
    label?: string
}

type ProgressButtonProps = {
    presentation?: ProgressPresentation
    definition: FrontendOperationDefinition
    resourceId?: number | null
    label: ReactNode
    icon?: IconProp
    onClick: () => void
    disabled?: boolean
    primary?: boolean
    className?: string
    starting?: boolean
    active?: boolean
    progress?: number
    activeLabel?: string
    ariaLabel?: string
    onCancel?: () => void
    cancelDisabled?: boolean
    cancelLabel?: string
    retry?: ProgressButtonRetryAction
}

// How long the outgoing surface stays on screen. It covers the longest animation in ProgressButton.css.
const SURFACE_TRANSITION_MS = 360
// Matches the width transition in ProgressButton.css.
const WIDTH_TRANSITION_MS = 220

type SurfaceTransition = {to: 'progress' | 'button'; leaving: ReactNode}

function prefersReducedMotion(): boolean {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function clampProgress(value: number | null | undefined): number {
    if (value == null || !Number.isFinite(value)) return 0
    return Math.max(0, Math.min(100, Math.round(value)))
}

export default function ProgressButton({
    definition,
    presentation,
    resourceId,
    label,
    icon,
    onClick,
    disabled = false,
    primary = true,
    className = '',
    starting = false,
    active = false,
    progress,
    activeLabel,
    ariaLabel,
    onCancel,
    cancelDisabled = false,
    cancelLabel,
    retry,
}: ProgressButtonProps) {
    // A missing resource ID means this button is managing its own aggregate state
    // instead of binding to an arbitrary active operation of the same kind.
    const operation = useActiveOperation(
        definition.kind,
        definition.resourceType,
        resourceId ?? null,
    )
    const resolved = presentation ?? presentOperationProgress(operation, starting)
        ?? (active ? workingPresentation('Working') : undefined)
    const isActive = resolved?.active ?? false
    const resolvedProgress = resolved?.percent ?? clampProgress(progress)
    const resolvedActiveLabel = resolved?.compactLabel ?? resolved?.label ?? activeLabel ?? `${resolvedProgress}%`
    const showCancel = isActive && onCancel !== undefined
    const controls = Number(Boolean(retry)) + Number(showCancel)
    const rootClassName = [
        'progress-button-root',
        primary ? 'is-primary' : '',
        isActive ? 'is-progress' : '',
        controls > 0 ? 'has-controls' : '',
        controls > 1 ? 'has-multiple-controls' : '',
        className,
    ].filter(Boolean).join(' ')
    const surfaceClassName = `btn${primary ? ' btn-primary' : ''} progress-button`
    const accessibleLabel = ariaLabel || definition.label
    // Keep the action's name visible while it runs, so a status like
    // "Queued…" or "32%" still says which action it belongs to.
    const title = typeof label === 'string' ? label : definition.label

    const buttonContent = <>{icon && <FontAwesomeIcon icon={icon}/>}{label}</>
    const progressContent = <>
        {resolved && <ProgressFill presentation={resolved} className="progress-button-fill"/>}
        <span className="progress-button-title" aria-hidden="true">{title}</span>
        <span className="progress-button-label">{resolved?.mode !== 'determinate' && resolved && <FontAwesomeIcon className="vl-progress-icon" icon={resolved.icon}/>} {resolvedActiveLabel}</span>
    </>
    const progressSurfaceClassName = `${surfaceClassName} is-progress-surface`

    // The button and the progress bar are different elements, so the one that goes away is kept
    // as an inert copy for a moment while the new one animates in over it.
    const [transition, setTransition] = useState<SurfaceTransition | null>(null)
    const [shownActive, setShownActive] = useState(isActive)
    const committed = useRef({button: buttonContent, progress: progressContent})
    if (shownActive !== isActive) {
        setShownActive(isActive)
        setTransition(prefersReducedMotion() ? null : {
            to: isActive ? 'progress' : 'button',
            leaving: isActive
                ? <span className={`${surfaceClassName} is-leaving`} aria-hidden="true">{committed.current.button}</span>
                : <span className={`${progressSurfaceClassName} is-leaving`} aria-hidden="true">{committed.current.progress}</span>,
        })
    }
    useLayoutEffect(() => {
        committed.current = {button: buttonContent, progress: progressContent}
    })
    useEffect(() => {
        if (!transition) return
        const timer = window.setTimeout(() => setTransition(null), SURFACE_TRANSITION_MS)
        return () => window.clearTimeout(timer)
    }, [transition])

    // The progress bar is often wider than the button. Grow and shrink between the two widths
    // instead of jumping.
    const rootRef = useRef<HTMLSpanElement>(null)
    const lastWidth = useRef<number | null>(null)
    const resizing = useRef(false)
    useLayoutEffect(() => {
        const root = rootRef.current
        if (!root || !transition) return
        const from = lastWidth.current
        const to = root.getBoundingClientRect().width
        lastWidth.current = to
        if (from == null || Math.abs(from - to) < 1) return
        const reset = () => {
            resizing.current = false
            delete root.dataset.resizing
            root.style.transition = ''
            root.style.width = ''
            root.style.minWidth = ''
        }
        resizing.current = true
        // Keeps the contents on one line while the width is in between.
        root.dataset.resizing = ''
        root.style.minWidth = '0'
        root.style.width = `${from}px`
        void root.offsetWidth
        root.style.transition = `width ${WIDTH_TRANSITION_MS}ms cubic-bezier(.2, .8, .2, 1)`
        root.style.width = `${to}px`
        const timer = window.setTimeout(reset, WIDTH_TRANSITION_MS)
        return () => {
            window.clearTimeout(timer)
            reset()
        }
    }, [transition])
    useEffect(() => {
        const root = rootRef.current
        if (!root || typeof ResizeObserver === 'undefined') return
        const observer = new ResizeObserver(() => {
            if (!resizing.current) lastWidth.current = root.getBoundingClientRect().width
        })
        observer.observe(root)
        return () => observer.disconnect()
    }, [])

    const enteringClassName = transition ? ' is-entering' : ''

    return (
        <span className="vl-progress-with-details download-progress">
        <span ref={rootRef} className={`${rootClassName}${transition ? ` is-entering-${transition.to}` : ''}`}>
            {transition?.leaving}
            {isActive ? (
                <span
                    className={`${progressSurfaceClassName}${enteringClassName}`}
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={resolved?.mode === 'determinate' ? resolvedProgress : undefined}
                    aria-valuetext={resolved?.detail}
                    aria-label={`${accessibleLabel}: ${resolvedActiveLabel}`}
                >
                    {progressContent}
                </span>
            ) : (
                <button
                    type="button"
                    className={`${surfaceClassName}${enteringClassName}`}
                    onClick={onClick}
                    disabled={disabled}
                    aria-label={ariaLabel}
                >
                    {buttonContent}
                </button>
            )}

            {controls > 0 && (
                <span className="progress-button-controls">
                    {retry && (
                        <button
                            type="button"
                            className="progress-button-control"
                            onClick={retry.onClick}
                            disabled={retry.disabled}
                            title={retry.label || `Retry ${definition.label.toLocaleLowerCase()}`}
                            aria-label={retry.label || `Retry ${definition.label.toLocaleLowerCase()}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'rotate-right')}/>
                        </button>
                    )}
                    {showCancel && (
                        <button
                            type="button"
                            className="progress-button-control is-cancel"
                            onClick={onCancel}
                            disabled={cancelDisabled}
                            title={cancelLabel || `Cancel ${definition.label.toLocaleLowerCase()}`}
                            aria-label={cancelLabel || `Cancel ${definition.label.toLocaleLowerCase()}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                        </button>
                    )}
                </span>
            )}
        </span>
        {isActive && resolved && <ProgressExplanation detail={resolved.detail}/>}
        </span>
    )
}
