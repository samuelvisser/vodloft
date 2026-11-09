import {type ReactNode, useState} from 'react'
import {type QueryKey, useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {PreferredFormatReg} from '../../types/local_media_profile'
import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import type {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import {faIcon} from '../../icons/faIcon'
import DownloadProgressStatus from '../DownloadProgress/DownloadProgressStatus'
import ProgressExplanation from '../common/ProgressExplanation'
import DownloadLogDialog from './DownloadLogDialog'
import {apiUrl} from '../../lib/api'
import {startLabel, useDownloadStarts} from '../../lib/downloadStarts'
import {refreshFrontendPuller} from '../../lib/puller'

/**
 * Send a download action for one row, then refresh the row's downloads and the download lists.
 * A failed request is reported in a toast. A retry or re-download shows as started at once.
 */
export function useDownloadRowRequest(downloadsQueryKey: QueryKey) {
    const qc = useQueryClient()
    const [busy, setBusy] = useState(false)
    const starts = useDownloadStarts()

    /** Send the request; resolves to whether the server accepted it. */
    async function request(path: string, init: RequestInit, failure: string): Promise<boolean> {
        setBusy(true)
        let accepted = false
        try {
            const response = await fetch(
                `${apiUrl()}${path}`,
                {credentials: 'include', ...init},
            )
            accepted = response.ok
            if (!response.ok) {
                const {error} = await getErrorMessageFromResponse(response)
                toast.error(error || failure)
            }
            await Promise.all([
                qc.invalidateQueries({queryKey: downloadsQueryKey}),
                qc.invalidateQueries({queryKey: ['mediaDownloads']}),
                qc.invalidateQueries({queryKey: ['mediaDownloadsView']}),
                refreshFrontendPuller(qc),
            ])
        } catch {
            toast.error(failure)
        } finally {
            setBusy(false)
        }
        return accepted
    }

    const sendCancel = (download: MediaDownloadViewRead) => request(
        `/media-downloads/${download.id}/cancel`,
        {method: 'POST'},
        'Could not cancel the download',
    )

    const cancel = (download: MediaDownloadViewRead) => starts.cancel(download, () => sendCancel(download))

    /** Retry or re-download an existing download, showing it as starting until its live progress arrives. */
    const retry = (download: MediaDownloadViewRead, path: string, init: RequestInit, failure: string) => starts.start(
        download,
        startLabel(download),
        () => request(path, init, failure),
        () => sendCancel(download),
    )

    return {busy, request, cancel, retry, present: starts.present, isStarting: starts.isStarting}
}

/** Whether a row offers to download, because nothing is downloaded or running for its profile yet. */
export function offersDownload(download: MediaDownloadViewRead | undefined, downloadStateKnown: boolean) {
    return downloadStateKnown && (
        !download
        || (!download.presentation.active && download.presentation.status === 'not_downloaded')
    )
}

/** One Local Media Profile and the state of a media item's download for it. */
export function DownloadRow({
    profile,
    download,
    downloadStateKnown,
    busy,
    starting = false,
    retry,
    onDownload,
    onCancel,
    note,
    downloadLabel = 'Download',
    actions,
    children,
}: {
    profile: LocalMediaProfileRead
    download?: MediaDownloadViewRead
    downloadStateKnown: boolean
    busy: boolean
    /** Whether the row's retry is still on its way to the server; it can be canceled meanwhile. */
    starting?: boolean
    /** The retry button, when the row offers one. */
    retry: {title: string, label: string, onClick: () => void} | null
    onDownload: () => void
    onCancel: () => void
    /** A line under the profile name, such as why the episode was skipped. */
    note?: ReactNode
    downloadLabel?: string
    /** Extra buttons before the log button. */
    actions?: ReactNode
    /** Dialogs that belong to the row. */
    children?: ReactNode
}) {
    const [showLog, setShowLog] = useState(false)

    return (
        <div className="download-row" role="listitem" aria-label={`Download for ${profile.name}`}>
            <div className="download-row-info">
                <div className="download-row-name">{profile.name}</div>
                <div className="download-row-format">{PreferredFormatReg.getLabelLoose(profile.preferredFormat)}</div>
                {note && <div className="download-row-note">{note}</div>}
            </div>
            <div className="download-row-state">
                {!downloadStateKnown
                    ? (
                        <span
                            className="download-row-loading"
                            role="status"
                            aria-label={`Loading download status for ${profile.name}`}
                        >
                            Loading…
                        </span>
                    )
                    : download && !offersDownload(download, downloadStateKnown)
                        ? <DownloadProgressStatus presentation={download.presentation} details={false}/>
                        : <button
                            type="button"
                            className="btn btn-primary"
                            onClick={onDownload}
                            disabled={busy}
                            aria-label={`Download ${profile.name}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'download')}/>
                            {downloadLabel}
                        </button>}
            </div>
            {downloadStateKnown && download && (
                <div className="download-row-actions" aria-label={`Actions for ${profile.name}`}>
                    <ProgressExplanation
                        detail={download.presentation.detail + (download.presentation.secondary
                            ? ` ${download.presentation.secondary}.`
                            : '')}
                    />
                    {download.presentation.active && download.presentation.canCancel && (
                        <button
                            type="button"
                            className="icon-btn"
                            onClick={onCancel}
                            disabled={busy && !starting}
                            title="Cancel download"
                            aria-label={`Cancel download for ${profile.name}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'ban')}/>
                        </button>
                    )}
                    {retry && (
                        <button
                            type="button"
                            className="icon-btn"
                            onClick={retry.onClick}
                            disabled={busy}
                            title={retry.title}
                            aria-label={retry.label}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'rotate-right')}/>
                        </button>
                    )}
                    {actions}
                    <button
                        type="button"
                        className="icon-btn"
                        onClick={() => setShowLog(true)}
                        title="View log"
                        aria-label={`View log for ${profile.name}`}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'file-lines')}/>
                    </button>
                </div>
            )}
            {children}
            <DownloadLogDialog row={showLog ? (download ?? null) : null} onClose={() => setShowLog(false)}/>
        </div>
    )
}
