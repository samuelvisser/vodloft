import {useEffect, useMemo, useState} from 'react'
import {can} from '../lib/access'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'
import {ClearInputButton} from '../components/common/ClearInputButton'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import CollectionIndexingProgress from '../components/CollectionIndexingProgress/CollectionIndexingProgress'
import MediaTypeTabs, {MediaType} from '../components/MediaTypeTabs/MediaTypeTabs'
import CollectionTypeFilter, {
    createDefaultCollectionTypeFilter,
    matchesCollectionTypeFilter,
} from '../components/common/CollectionTypeFilter'
import SourceBadge from '../components/Source/SourceBadge'
import CollectionTileArt from '../components/CollectionTileArt/CollectionTileArt'
import {DrmBadge} from '../components/common/DrmProtected'
import {SubscriptionBadge} from '../components/common/NeedsSubscription'
import SourceFilter, {matchesSourceFilter} from '../components/Source/SourceFilter'
import DownloadStatusBadge from '../components/DownloadProgress/DownloadStatusBadge'
import {useLibraryCounts, useLibraryDownloads, useMovies, useCollectionsView, useVideos} from '../lib/queries'
import {MediaDownloadViewRead} from '../types/schemas/media_download'
import {CollectionTypeReg, CollectionTypeValue} from '../types/collection'

const LIBRARY_COLLECTION_TYPE_FILTER_STORAGE_KEY = 'libraryCollectionTypeFilter'
const LIBRARY_SOURCE_FILTER_STORAGE_KEY = 'librarySourceFilter'

/** The remembered Source filter; empty (every Source) when nothing usable is stored. */
function loadLibrarySourceFilter(): Set<string> {
    try {
        const raw = localStorage.getItem(LIBRARY_SOURCE_FILTER_STORAGE_KEY)
        if (raw === null) return new Set()

        const parsed: unknown = JSON.parse(raw)
        if (!Array.isArray(parsed)) return new Set()
        return new Set(parsed.filter((value): value is string => typeof value === 'string'))
    } catch {
        return new Set()
    }
}

function loadLibraryCollectionTypeFilter(): Set<CollectionTypeValue> {
    try {
        const raw = localStorage.getItem(LIBRARY_COLLECTION_TYPE_FILTER_STORAGE_KEY)
        if (raw === null) return createDefaultCollectionTypeFilter()

        const parsed: unknown = JSON.parse(raw)
        if (!Array.isArray(parsed)) return createDefaultCollectionTypeFilter()

        const selectedTypes = parsed.filter(
            (value): value is CollectionTypeValue => (
                typeof value === 'string'
                && CollectionTypeReg.values.includes(value as CollectionTypeValue)
            ),
        )

        // Preserve an intentionally empty filter, while rejecting stored data that
        // only contains stale or otherwise invalid values.
        if (parsed.length > 0 && selectedTypes.length === 0) {
            return createDefaultCollectionTypeFilter()
        }

        return new Set(selectedTypes)
    } catch {
        return createDefaultCollectionTypeFilter()
    }
}

