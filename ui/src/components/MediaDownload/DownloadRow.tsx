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

/**
 * Send a download action for one row, then refresh the row's downloads and the download lists.
 * A failed request is reported in a toast.
 */
export function useDownloadRowRequest(downloadsQueryKey: QueryKey) {
    const qc = useQueryClient()
    const [busy, setBusy] = useState(false)

    async function request(path: string, init: RequestInit, failure: string) {
        setBusy(true)
        try {
            const response = await fetch(
                `${(window as any).appConfig.API_URL}${path}`,
                {credentials: 'include', ...init},
            )
            if (!response.ok) {
                const {error} = await getErrorMessageFromResponse(response)
                toast.error(error || failure)
            }
            await Promise.all([
                qc.invalidateQueries({queryKey: downloadsQueryKey}),
                qc.invalidateQueries({queryKey: ['mediaDownloads']}),
                qc.invalidateQueries({queryKey: ['mediaDownloadsView']}),
            ])
        } catch {
            toast.error(failure)
        } finally {
            setBusy(false)
        }
    }

    const cancel = (download: MediaDownloadViewRead) => request(
        `/media-downloads/${download.id}/cancel`,
        {method: 'POST'},
        'Could not cancel the download',
    )

    return {busy, request, cancel}
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
    retry,
    onDownload,
    onCancel,
    children,
}: {
    profile: LocalMediaProfileRead
    download?: MediaDownloadViewRead
    downloadStateKnown: boolean
    busy: boolean
    /** The retry button, when the row offers one. */
    retry: {title: string, label: string, onClick: () => void} | null
    onDownload: () => void
    onCancel: () => void
    /** Dialogs that belong to the row. */
    children?: ReactNode
}) {
    const [showLog, setShowLog] = useState(false)

    return (
        <div className="download-row" role="listitem" aria-label={`Download for ${profile.name}`}>
            <div className="download-row-info">
                <div className="download-row-name">{profile.name}</div>
                <div className="download-row-format">{PreferredFormatReg.getLabelLoose(profile.preferredFormat)}</div>
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
                        ? <DownloadProgressStatus download={download} details={false}/>
                        : <button
                            type="button"
                            className="btn btn-primary"
                            onClick={onDownload}
                            disabled={busy}
                            aria-label={`Download ${profile.name}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'download')}/>
                            Download
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
                            disabled={busy}
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
