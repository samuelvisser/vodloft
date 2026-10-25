import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {PreferredFormatReg} from '../../types/local_media_profile'
import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import type {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import {faIcon} from '../../icons/faIcon'
import DownloadProgressStatus from '../DownloadProgress/DownloadProgressStatus'
import DownloadLogDialog from '../MediaDownload/DownloadLogDialog'
import ProgressExplanation from '../common/ProgressExplanation'

/** One Video Local Media Profile and the state of this video's download for it. */
export function VideoDownloadRow({
    profile,
    download,
    downloadStateKnown = true,
    videoId,
}: {
    profile: LocalMediaProfileRead
    download?: MediaDownloadViewRead
    downloadStateKnown?: boolean
    videoId: number
}) {
    const qc = useQueryClient()
    const [busy, setBusy] = useState(false)
    const [showLog, setShowLog] = useState(false)

    const invalidate = () =>
        Promise.all([
            qc.invalidateQueries({queryKey: ['videoDownloads', videoId]}),
            qc.invalidateQueries({queryKey: ['mediaDownloads']}),
            qc.invalidateQueries({queryKey: ['mediaDownloadsView']}),
        ])

    async function request(path: string, init: RequestInit, failure: string) {
        setBusy(true)
        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}${path}`, {credentials: 'include', ...init})
            if (!response.ok) {
                const {error} = await getErrorMessageFromResponse(response)
                toast.error(error || failure)
            }
            await invalidate()
        } catch {
            toast.error(failure)
        } finally {
            setBusy(false)
        }
    }

    const startDownload = () => request(
        `/videos/${videoId}/downloads`,
        {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({localMediaProfileId: profile.id}),
        },
        'Could not start the download',
    )
    const retryDownload = () => request(
        `/media-downloads/${download!.id}/retry`,
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'},
        'Could not retry the download',
    )
    const cancelDownload = () => request(
        `/media-downloads/${download!.id}/cancel`,
        {method: 'POST'},
        'Could not cancel the download',
    )

    const showDownloadButton = downloadStateKnown && (
        !download
        || (!download.presentation.active && download.presentation.status === 'not_downloaded')
    )
    const showRetryButton = Boolean(download && !download.presentation.active && download.presentation.canRetry)

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
                    : download && !showDownloadButton
                        ? <DownloadProgressStatus download={download} details={false}/>
                        : <button
                            type="button"
                            className="btn btn-primary"
                            onClick={() => void startDownload()}
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
                            onClick={() => void cancelDownload()}
                            disabled={busy}
                            title="Cancel download"
                            aria-label={`Cancel download for ${profile.name}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'ban')}/>
                        </button>
                    )}
                    {showRetryButton && (
                        <button
                            type="button"
                            className="icon-btn"
                            onClick={() => void retryDownload()}
                            disabled={busy}
                            title={download.presentation.outcome === 'success' ? 'Re-download' : 'Retry download'}
                            aria-label={download.presentation.outcome === 'success'
                                ? `Re-download ${profile.name}`
                                : `Retry download for ${profile.name}`}
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
            <DownloadLogDialog row={showLog ? (download ?? null) : null} onClose={() => setShowLog(false)}/>
        </div>
    )
}
