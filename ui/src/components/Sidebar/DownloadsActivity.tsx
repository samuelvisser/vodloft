import {useFrontendPuller} from '../../lib/puller'

/**
 * A quiet marker on the Downloads icon while a download, library or quick, is running: a faint
 * turning arc, or a still dot when the browser asks for reduced motion.
 * Queued downloads that have not started do not count.
 */
export default function DownloadsActivity() {
    const {data} = useFrontendPuller()
    const running = (data?.operations ?? []).some(
        (operation) => (operation.kind === 'media.download' || operation.kind === 'quick.download') && operation.status === 'RUNNING',
    )
    if (!running) return null

    return (
        <>
            {/* The span turns, not the svg: Safari on iPhone did not repaint a turning svg, so the arc stood
                still and only jumped now and then. A span gets its own layer that turns without repainting. */}
            <span className="nav-activity-ring" aria-hidden="true">
                <svg viewBox="0 0 28 28" focusable="false">
                    <circle cx="14" cy="14" r="13" />
                </svg>
            </span>
            <span className="nav-activity-dot" aria-hidden="true" />
        </>
    )
}
