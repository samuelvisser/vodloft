import {useMemo} from 'react'
import {can} from '../lib/access'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'

import DownloadProgressStatus from '../components/DownloadProgress/DownloadProgressStatus'
import KeepQuestions from '../components/KeepQuestions/KeepQuestions'
import {
    useLocalMediaProfiles,
    useMediaDownloadsCollection,
    useMovies,
    useRecentlyIndexedEpisodes,
    useCollections,
    useKeepQuestions,
    useSourceProblems,
} from '../lib/queries'
import {
    DEFAULT_DOWNLOAD_STATUS_FILTER,
    downloadsUrlForStatusFilters,
} from '../lib/downloadStatusFilters'
import {EpisodeIndexedActivityRead} from '../types/schemas/episode'
import {MediaDownloadViewRead} from '../types/schemas/media_download'
import {movieExtraTypeLabel} from '../utils/movieExtras'

const IN_PROGRESS = ['preparing', 'waiting', 'canceling', 'downloading', 'local_processing'] as const
const QUEUED = ['pending'] as const
const PROBLEMS = ['error', 'missing', 'corrupted'] as const
const COMPLETE = ['downloaded', 'redownloaded'] as const
const HOME_SECTION_LIMIT = 3
const RECENT_ACTIVITY_LIMIT = 9

type RecentActivityItem =
    | {kind: 'download'; occurredAt: Date; download: MediaDownloadViewRead}
    | {kind: 'episode-indexed'; occurredAt: Date; episode: EpisodeIndexedActivityRead}

function mediaTitle(download: MediaDownloadViewRead) {
    return download.mediaTitle || download.movieTitle || download.episodeTitle || 'Unknown media'
}

function mediaContext(download: MediaDownloadViewRead) {
    if (download.type === 'movie_extra') {
        return `${movieExtraTypeLabel(download.movieExtraType)} • ${download.movieTitle || 'Movie'}`
    }
    return download.movieTitle ? 'Movie' : download.collectionTitle || 'Episode'
}

