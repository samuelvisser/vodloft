import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import {presentDownloadProgress} from '../../lib/downloadProgress'
import {useControlOperation} from '../../lib/operations'
import {
    clearQuickDownloadHistory,
    quickDownloadFileUrl,
    quickDownloadHistoryQueryKey,
    quickDownloadsQueryKey,
    removeQuickDownload,
} from '../../lib/quickDownloads'
import {formatBytes} from '../../utils/formatting'
import type {TaskOperationRead} from '../../types/schemas/operation'
import type {QuickDownloadHistoryEntry, QuickDownloadReady} from '../../types/schemas/quick_download'
import ProgressBar from '../common/ProgressBar'
import SourceBadge from '../Source/SourceBadge'

function untilLabel(until: Date, now: number): string {
    const minutes = Math.max(0, Math.round((until.getTime() - now) / 60_000))
    if (minutes < 1) return 'in a moment'
    if (minutes < 60) return `in ${minutes} min`
    const hours = Math.round(minutes / 60)
    return `in ${hours} h`
}

function useNow(intervalMs = 30_000): number {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
        return () => window.clearInterval(timer)
    }, [intervalMs])
    return now
}

export function QuickInProgressList({operations}: {operations: TaskOperationRead[]}) {
    const control = useControlOperation()
    const [busy, setBusy] = useState<string | null>(null)
    if (!operations.length) return null

    const cancel = async (operation: TaskOperationRead) => {
        setBusy(operation.id)
        try {
            await control(operation.id, 'cancel')
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(null)
        }
    }

    return (
        <section className="quick-list" aria-labelledby="quick-in-progress">
            <h2 id="quick-in-progress">In progress <span className="quick-count">{operations.length}</span></h2>
            <ul>
                {operations.map((operation) => {
                    const state = presentDownloadProgress(undefined, operation)
                    const choice = typeof operation.context?.choice === 'string' ? operation.context.choice : ''
                    const sourceKey = typeof operation.context?.source_key === 'string' ? operation.context.source_key : null
                    return (
                        <li key={operation.id} className="quick-list-row">
                            <span className="quick-list-what">
                                <SourceBadge sourceKey={sourceKey}/>
                                <span className="quick-list-title">{operation.title}</span>
                                <small className="quick-muted">{choice}</small>
                            </span>
                            <span className="quick-list-progress">
                                <small>{state.label}{state.secondary ? ` · ${state.secondary}` : ''}</small>
                                <ProgressBar value={state.mode === 'determinate' ? state.percent : null} mode={state.mode}
                                             ariaLabel={`Progress of ${operation.title}`} detail={state.detail}/>
                            </span>
                            <span className="quick-list-actions">
                                <button type="button" className="btn" disabled={busy === operation.id || state.canCancel === false}
                                        onClick={() => void cancel(operation)}>
                                    Cancel
                                </button>
                            </span>
                        </li>
                    )
                })}
            </ul>
        </section>
    )
}

