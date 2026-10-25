import {useState} from 'react'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import ActionMenu from '../../components/ActionMenu/ActionMenu'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import SourceBadge from '../../components/Source/SourceBadge'
import {VideoDownloadRow} from '../../components/Video/VideoDownloadRow'
import {faIcon} from '../../icons/faIcon'
import {useLocalMediaProfiles, useSourceLookup, useVideo, useVideoDownloads} from '../../lib/queries'
import {MediaDownloadViewRead} from '../../types/schemas/media_download'
import {VideoReadSchema} from '../../types/schemas/video'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import '../episode/EpisodePage.css'
import {siteName} from '../../lib/siteName'
import {DrmBadge, DrmNotice} from '../../components/common/DrmProtected'

function formatDuration(seconds: number) {
    if (!seconds) return null
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.round((seconds % 3600) / 60)
    return hours ? `${hours}h ${minutes}m` : `${Math.max(minutes, 1)}m`
}

/** The site a video is on, since one Source can serve many sites. */
export default function VideoPage() {
    const {id} = useParams()
    const videoId = id && /^\d+$/.test(id) ? Number(id) : undefined
    const navigate = useNavigate()
    const qc = useQueryClient()
    const {data: video, isPending, error} = useVideo(videoId)
    const {data: profiles, error: profilesError} = useLocalMediaProfiles()
    const {data: downloads, error: downloadsError, hasDomainData: hasDownloadState} = useVideoDownloads(videoId)
    const sourceName = useSourceLookup().name(video?.sourceKey)
    const [refreshing, setRefreshing] = useState(false)
    const [confirmDelete, setConfirmDelete] = useState(false)
    const [deleting, setDeleting] = useState(false)

    if (videoId === undefined || (!video && !isPending)) {
        return (
            <section className="view episode-view">
                <div className="view-header">
                    <h1>Video</h1>
                </div>
                <p>{error?.message ?? 'Video not found.'}</p>
                <p><Link to="/library?type=videos">Back to videos</Link></p>
            </section>
        )
    }
    if (!video) return <section className="view episode-view" aria-busy="true"><p>Loading video…</p></section>

    const videoProfiles = profiles?.filter((profile) => profile.type === 'video')
    const downloadByProfileId = new Map<number, MediaDownloadViewRead>(
        (downloads ?? []).map((download) => [download.localMediaProfileId, download]),
    )
    const downloadStateError = (profiles === undefined ? profilesError : null)
        ?? (!hasDownloadState ? downloadsError : null)
    const cover = toImageUrl(video.thumbnailLandscapePath || video.backgroundImagePath)
    const duration = formatDuration(video.duration)

    const refresh = async () => {
        if (refreshing) return
        setRefreshing(true)
        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/videos/${video.id}/refresh`, {
                method: 'POST',
                credentials: 'include',
            })
            if (!response.ok) {
                const {error: message} = await getErrorMessageFromResponse(response)
                toast.error(message || 'Could not refresh the video')
                return
            }
            qc.setQueryData(['video', video.id], VideoReadSchema.parse(await response.json()))
            await qc.invalidateQueries({queryKey: ['videos']})
            toast.success('Video details refreshed')
        } catch {
            toast.error('Could not refresh the video')
        } finally {
            setRefreshing(false)
        }
    }

    const deleteVideo = async () => {
        if (deleting) return
        setDeleting(true)
        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/videos/${video.id}`, {
                method: 'DELETE',
                credentials: 'include',
            })
            if (!response.ok) {
                const {error: message} = await getErrorMessageFromResponse(response)
                toast.error(message || 'Could not delete the video')
                return
            }
            setConfirmDelete(false)
            await Promise.all([
                qc.invalidateQueries({queryKey: ['videos']}),
                qc.invalidateQueries({queryKey: ['mediaDownloads']}),
                qc.invalidateQueries({queryKey: ['mediaDownloadsView']}),
            ])
            navigate('/library?type=videos')
        } catch {
            toast.error('Could not delete the video')
        } finally {
            setDeleting(false)
        }
    }

    return (
        <section className="view episode-view video-view" aria-labelledby="video-title">
            <article className="episode-details" aria-label="Video details">
                <nav className="episode-breadcrumb" aria-label="Breadcrumb">
                    <Link to="/library">Library</Link>
                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')} aria-hidden="true"/>
                    <Link to="/library?type=videos">Videos</Link>
                </nav>

                <div className="episode-cover">
                    {cover
                        ? <img src={cover} alt="Video thumbnail"/>
                        : <div className="video-cover-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'film')}/></div>}
                </div>

                <header className="episode-header">
                    <div className="episode-title-row">
                        <h1 id="video-title" className="episode-title-text">{video.title}</h1>
                        <ActionMenu
                            items={[
                                {
                                    label: 'Refresh details',
                                    icon: faIcon('fass', 'arrows-rotate'),
                                    disabled: refreshing,
                                    disabledReason: refreshing ? `Asking ${sourceName} for the latest details…` : undefined,
                                    onSelect: () => void refresh(),
                                },
                                {
                                    label: 'Delete video',
                                    icon: faIcon('fass', 'trash'),
                                    tone: 'danger' as const,
                                    separatorBefore: true,
                                    onSelect: () => setConfirmDelete(true),
                                },
                            ]}
                        />
                    </div>
                    <div className="episode-summary" aria-label="Video metadata">
                        <SourceBadge sourceKey={video.sourceKey}/>
                        {video.drmProtected && <DrmBadge/>}
                        {video.authorName && (
                            <>
                                <span className="episode-summary-separator" aria-hidden="true"/>
                                <span className="episode-summary-item">
                                    <FontAwesomeIcon icon={faIcon('fass', 'user')} aria-hidden="true"/>
                                    {video.authorUrl
                                        ? <a href={video.authorUrl} target="_blank" rel="noreferrer">{video.authorName}</a>
                                        : <span>{video.authorName}</span>}
                                </span>
                            </>
                        )}
                        {video.publishedAt && (
                            <>
                                <span className="episode-summary-separator" aria-hidden="true"/>
                                <span className="episode-summary-item">
                                    <FontAwesomeIcon icon={faIcon('fass', 'calendar')} aria-hidden="true"/>
                                    <span>Uploaded {video.publishedAt.toLocaleDateString(undefined, {year: 'numeric', month: 'short', day: 'numeric'})}</span>
                                </span>
                            </>
                        )}
                        {duration && (
                            <>
                                <span className="episode-summary-separator" aria-hidden="true"/>
                                <span className="episode-summary-item">
                                    <FontAwesomeIcon icon={faIcon('fass', 'clock')} aria-hidden="true"/>
                                    <span>{duration}</span>
                                </span>
                            </>
                        )}
                        <span className="episode-summary-separator" aria-hidden="true"/>
                        <a className="episode-summary-item" href={video.sharingUrl} target="_blank" rel="noreferrer">
                            <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                            <span>Open on {siteName(video.sharingUrl) ?? sourceName}</span>
                        </a>
                    </div>
                </header>

                {!!video.description?.trim() && (
                    <section className="episode-description" aria-labelledby="video-description-title">
                        <h2 id="video-description-title">Description</h2>
                        <p>{video.description}</p>
                    </section>
                )}

                <div className="episode-downloads" aria-labelledby="video-downloads-title">
                    <h2 id="video-downloads-title">Downloads</h2>
                    {video.drmProtected && <DrmNotice/>}
                    {!video.drmProtected && downloadStateError && (
                        <div className="form-error-card" role="alert">
                            Could not load download status: {downloadStateError.message}
                        </div>
                    )}
                    {!video.drmProtected && !downloadStateError && profiles === undefined && (
                        <div role="status" aria-busy="true" className="episode-downloads-loading">
                            Loading download options…
                        </div>
                    )}
                    {!video.drmProtected && !downloadStateError && profiles !== undefined && !videoProfiles?.length && (
                        <p>
                            No Video Local Media Profiles yet.{' '}
                            <Link to="/add-local-media-profile?type=video">Add one</Link> to download this video.
                        </p>
                    )}
                    {!video.drmProtected && !downloadStateError && !!videoProfiles?.length && (
                        <div role="list" aria-label="Available downloads per Local Media Profile">
                            {videoProfiles.map((profile) => {
                                const download = downloadByProfileId.get(profile.id)
                                return (
                                    <VideoDownloadRow
                                        key={profile.id}
                                        profile={profile}
                                        download={download}
                                        downloadStateKnown={hasDownloadState || download !== undefined}
                                        videoId={video.id}
                                    />
                                )
                            })}
                        </div>
                    )}
                </div>
            </article>

            <ConfirmDialog
                open={confirmDelete}
                title="Delete video"
                onDismiss={() => {
                    if (!deleting) setConfirmDelete(false)
                }}
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                dismissOnOverlayClick={!deleting}
                cancelButton={{disabled: deleting}}
                confirmButton={{
                    label: deleting ? 'Deleting…' : 'Delete',
                    onClick: deleteVideo,
                    className: 'btn btn-danger',
                    disabled: deleting,
                }}
            >
                <p>
                    Are you sure you want to delete "{video.title}" from VODLoft? This removes the video and its
                    download history from the VODLoft database. Downloaded files already on disk are not removed.
                </p>
            </ConfirmDialog>
        </section>
    )
}
