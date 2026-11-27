import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useLayoutEffect, useRef, type ReactNode} from 'react'
import './Notice.css'

/** The most lines a notice's text takes beside its action; longer, the action goes below the text. */
const LINES_BESIDE_ACTION = 2

/**
 * A message with an icon in a box, such as why media can't be downloaded, with an optional action, such as a button
 * to check again. The action stands beside the text while the text takes at most two lines there, and below it
 * otherwise. ``className`` gives the notice its colours, such as ``drm-notice``.
 */
export default function Notice({icon, action, className = '', children}: {
    icon: IconProp
    action?: ReactNode
    className?: string
    children: ReactNode
}) {
    const box = useRef<HTMLDivElement>(null)
    const text = useRef<HTMLSpanElement>(null)
    const hasAction = !!action

    useLayoutEffect(() => {
        const notice = box.current
        const message = text.current
        if (!hasAction || !notice || !message) return
        let width = -1
        const arrange = () => {
            if (notice.clientWidth === width) return
            width = notice.clientWidth
            // Measured beside the action, before the browser paints either way.
            notice.classList.remove('notice-stacked')
            const lineHeight = parseFloat(getComputedStyle(message).lineHeight) || 20
            const lines = Math.round(message.getBoundingClientRect().height / lineHeight)
            notice.classList.toggle('notice-stacked', lines > LINES_BESIDE_ACTION)
        }
        arrange()
        const observer = new ResizeObserver(arrange)
        observer.observe(notice)
        return () => observer.disconnect()
    }, [hasAction, children])

    return (
        <div ref={box} className={`notice ${className}`.trim()} role="status">
            <div className="notice-message">
                <FontAwesomeIcon icon={icon} aria-hidden="true"/>
                <span ref={text}>{children}</span>
            </div>
            {hasAction && <div className="notice-action">{action}</div>}
        </div>
    )
}
