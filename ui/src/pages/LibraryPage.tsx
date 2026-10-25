import {useEffect, useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link, useNavigate, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import ShowIndexingProgress from '../components/ShowIndexingProgress/ShowIndexingProgress'
import MediaTypeTabs, {MediaType} from '../components/MediaTypeTabs/MediaTypeTabs'
import ShowTypeFilter, {
    createDefaultShowTypeFilter,
    matchesShowTypeFilter,
} from '../components/common/ShowTypeFilter'
import SourceBadge from '../components/Source/SourceBadge'
import SourceFilter, {matchesSourceFilter} from '../components/Source/SourceFilter'
import {useMediaDownloadsView, useMovies, useShowsView, useVideos} from '../lib/queries'
import {MediaDownloadViewRead} from '../types/schemas/media_download'
import {ShowTypeReg, ShowTypeValue} from '../types/show'

const LIBRARY_SHOW_TYPE_FILTER_STORAGE_KEY = 'libraryShowTypeFilter'

function loadLibraryShowTypeFilter(): Set<ShowTypeValue> {
    try {
        const raw = localStorage.getItem(LIBRARY_SHOW_TYPE_FILTER_STORAGE_KEY)
        if (raw === null) return createDefaultShowTypeFilter()

        const parsed: unknown = JSON.parse(raw)
        if (!Array.isArray(parsed)) return createDefaultShowTypeFilter()

        const selectedTypes = parsed.filter(
            (value): value is ShowTypeValue => (
                typeof value === 'string'
                && ShowTypeReg.values.includes(value as ShowTypeValue)
            ),
        )

        // Preserve an intentionally empty filter, while rejecting stored data that
        // only contains stale or otherwise invalid values.
        if (parsed.length > 0 && selectedTypes.length === 0) {
            return createDefaultShowTypeFilter()
        }

        return new Set(selectedTypes)
    } catch {
        return createDefaultShowTypeFilter()
    }
}

function latestMovieDownload(downloads: MediaDownloadViewRead[] | undefined, slug: string) {
    return downloads?.find((download) => download.movieSlug === slug)
}

function latestVideoDownload(downloads: MediaDownloadViewRead[] | undefined, videoId: number) {
    return downloads?.find((download) => download.type === 'video' && download.mediaItemId === videoId)
}

function DownloadStateBadge({download}: {download?: MediaDownloadViewRead}) {
    const status = String(download?.downloadStatus || '')
    if (status === 'downloaded' || status === 'redownloaded') {
        return <span className="movie-state is-complete" aria-label="Downloaded"><FontAwesomeIcon icon={faIcon('fass', 'check')}/></span>
    }
    if (status === 'downloading' || status === 'pending') {
        return <span className="movie-state is-active" aria-label="Downloading"><FontAwesomeIcon icon={faIcon('fass', 'circle-down')}/></span>
    }
    if (status === 'error') {
        return <span className="movie-state is-error" aria-label="Download failed"><FontAwesomeIcon icon={faIcon('fass', 'triangle-exclamation')}/></span>
    }
    return null
}

function formatVideoDuration(seconds: number) {
    if (!seconds) return null
    const total = Math.round(seconds)
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const rest = String(total % 60).padStart(2, '0')
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

export default function LibraryPage() {
    const navigate = useNavigate()
    const [params, setParams] = useSearchParams()
    const [showTypeFilter, setShowTypeFilter] = useState(loadLibraryShowTypeFilter)
    const [sourceFilter, setSourceFilter] = useState<Set<string>>(() => new Set())
    const {data: shows, isLoading: showsLoading, error: showsError} = useShowsView()
    const {data: movies, isLoading: moviesLoading, error: moviesError} = useMovies()
    const {data: videos, isLoading: videosLoading, error: videosError} = useVideos()
    const {data: downloads} = useMediaDownloadsView()
    const sourceKeys = useMemo(
        () => [...new Set([...(shows ?? []), ...(movies ?? []), ...(videos ?? [])].map((item) => item.sourceKey))].sort(),
        [shows, movies, videos],
    )
    const filteredShows = useMemo(
        () => shows?.filter((show) => (
            matchesShowTypeFilter(show.type, showTypeFilter) && matchesSourceFilter(show.sourceKey, sourceFilter)
        )) ?? [],
        [shows, showTypeFilter, sourceFilter],
    )
    const filteredMovies = useMemo(
        () => movies?.filter((movie) => matchesSourceFilter(movie.sourceKey, sourceFilter)) ?? [],
        [movies, sourceFilter],
    )
    const filteredVideos = useMemo(
        () => videos?.filter((video) => matchesSourceFilter(video.sourceKey, sourceFilter)) ?? [],
        [videos, sourceFilter],
    )
    const hasShows = !!shows?.length
    const hasMovies = !!movies?.length
    const hasVideos = !!videos?.length
    const hasAny = hasShows || hasMovies || hasVideos
    const presentTypes = useMemo(() => {
        const types: MediaType[] = []
        if (hasShows) types.push('shows')
        if (hasMovies) types.push('movies')
        if (hasVideos) types.push('videos')
        return types
    }, [hasShows, hasMovies, hasVideos])

    useEffect(() => {
        try {
            localStorage.setItem(
                LIBRARY_SHOW_TYPE_FILTER_STORAGE_KEY,
                JSON.stringify(Array.from(showTypeFilter)),
            )
        } catch {
            // Storage can be unavailable in restricted browser contexts. The filter
            // should still work normally for the current page session in that case.
        }
    }, [showTypeFilter])

    // The URL is the single source of truth for the selected library type, just
    // like on the Browse page. Never switch away from an explicitly requested
    // type based on which query happens to finish first.
    // Without one, open the first type the library has.
    const requestedType = params.get('type')
    const activeType: MediaType = requestedType === 'shows' || requestedType === 'movies' || requestedType === 'videos'
        ? requestedType
        : presentTypes[0] ?? 'shows'

    const chooseType = (type: MediaType) => {
        setParams({type}, {replace: true})
    }

    const loading = showsLoading || moviesLoading || videosLoading
    const error = showsError || moviesError || videosError
    const showTabs = presentTypes.length > 1

    return (
        <section className="view library-view" aria-labelledby="library-title">
            <div className="view-header">
                <div>
                    <h1 id="library-title">Library</h1>
                    <p className="view-description">Shows, movies and videos indexed by VODLoft.</p>
                </div>
                <button className="btn btn-primary" onClick={() => navigate('/add')}>
                    <FontAwesomeIcon icon={faIcon('fass', 'plus')}/>
                    Add media
                </button>
            </div>

            {showTabs && (
                <MediaTypeTabs
                    activeType={activeType}
                    onChange={chooseType}
                    ariaLabel="Library media type"
                    types={presentTypes}
                    counts={{shows: shows?.length ?? 0, movies: movies?.length ?? 0, videos: videos?.length ?? 0}}
                />
            )}

            {hasAny && (
                <SourceFilter
                    sourceKeys={sourceKeys}
                    selected={sourceFilter}
                    onChange={setSourceFilter}
                    ariaLabel="Filter library by source"
                />
            )}

            {activeType === 'shows' && hasShows && (
                <ShowTypeFilter
                    selectedTypes={showTypeFilter}
                    onChange={setShowTypeFilter}
                    ariaLabel="Filter library shows by type"
                />
            )}

            {loading && !hasAny ? (
                <p>Loading library…</p>
            ) : error && !hasAny ? (
                <div className="form-error-card" role="alert">{error.message}</div>
            ) : !hasAny ? (
                <div className="library-empty">
                    <FontAwesomeIcon icon={faIcon('fass', 'book-open')}/>
                    <h2>Your library is empty</h2>
                    <p>Paste a link to a show, a movie or a video to add it.</p>
                    <button className="btn btn-primary" onClick={() => navigate('/add')}>Add media</button>
                </div>
            ) : activeType === 'shows' && hasShows ? (
                filteredShows.length > 0 ? (
                    <div className="library-show-list" role="list" aria-label="Shows">
                        {filteredShows.map((show) => {
                            const image = toImageUrl(
                                show.thumbnailPortraitPath || show.thumbnailLandscapePath || show.logoImagePath || show.authorHeadshotPath,
                            )
                            return (
                                <Link className="show-summary-card library-show-card" to={`/show/${show.slug}`} key={show.slug} role="listitem">
                                    <span className="show-summary-art">
                                        {image ? <img src={image} alt="" loading="lazy" decoding="async"/> : <span className="show-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'podcast')}/></span>}
                                    </span>
                                    <div className="show-summary-copy">
                                        <span className="show-summary-title">{show.title}</span>
                                        <span className="show-summary-author">{show.authorName}</span>
                                        <SourceBadge sourceKey={show.sourceKey}/>
                                        <span className="show-summary-meta">{show.episodeCount} episodes{show.years ? ` • ${show.years}` : ''}</span>
                                        {show.description && <span className="show-summary-description">{show.description}</span>}
                                        <ShowIndexingProgress
                                            showId={show.id}
                                            showSlug={show.slug}
                                            pollForStart={show.episodeCount === 0}
                                            className="library-show-indexing"
                                        />
                                    </div>
                                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')} aria-hidden="true"/>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <div className="catalog-empty">
                        <FontAwesomeIcon icon={faIcon('fass', 'filter')}/>
                        <p>No shows match the selected filters.</p>
                    </div>
                )
            ) : activeType === 'movies' && hasMovies ? (
                <div className="movie-poster-grid" role="list" aria-label="Movies">
                    {filteredMovies.map((movie) => {
                        const image = toImageUrl(
                            movie.thumbnailPortraitPath
                            || movie.thumbnailLandscapePath
                            || movie.backgroundImagePath
                            || movie.logoImagePath,
                        )
                        const download = latestMovieDownload(downloads, movie.slug)
                        return (
                            <Link className="movie-poster-card" to={`/movie/${movie.slug}`} key={movie.slug} role="listitem">
                                <span className="movie-poster-art">
                                    {image
                                        ? <img src={image} alt="" loading="lazy" decoding="async"/>
                                        : <FontAwesomeIcon icon={faIcon('fass', 'clapperboard')}/>
                                    }
                                    <DownloadStateBadge download={download}/>
                                </span>
                                <span className="movie-poster-title">{movie.title}</span>
                                {movie.authorName && <span className="movie-poster-meta">{movie.authorName}</span>}
                                <SourceBadge sourceKey={movie.sourceKey}/>
                            </Link>
                        )
                    })}
                </div>
            ) : activeType === 'videos' && hasVideos ? (
                filteredVideos.length > 0 ? (
                    <div className="video-card-grid" role="list" aria-label="Videos">
                        {filteredVideos.map((video) => {
                            const image = toImageUrl(video.thumbnailLandscapePath || video.backgroundImagePath)
                            const duration = formatVideoDuration(video.duration)
                            return (
                                <Link className="video-card" to={`/video/${video.id}`} key={video.id} role="listitem">
                                    <span className="movie-poster-art">
                                        {image
                                            ? <img src={image} alt="" loading="lazy" decoding="async"/>
                                            : <FontAwesomeIcon icon={faIcon('fass', 'film')}/>
                                        }
                                        {duration && <span className="video-card-duration">{duration}</span>}
                                        <DownloadStateBadge download={latestVideoDownload(downloads, video.id)}/>
                                    </span>
                                    <span className="movie-poster-title">{video.title}</span>
                                    {video.authorName && <span className="movie-poster-meta">{video.authorName}</span>}
                                    <SourceBadge sourceKey={video.sourceKey}/>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <div className="catalog-empty">
                        <FontAwesomeIcon icon={faIcon('fass', 'filter')}/>
                        <p>No videos match the selected filters.</p>
                    </div>
                )
            ) : null}
        </section>
    )
}
