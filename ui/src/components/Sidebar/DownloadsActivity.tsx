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
            <svg className="nav-activity-ring" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
                <circle cx="14" cy="14" r="13" />
            </svg>
            <span className="nav-activity-dot" aria-hidden="true" />
        </>
    )
}
