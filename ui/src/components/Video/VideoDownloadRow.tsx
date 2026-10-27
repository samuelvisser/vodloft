import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import type {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {DownloadRow, useDownloadRowRequest} from '../MediaDownload/DownloadRow'

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
    const {busy, request, cancel} = useDownloadRowRequest(['videoDownloads', videoId])

    const startDownload = () => request(
        `/videos/${videoId}/downloads`,
        {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({localMediaProfileId: profile.id}),
        },
        'Could not start the download',
    )
    const retryDownload = (retried: MediaDownloadViewRead) => request(
        `/media-downloads/${retried.id}/retry`,
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'},
        'Could not retry the download',
    )

    const succeeded = download?.presentation.outcome === 'success'
    return (
        <DownloadRow
            profile={profile}
            download={download}
            downloadStateKnown={downloadStateKnown}
            busy={busy}
            retry={download && !download.presentation.active && download.presentation.canRetry
                ? {
                    title: succeeded ? 'Re-download' : 'Retry download',
                    label: succeeded ? `Re-download ${profile.name}` : `Retry download for ${profile.name}`,
                    onClick: () => void retryDownload(download),
                }
                : null}
            onDownload={() => void startDownload()}
            onCancel={() => download && void cancel(download)}
        />
    )
}