function latestMovieDownload(downloads: MediaDownloadViewRead[] | undefined, slug: string) {
    return downloads?.find((download) => download.type === 'movie' && download.movieSlug === slug)
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

function sameName(a: string, b: string) {
    const plain = (name: string) => name.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
    return plain(a) === plain(b)
}

/** Lower case without accents, so "beyonce" finds "Beyoncé". */
function foldForSearch(text: string) {
    return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Whether every word of the search appears in the item's title or author. */
function matchesLibrarySearch(item: {title: string, authorName?: string | null}, words: string[]) {
    if (words.length === 0) return true
    const haystack = foldForSearch(`${item.title} ${item.authorName ?? ''}`)
    return words.every((word) => haystack.includes(word))
}

function formatVideoDuration(seconds: number) {
    if (!seconds) return null
    const total = Math.round(seconds)
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const rest = String(total % 60).padStart(2, '0')
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}

function NoMatches({search, what}: {search: boolean, what: string}) {
    return (
        <div className="catalog-empty">
            <FontAwesomeIcon icon={search ? faIcon('fass', 'magnifying-glass') : faIcon('fass', 'filter')}/>
            <p>{search ? `No ${what} match your search and filters.` : `No ${what} match the selected filters.`}</p>
        </div>
    )
}

function LibraryTypeLoading({what, error}: {what: string, error: Error | null}) {
    if (error) return <div className="form-error-card" role="alert">{error.message}</div>
    return <p>Loading {what}…</p>
}

export default function LibraryPage() {
    const [params, setParams] = useSearchParams()
    const [collectionTypeFilter, setCollectionTypeFilter] = useState(loadLibraryCollectionTypeFilter)
    const [sourceFilter, setSourceFilter] = useState(loadLibrarySourceFilter)
    const [search, setSearch] = useState('')
    const searchWords = useMemo(() => foldForSearch(search).split(/\s+/).filter(Boolean), [search])
    const {data: collections, isLoading: collectionsLoading, error: collectionsError} = useCollectionsView()
    const {data: movies, isLoading: moviesLoading, error: moviesError} = useMovies()
    const {data: videos, isLoading: videosLoading, error: videosError} = useVideos()
    const {data: downloads} = useLibraryDownloads()
    const {data: libraryCounts, error: libraryCountsError} = useLibraryCounts()
    const sourceKeys = useMemo(
        () => [...new Set([...(collections ?? []), ...(movies ?? []), ...(videos ?? [])].map((item) => item.sourceKey))].sort(),
        [collections, movies, videos],
    )
    // A remembered Source can disappear from the library. Only apply the Sources still
    // present, and every Source while the chips are hidden, so nothing stays filtered
    // out without a visible way to clear it.
    const activeSourceFilter = useMemo(() => {
        if (sourceKeys.length < 2) return new Set<string>()
        const kept = [...sourceFilter].filter((key) => sourceKeys.includes(key))
        return kept.length === sourceKeys.length ? new Set<string>() : new Set(kept)
    }, [sourceFilter, sourceKeys])
    const filteredCollections = useMemo(
        () => collections?.filter((collection) => (
            matchesCollectionTypeFilter(collection.type, collectionTypeFilter) && matchesSourceFilter(collection.sourceKey, activeSourceFilter)
            && matchesLibrarySearch(collection, searchWords)
        )) ?? [],
        [collections, collectionTypeFilter, activeSourceFilter, searchWords],
    )
    const filteredMovies = useMemo(
        () => movies?.filter((movie) => (
            matchesSourceFilter(movie.sourceKey, activeSourceFilter) && matchesLibrarySearch(movie, searchWords)
        )) ?? [],
        [movies, activeSourceFilter, searchWords],
    )
    const filteredVideos = useMemo(
        () => videos?.filter((video) => (
            matchesSourceFilter(video.sourceKey, activeSourceFilter) && matchesLibrarySearch(video, searchWords)
        )) ?? [],
        [videos, activeSourceFilter, searchWords],
    )
    // A loaded list is the truth; until then the counts say which tabs the library will have,
    // so the tabs are there from the start instead of appearing as each list arrives.
    const typeCounts: Partial<Record<MediaType, number>> = {
        collections: collections?.length ?? libraryCounts?.collections,
        movies: movies?.length ?? libraryCounts?.movies,
        videos: videos?.length ?? libraryCounts?.videos,
    }
    // Show no type before every type is known, or a list that arrives first would show alone.
    const typesKnown = libraryCounts !== undefined || (!!collections && !!movies && !!videos)
        || (!!libraryCountsError && !collectionsLoading && !moviesLoading && !videosLoading)
    const hasCollections = typesKnown && !!typeCounts.collections
    const hasMovies = typesKnown && !!typeCounts.movies
    const hasVideos = typesKnown && !!typeCounts.videos
    const hasAny = hasCollections || hasMovies || hasVideos
    const presentTypes = useMemo(() => {
        const types: MediaType[] = []
        if (hasCollections) types.push('collections')
        if (hasMovies) types.push('movies')
        if (hasVideos) types.push('videos')
        return types
    }, [hasCollections, hasMovies, hasVideos])

    useEffect(() => {
        try {
            localStorage.setItem(
                LIBRARY_COLLECTION_TYPE_FILTER_STORAGE_KEY,
                JSON.stringify(Array.from(collectionTypeFilter)),
            )
        } catch {
            // Storage can be unavailable in restricted browser contexts. The filter
            // should still work normally for the current page session in that case.
        }
    }, [collectionTypeFilter])

    useEffect(() => {
        try {
            localStorage.setItem(LIBRARY_SOURCE_FILTER_STORAGE_KEY, JSON.stringify(Array.from(sourceFilter)))
        } catch {
            // As above: without storage the filter just isn't remembered.
        }
    }, [sourceFilter])

    // The URL is the single source of truth for the selected library type, just
    // like on the Browse page. Never switch away from an explicitly requested
    // type based on which query happens to finish first.
    // Without one, open the first type the library has.
    const requestedType = params.get('type')
    const activeType: MediaType = requestedType === 'collections' || requestedType === 'movies' || requestedType === 'videos'
        ? requestedType
        : presentTypes[0] ?? 'collections'

    const chooseType = (type: MediaType) => {
        setParams({type}, {replace: true})
    }

    const loading = collectionsLoading || moviesLoading || videosLoading
    const error = collectionsError || moviesError || videosError
    const showTabs = presentTypes.length > 1

    return (
        <section className="view library-view" aria-labelledby="library-title">
            <div className="view-header">
                <div>
                    <h1 id="library-title">Library</h1>
                    <p className="view-description">Collections, movies and videos indexed by VODLoft.</p>
                </div>
                {can('add_media') && (
                    <Link className="btn btn-primary" to="/add">
                        <FontAwesomeIcon icon={faIcon('fass', 'plus')}/>
                        Add media
                    </Link>
                )}
            </div>

            {showTabs && (
                <MediaTypeTabs
                    activeType={activeType}
                    onChange={chooseType}
                    ariaLabel="Library media type"
                    types={presentTypes}
                    counts={typeCounts}
                />
            )}

            {hasAny && (
                <div className="browse-toolbar library-toolbar">
                    <label className="browse-search">
                        <span className="sr-only">Search {activeType}</span>
                        <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                        <input
                            enterKeyHint="search"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder={`Search ${activeType}`}
                        />
                        {search && <ClearInputButton label="Clear the search" onClear={() => setSearch('')}/>}
                    </label>
                </div>
            )}

            {hasAny && (
                <SourceFilter
                    sourceKeys={sourceKeys}
                    selected={activeSourceFilter}
                    onChange={setSourceFilter}
                    ariaLabel="Filter library by source"
                />
            )}

            {activeType === 'collections' && hasCollections && (
                <CollectionTypeFilter
                    selectedTypes={collectionTypeFilter}
                    onChange={setCollectionTypeFilter}
                    ariaLabel="Filter library collections by type"
                />
            )}

            {(!typesKnown || loading) && !hasAny ? (
                <p>Loading library…</p>
            ) : error && !hasAny ? (
                <div className="form-error-card" role="alert">{error.message}</div>
            ) : !hasAny ? (
                <div className="library-empty">
                    <FontAwesomeIcon icon={faIcon('fass', 'book-open')}/>
                    <h2>Your library is empty</h2>
                    <p>Paste a link to a collection, a movie or a video to add it.</p>
                    {can('add_media') && <Link className="btn btn-primary" to="/add">Add media</Link>}
                </div>
            ) : activeType === 'collections' && hasCollections && !collections ? (
                <LibraryTypeLoading what="collections" error={collectionsError}/>
            ) : activeType === 'movies' && hasMovies && !movies ? (
                <LibraryTypeLoading what="movies" error={moviesError}/>
            ) : activeType === 'videos' && hasVideos && !videos ? (
                <LibraryTypeLoading what="videos" error={videosError}/>
            ) : activeType === 'collections' && hasCollections ? (
                filteredCollections.length > 0 ? (
                    <div className="library-collection-grid" role="list" aria-label="Collections">
                        {filteredCollections.map((collection) => {
                            // The tile is square, so square artwork comes first when a Source has it.
                            const image = toImageUrl(
                                collection.thumbnailSquarePath || collection.thumbnailPortraitPath || collection.thumbnailLandscapePath || collection.logoImagePath || collection.authorHeadshotPath,
                            )
                            // A yt-dlp channel's author is usually the channel itself: do not say its name twice.
                            const showAuthor = !!collection.authorName && !sameName(collection.authorName, collection.title)
                            return (
                                <Link className="library-tile" to={`/collection/${collection.slug}`} key={collection.slug} role="listitem">
                                    <span className="library-tile-art">
                                        {image
                                            ? <CollectionTileArt key={image} src={image}/>
                                            : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'podcast')}/></span>}
                                        <SourceBadge sourceKey={collection.sourceKey} className="library-tile-source"/>
                                    </span>
                                    <span className="library-tile-copy">
                                        <span className="library-tile-title">{collection.title}</span>
                                        {showAuthor && <span className="library-tile-author">{collection.authorName}</span>}
                                        <span className="library-tile-status">
                                            <span className="library-tile-meta">
                                                <span>{collection.episodeCount} episodes</span>
                                                {collection.years && <span>{collection.years}</span>}
                                            </span>
                                            <CollectionIndexingProgress
                                                collectionId={collection.id}
                                                collectionSlug={collection.slug}
                                                pollForStart={collection.episodeCount === 0}
                                                className="library-collection-indexing"
                                            />
                                        </span>
                                    </span>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <NoMatches search={searchWords.length > 0} what="collections"/>
                )
            ) : activeType === 'movies' && hasMovies ? (
                filteredMovies.length > 0 ? (
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
                                        {movie.drmProtected && <DrmBadge onCover/>}
                                    </span>
                                    <span className="movie-poster-title">{movie.title}</span>
                                    {movie.authorName && <span className="movie-poster-meta">{movie.authorName}</span>}
                                    <SourceBadge sourceKey={movie.sourceKey}/>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <NoMatches search={searchWords.length > 0} what="movies"/>
                )
            ) : activeType === 'videos' && hasVideos ? (
                filteredVideos.length > 0 ? (
                    <div className="episodes-grid" role="list" aria-label="Videos">
                        {filteredVideos.map((video) => {
                            const image = toImageUrl(video.thumbnailLandscapePath || video.backgroundImagePath)
                            const duration = formatVideoDuration(video.duration)
                            const download = latestVideoDownload(downloads, video.id)
                            return (
                                <Link className="episode-card" to={`/video/${video.id}`} key={video.id} role="listitem" aria-label={video.title}>
                                    <span className="cover" style={image ? {backgroundImage: `url(${image})`} : undefined}>
                                        {download && download.presentation.status !== 'not_downloaded' && (
                                            <span className="status-group" role="list" aria-label="Download status">
                                                <DownloadStatusBadge download={download}/>
                                            </span>
                                        )}
                                        {video.drmProtected ? <DrmBadge onCover/> : video.needsSubscription && <SubscriptionBadge sourceKey={video.sourceKey} onCover/>}
                                        {!image && <FontAwesomeIcon icon={faIcon('fass', 'film')}/>}
                                        {duration && <span className="badge">{duration}</span>}
                                    </span>
                                    <span className="episode-title" title={video.title}>{video.title}</span>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <NoMatches search={searchWords.length > 0} what="videos"/>
                )
            ) : null}
        </section>
    )
}