export function QuickReadyList({ready}: {ready: QuickDownloadReady[]}) {
    const queryClient = useQueryClient()
    const now = useNow()
    const [busy, setBusy] = useState<string | null>(null)
    if (!ready.length) return null

    const discard = async (item: QuickDownloadReady) => {
        setBusy(item.id)
        try {
            await removeQuickDownload(item.id)
            await queryClient.invalidateQueries({queryKey: quickDownloadsQueryKey})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(null)
        }
    }

    // The browser downloads the file itself; once every byte has gone out the file
    // turns into "Downloaded", which the next refresh shows.
    const downloaded = () => {
        window.setTimeout(() => void queryClient.invalidateQueries({queryKey: quickDownloadsQueryKey}), 5_000)
    }

    return (
        <section className="quick-list" aria-labelledby="quick-ready">
            <h2 id="quick-ready">Ready to download <span className="quick-count">{ready.length}</span></h2>
            <ul>
                {ready.map((item) => (
                    <li key={item.id} className="quick-list-row">
                        <span className="quick-list-what">
                            <SourceBadge sourceKey={item.sourceKey}/>
                            <span className="quick-list-title">{item.title}</span>
                            <small className="quick-muted">{item.format} · {formatBytes(item.sizeBytes)}</small>
                        </span>
                        <span className="quick-list-progress">
                            <small className={item.state === 'delivered' ? 'quick-ok' : 'quick-warn'}>
                                {item.state === 'delivered' ? 'Downloaded · deleted ' : 'Deleted '}
                                {untilLabel(item.expiresAt, now)}
                            </small>
                        </span>
                        <span className="quick-list-actions">
                            <a className="btn btn-primary" href={quickDownloadFileUrl(item.id)} download={item.fileName} onClick={downloaded}>
                                <FontAwesomeIcon icon={faIcon('fass', 'download')}/>
                                Download file
                            </a>
                            <button type="button" className="btn" disabled={busy === item.id} onClick={() => void discard(item)}>
                                Discard
                            </button>
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}

const OUTCOME_LABELS: Record<QuickDownloadHistoryEntry['outcome'], string> = {
    working: 'Working',
    ready: 'Ready',
    downloaded: 'Downloaded',
    expired: 'Deleted, never downloaded',
    discarded: 'Discarded',
    canceled: 'Canceled',
    failed: 'Failed',
    refused: 'Not downloaded',
}

const OUTCOME_TONES: Partial<Record<QuickDownloadHistoryEntry['outcome'], string>> = {
    downloaded: 'quick-ok',
    failed: 'quick-warn',
    refused: 'quick-warn',
}

function whenLabel(date: Date): string {
    return date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'})
}

/**
 * What was quick downloaded, from where, as what and how it ended. Download
 * again looks the link up once more with the same choices.
 */
export function QuickHistoryList({entries, onDownloadAgain}: {
    entries: QuickDownloadHistoryEntry[]; onDownloadAgain: (entry: QuickDownloadHistoryEntry) => void
}) {
    const queryClient = useQueryClient()
    const [clearing, setClearing] = useState(false)
    const [confirming, setConfirming] = useState(false)
    if (!entries.length) return null
    const finished = entries.filter((entry) => entry.outcome !== 'working' && entry.outcome !== 'ready').length

    const clear = async () => {
        setClearing(true)
        try {
            await clearQuickDownloadHistory()
            await queryClient.invalidateQueries({queryKey: quickDownloadHistoryQueryKey})
            setConfirming(false)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setClearing(false)
        }
    }

    return (
        <section className="quick-list" aria-labelledby="quick-history">
            <div className="quick-list-heading">
                <h2 id="quick-history">History <span className="quick-count">{entries.length}</span></h2>
                {finished > 0 && (confirming ? (
                    <span className="quick-list-actions">
                        <span className="quick-muted">Forget {finished} finished {finished === 1 ? 'entry' : 'entries'}?</span>
                        <button type="button" className="btn btn-danger" disabled={clearing} onClick={() => void clear()}>Clear</button>
                        <button type="button" className="btn" onClick={() => setConfirming(false)}>Keep</button>
                    </span>
                ) : (
                    <button type="button" className="btn" onClick={() => setConfirming(true)}>Clear history</button>
                ))}
            </div>
            <ul>
                {entries.map((entry) => (
                    <li key={entry.id} className="quick-list-row">
                        <span className="quick-list-what">
                            <SourceBadge sourceKey={entry.sourceKey}/>
                            <span className="quick-list-title">{entry.title}</span>
                            <small className="quick-muted">
                                {[entry.format, entry.sizeBytes ? formatBytes(entry.sizeBytes) : null].filter(Boolean).join(' · ')}
                            </small>
                        </span>
                        <span className="quick-list-progress">
                            <span className={OUTCOME_TONES[entry.outcome]}>{OUTCOME_LABELS[entry.outcome]}</span>
                            <small className="quick-muted">
                                {entry.message ? `${entry.message} · ` : ''}{whenLabel(entry.startedAt)}
                            </small>
                        </span>
                        <span className="quick-list-actions">
                            <button type="button" className="btn" onClick={() => onDownloadAgain(entry)}>
                                <FontAwesomeIcon icon={faIcon('fass', 'rotate-right')}/> Download again
                            </button>
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}