export default function HomePage() {
    const {data: collections} = useCollections()
    const {data: movies} = useMovies()
    const {data: profiles} = useLocalMediaProfiles()
    const defaultDownloadStatuses = useMemo(
        () => [...DEFAULT_DOWNLOAD_STATUS_FILTER].sort(),
        [],
    )
    const downloadsQuery = useMediaDownloadsCollection({
        statuses: defaultDownloadStatuses,
        order: 'workflow',
        initialCount: HOME_SECTION_LIMIT,
        batchSize: 50,
    })
    const sourceProblemsQuery = useSourceProblems()
    const keepQuestions = useKeepQuestions().data ?? []
    const keepQuestionEpisodes = new Set(keepQuestions.map((question) => question.episodeId)).size
    const problemsQuery = useMediaDownloadsCollection({
        statuses: PROBLEMS,
        order: 'workflow',
        initialCount: HOME_SECTION_LIMIT,
        batchSize: HOME_SECTION_LIMIT,
    })
    const recentDownloadsQuery = useMediaDownloadsCollection({
        statuses: COMPLETE,
        order: 'recent',
        initialCount: RECENT_ACTIVITY_LIMIT,
        batchSize: RECENT_ACTIVITY_LIMIT,
    })
    const {data: indexedEpisodes} = useRecentlyIndexedEpisodes(RECENT_ACTIVITY_LIMIT)
    const active = downloadsQuery.data
        .filter((download) => (
            IN_PROGRESS.includes(download.downloadStatus as typeof IN_PROGRESS[number])
            || QUEUED.includes(download.downloadStatus as typeof QUEUED[number])
        ))
        .slice(0, HOME_SECTION_LIMIT)
    const problems = problemsQuery.data
    const metadataProblems = movies?.filter((movie) => movie.releaseDateLookupStatus === 'error') || []
    const sourceProblems = sourceProblemsQuery.data ?? []
    const hasAttention = problemsQuery.total > 0 || metadataProblems.length > 0 || profiles?.length === 0 || sourceProblems.length > 0
    // The keep question has its own card above, so it does not fill Needs attention.
    const needsAnAnswer = hasAttention || keepQuestionEpisodes > 0
    const downloadError = (
        downloadsQuery.error
        ?? problemsQuery.error
        ?? recentDownloadsQuery.error
    )
    const activeSectionIsEmpty = active.length === 0
    const attentionSectionIsEmpty = !problemsQuery.isPending
        && movies !== undefined
        && profiles !== undefined
        && !hasAttention
    const attentionSummary = [
        problemsQuery.total ? `${problemsQuery.total} download problem${problemsQuery.total === 1 ? '' : 's'}` : null,
        metadataProblems.length ? `${metadataProblems.length} movie metadata problem${metadataProblems.length === 1 ? '' : 's'}` : null,
        profiles?.length === 0 ? 'No Local Media Profiles' : null,
        ...sourceProblems.map((problem) => problem.title),
        keepQuestionEpisodes ? `${keepQuestionEpisodes} download${keepQuestionEpisodes === 1 ? '' : 's'} removed from the Source` : null,
    ].filter(Boolean).join(' • ')
    const recentActivity = useMemo(() => {
        const activity: RecentActivityItem[] = []

        for (const download of recentDownloadsQuery.data) {
            const occurredAt = download.finishedAt ?? download.downloadedAt
            if (!occurredAt) continue
            activity.push({kind: 'download', occurredAt, download})
        }

        for (const episode of indexedEpisodes ?? []) {
            activity.push({
                kind: 'episode-indexed',
                occurredAt: episode.indexedAt,
                episode,
            })
        }

        return activity
            .sort((left, right) => right.occurredAt.getTime() - left.occurredAt.getTime())
            .slice(0, RECENT_ACTIVITY_LIMIT)
    }, [indexedEpisodes, recentDownloadsQuery.data])

    const downloadHref = (download: MediaDownloadViewRead) => {
        if (download.movieSlug) return `/movie/${download.movieSlug}`
        if (download.collectionSlug && download.episodeSlug) return `/collection/${download.collectionSlug}/episode/${download.episodeSlug}`
        return '/downloads'
    }

    return (
        <section className="view operations-home" aria-labelledby="home-title">
            <div className="view-header">
                <div>
                    <h1 id="home-title">Home</h1>
                    <p className="view-description">What VODLoft is doing now and anything that needs your attention.</p>
                </div>
                {can('add_media') && (
                    <Link className="btn btn-primary" to="/add">
                        <FontAwesomeIcon icon={faIcon('fass', 'plus')}/> Add media
                    </Link>
                )}
            </div>

            <div className={`system-health ${needsAnAnswer ? 'needs-attention' : 'is-healthy'}`}>
                <FontAwesomeIcon icon={faIcon('fass', needsAnAnswer ? 'triangle-exclamation' : 'circle-check')}/>
                <div>
                    <strong>{needsAnAnswer ? 'VODLoft needs attention' : 'VODLoft is running normally'}</strong>
                    <small>{needsAnAnswer ? attentionSummary : 'No download, metadata, profile or Source problems detected'}</small>
                </div>
            </div>

            <KeepQuestions questions={keepQuestions}/>

            <div className="operation-stats" aria-label="VODLoft status summary">
                <Link to={downloadsUrlForStatusFilters('downloading', 'local_processing')}><span>Active</span><strong>{IN_PROGRESS.reduce((total, status) => total + (downloadsQuery.facets[status] ?? 0), 0)}</strong></Link>
                <Link to={downloadsUrlForStatusFilters('pending')}><span>Queued</span><strong>{downloadsQuery.facets.pending ?? 0}</strong></Link>
                <Link to={downloadsUrlForStatusFilters('error', 'missing', 'corrupted')}><span>Failed</span><strong>{problemsQuery.total}</strong></Link>
                <Link to="/library"><span>Library</span><strong>{(collections?.length || 0) + (movies?.length || 0)}</strong></Link>
            </div>

            {downloadError && <div className="form-error-card" role="alert">Could not load download status: {downloadError.message}</div>}

            <div className="operations-grid">
                <section
                    className={`operation-section${activeSectionIsEmpty ? ' mobile-empty-section' : ''}`}
                    aria-labelledby="active-downloads-title"
                >
                    <div className="operation-section-header"><h2 id="active-downloads-title">Downloading now</h2><Link to="/downloads">All downloads</Link></div>
                    {active.length ? active.map((download) => (
                        <Link className="operation-download" key={download.id} to={downloadHref(download)}>
                            <span className="operation-icon"><FontAwesomeIcon icon={faIcon('fass', download.movieSlug ? 'clapperboard' : 'podcast')}/></span>
                            <span className="operation-download-copy"><strong>{mediaTitle(download)}</strong><small>{mediaContext(download)} • {download.localMediaProfileName}</small><DownloadProgressStatus presentation={download.presentation} compact details={false}/></span>
                        </Link>
                    )) : <div className="operation-empty"><FontAwesomeIcon icon={faIcon('fass', 'check')}/><span>No active downloads</span></div>}
                </section>

                <section
                    className={`operation-section${attentionSectionIsEmpty ? ' mobile-empty-section' : ''}`}
                    aria-labelledby="attention-title"
                >
                    <div className="operation-section-header"><h2 id="attention-title">Needs attention</h2></div>
                    {profiles?.length === 0 && (
                        <Link className="operation-alert" to="/add-local-media-profile">
                            <FontAwesomeIcon icon={faIcon('fass', 'folder-plus')}/><span><strong>No Local Media Profile</strong><small>Create one before downloading episodes or movies.</small></span><span>Fix</span>
                        </Link>
                    )}
                    {sourceProblems.map((problem) => (
                        <Link className="operation-alert" key={`source-${problem.sourceKey}-${problem.title}`} to="/settings?tab=sources">
                            <FontAwesomeIcon icon={faIcon('fass', 'triangle-exclamation')}/><span><strong>{problem.title}</strong><small>{problem.detail}</small></span><span>Fix</span>
                        </Link>
                    ))}
                    {metadataProblems.slice(0, HOME_SECTION_LIMIT).map((movie) => (
                        <Link className="operation-alert" key={`movie-metadata-${movie.id}`} to={`/movie/${movie.slug}`}>
                            <FontAwesomeIcon icon={faIcon('fass', 'triangle-exclamation')}/><span><strong>{movie.title} metadata</strong><small>{movie.releaseDateLookupError || 'TMDB release-date lookup failed. Open the movie to retry.'}</small></span><span>View</span>
                        </Link>
                    ))}
                    {problems.slice(0, HOME_SECTION_LIMIT).map((download) => (
                        <Link className="operation-alert" key={download.id} to={downloadHref(download)}>
                            <FontAwesomeIcon icon={faIcon('fass', 'triangle-exclamation')}/><span><strong>{mediaTitle(download)}</strong><small>{download.errorMessage || `Download is ${download.downloadStatus}`}</small></span><span>View</span>
                        </Link>
                    ))}
                    {!hasAttention && <div className="operation-empty"><FontAwesomeIcon icon={faIcon('fass', 'circle-check')}/><span>Nothing needs attention</span></div>}
                </section>
            </div>

            <section className="operation-section recent-activity" aria-labelledby="recent-title">
                <div className="operation-section-header"><h2 id="recent-title">Recent activity</h2></div>
                {recentActivity.length ? recentActivity.map((activity) => {
                    if (activity.kind === 'download') {
                        const {download} = activity
                        return (
                            <Link className="recent-download" key={`download-${download.id}`} to={downloadHref(download)}>
                                <FontAwesomeIcon icon={faIcon('fass', 'circle-check')}/><span><strong>{mediaTitle(download)}</strong><small>{mediaContext(download)} • {download.localMediaProfileName}</small></span><time>{activity.occurredAt.toLocaleString()}</time>
                            </Link>
                        )
                    }

                    const {episode} = activity
                    return (
                        <Link
                            className="recent-download recent-indexed-episode"
                            key={`episode-indexed-${episode.id}`}
                            to={`/collection/${episode.collectionSlug}/episode/${episode.slug}`}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'circle-plus')}/><span><strong>{episode.title}</strong><small>{episode.collectionTitle} • Indexed</small></span><time>{activity.occurredAt.toLocaleString()}</time>
                        </Link>
                    )
                }) : <div className="operation-empty"><span>No recent activity yet</span></div>}
            </section>
        </section>
    )
}
