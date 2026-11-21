import {useEffect, useMemo, useState} from 'react'
import {can} from '../lib/access'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import MediaTypeTabs, {MediaType} from '../components/MediaTypeTabs/MediaTypeTabs'
import SourceBadge from '../components/Source/SourceBadge'
import CollectionTile from '../components/CollectionTile/CollectionTile'
import {DrmBadge} from '../components/common/DrmProtected'
import {AccessBadge} from '../components/common/AccessLocked'
import FilterBar, {ChipFilter} from '../components/common/FilterBar'
import DownloadStatusBadge from '../components/DownloadProgress/DownloadStatusBadge'
import CollectionSort, {
    type CollectionSortOrder,
    type LibrarySortable,
    compareCollections,
    DEFAULT_COLLECTION_SORT,
    isCollectionSortOrder,
} from '../components/CollectionSort/CollectionSort'
import {
    useCreators, useLibraryCounts, useLibraryDownloads, useLibraryPreferences, useMovies, useCollectionsView, useSaveLibraryPreferences, useVideos,
} from '../lib/queries'
import {MediaDownloadViewRead} from '../types/schemas/media_download'
import {CollectionTypeReg} from '../types/collection'
import DurationPill from '../components/common/DurationPill'
import './LibraryPage.css'
import {capitalized, creatorKindText} from '../types/creator'
import type {Names} from '../types/schemas/source'
import type {CollectionReadView} from '../types/schemas/collection'
import type {CreatorRead} from '../types/schemas/creator'
import PageHeader, {PageHeaderAction} from '../components/common/PageHeader'
import {wordsOf} from '../lib/collectionWords'

const LIBRARY_COLLECTION_TYPE_FILTER_STORAGE_KEY = 'libraryCollectionTypeFilter'
const LIBRARY_SITE_FILTER_STORAGE_KEY = 'librarySiteFilter'
const LIBRARY_KIND_FILTER_STORAGE_KEY = 'libraryKindFilter'
const KIND_VALUES = ['creator', 'collection']

type Noun = {singular: string, plural: string}

/** What the library's creators are called: as their Sites call them when they all call them the same, such as hosts. */
function creatorNoun(creatorNames: Names[]): Noun {
    const kinds = new Map(creatorNames.map((names) => [names.plural, names]))
    return kinds.size === 1 ? [...kinds.values()][0] : {singular: 'creator', plural: 'creators'}
}
/** Creators and collections. */
function kindOptions(creators: Noun) {
    return [{value: 'creator', label: capitalized(creators.plural)}, {value: 'collection', label: 'Collections'}]
}
const COLLECTION_NOUN: Noun = {singular: 'collection', plural: 'collections'}
const MEDIA_TYPE_NOUNS: Record<MediaType, Noun> = {
    collections: COLLECTION_NOUN,
    movies: {singular: 'movie', plural: 'movies'},
    videos: {singular: 'video', plural: 'videos'},
}
const LIBRARY_COLLECTION_SORT_STORAGE_KEY = 'libraryCollectionSort'

/** The order this browser remembers, for installs without user accounts. */
function loadBrowserCollectionSort(): CollectionSortOrder {
    try {
        const raw = localStorage.getItem(LIBRARY_COLLECTION_SORT_STORAGE_KEY)
        const parsed: unknown = raw === null ? null : JSON.parse(raw)
        return isCollectionSortOrder(parsed) ? parsed : DEFAULT_COLLECTION_SORT
    } catch {
        return DEFAULT_COLLECTION_SORT
    }
}

/** A remembered chip filter: the chosen values, or empty for all of them when nothing usable is stored. */
function loadLibraryChipFilter(storageKey: string): string[] {
    try {
        const raw = localStorage.getItem(storageKey)
        const parsed: unknown = raw === null ? null : JSON.parse(raw)
        return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string') : []
    } catch {
        return []
    }
}

/**
 * The part of a remembered chip filter that still applies: only the values on offer, and all of them
 * (empty) when it would keep every value or none, so nothing stays filtered out without a visible way to clear it.
 */
function applicableChipFilter(selected: readonly string[], values: readonly string[]): string[] {
    const kept = values.filter((value) => selected.includes(value))
    return kept.length === values.length ? [] : kept
}

function matchesChipFilter(value: string, selected: readonly string[]) {
    return selected.length === 0 || selected.includes(value)
}

/** Media whose Site VODLoft has not found yet only shows while every Site does. */
function matchesSiteFilter(item: {site?: {key: string} | null}, selected: readonly string[]) {
    return selected.length === 0 || (!!item.site && selected.includes(item.site.key))
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

/**
 * How well a Collection matches the search, best first: the whole title, the start of the title,
 * the start of words in the title, anywhere in the title, and last the ones only its author matches.
 */
function searchRank(item: {title: string}, words: string[]) {
    const title = foldForSearch(item.title).trim()
    const query = words.join(' ')
    if (title === query) return 0
    if (title.startsWith(query)) return 1
    const titleWords = title.split(/[^\p{L}\p{N}]+/u).filter(Boolean)
    if (words.every((word) => titleWords.some((titleWord) => titleWord.startsWith(word)))) return 2
    if (words.every((word) => title.includes(word))) return 3
    return 4
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
    const [collectionTypeFilter, setCollectionTypeFilter] = useState(() => loadLibraryChipFilter(LIBRARY_COLLECTION_TYPE_FILTER_STORAGE_KEY))
    const [siteFilter, setSiteFilter] = useState(() => loadLibraryChipFilter(LIBRARY_SITE_FILTER_STORAGE_KEY))
    const [kindFilter, setKindFilter] = useState(() => loadLibraryChipFilter(LIBRARY_KIND_FILTER_STORAGE_KEY))
    const [search, setSearch] = useState('')
    const searchWords = useMemo(() => foldForSearch(search).split(/\s+/).filter(Boolean), [search])
    const {data: collections, isLoading: collectionsLoading, error: collectionsError} = useCollectionsView()
    const {data: creators} = useCreators()
    const {data: movies, isLoading: moviesLoading, error: moviesError} = useMovies()
    const {data: videos, isLoading: videosLoading, error: videosError} = useVideos()
    const {data: downloads} = useLibraryDownloads()
    const {data: libraryCounts, error: libraryCountsError} = useLibraryCounts()
    const {data: libraryPreferences, error: libraryPreferencesError} = useLibraryPreferences()
    const saveLibraryPreferences = useSaveLibraryPreferences()
    const [browserCollectionSort, setBrowserCollectionSort] = useState(loadBrowserCollectionSort)
    // With user accounts VODLoft remembers each user's order; without them, the browser does.
    const collectionSort = useMemo<CollectionSortOrder>(() => (libraryPreferences?.saved
        ? {by: libraryPreferences.collectionSort, reversed: libraryPreferences.collectionSortReversed}
        : browserCollectionSort), [libraryPreferences, browserCollectionSort])
    const collectionSortKnown = libraryPreferences !== undefined || !!libraryPreferencesError
    const chooseCollectionSort = (order: CollectionSortOrder) => {
        if (libraryPreferences?.saved) {
            saveLibraryPreferences.mutate({collectionSort: order.by, collectionSortReversed: order.reversed})
            return
        }
        setBrowserCollectionSort(order)
        try {
            localStorage.setItem(LIBRARY_COLLECTION_SORT_STORAGE_KEY, JSON.stringify(order))
        } catch {
            // Without storage the order is only kept while the page is open.
        }
    }
    // Every Site the library has media from, by name.
    const siteOptions = useMemo(() => {
        const names = new Map<string, string>()
        for (const item of [...(collections ?? []), ...(movies ?? []), ...(videos ?? [])]) {
            if (item.site) names.set(item.site.key, item.site.name)
        }
        return [...names].map(([value, label]) => ({value, label}))
            .sort((a, b) => a.label.localeCompare(b.label, undefined, {sensitivity: 'base'}))
    }, [collections, movies, videos])
    // A remembered Site can disappear from the library: only apply the Sites still present.
    const activeSiteFilter = useMemo(
        () => siteOptions.length < 2 ? [] : applicableChipFilter(siteFilter, siteOptions.map((option) => option.value)),
        [siteFilter, siteOptions],
    )
    const activeCollectionTypeFilter = useMemo(
        () => applicableChipFilter(collectionTypeFilter, CollectionTypeReg.values),
        [collectionTypeFilter],
    )
    const hasCreators = !!creators?.length
    const activeKindFilter = useMemo(
        () => hasCreators ? applicableChipFilter(kindFilter, KIND_VALUES) : [],
        [kindFilter, hasCreators],
    )
    // Creators come first. A creator matches a collection type when one of its collections has that type.
    const filteredCreators = useMemo(() => {
        if (!matchesChipFilter('creator', activeKindFilter)) return []
        const typed = new Set((collections ?? [])
            .filter((collection) => collection.creatorSlug && matchesChipFilter(collection.type, activeCollectionTypeFilter))
            .map((collection) => collection.creatorSlug))
        return creators?.filter((creator) => (
            (activeCollectionTypeFilter.length === 0 || typed.has(creator.slug))
            && creator.accounts.some((account) => matchesSiteFilter(account, activeSiteFilter))
            && matchesLibrarySearch({title: creator.title, authorName: creator.accounts[0]?.handle}, searchWords)
        )) ?? []
    }, [creators, collections, activeKindFilter, activeCollectionTypeFilter, activeSiteFilter, searchWords])
    const filteredCollections = useMemo(() => {
        if (!matchesChipFilter('collection', activeKindFilter)) return []
        // A creator's collections are behind its card, unless a search looks for them or the card is filtered out.
        const behindCard = new Set(searchWords.length > 0 ? [] : filteredCreators.map((creator) => creator.slug))
        const shown = collections?.filter((collection) => (
            !(collection.creatorSlug && behindCard.has(collection.creatorSlug))
            && matchesChipFilter(collection.type, activeCollectionTypeFilter) && matchesSiteFilter(collection, activeSiteFilter)
            && matchesLibrarySearch(collection, searchWords)
        )) ?? []
        // While searching, the best matches come first; the chosen order only settles equal matches.
        const ranks = new Map(searchWords.length > 0 ? shown.map((collection) => [collection.slug, searchRank(collection, searchWords)]) : [])
        return shown.sort((a, b) => (
            (ranks.get(a.slug) ?? 0) - (ranks.get(b.slug) ?? 0) || compareCollections(a, b, collectionSort)
        ))
    }, [collections, filteredCreators, activeKindFilter, activeCollectionTypeFilter, activeSiteFilter, searchWords, collectionSort])
    // Creators and collections share the chosen order: a creator counts as opened when its page or one of its
    // collections was, and was released when its first collection was. While searching, creators come first.
    const collectionTiles = useMemo(() => {
        const firstPublished = new Map<string, Date>()
        for (const collection of collections ?? []) {
            const date = collection.firstPublishedDate
            if (!collection.creatorSlug || !date) continue
            const known = firstPublished.get(collection.creatorSlug)
            if (!known || date < known) firstPublished.set(collection.creatorSlug, date)
        }
        type Tile = {sortable: LibrarySortable} & (
            {kind: 'creator', creator: CreatorRead} | {kind: 'collection', collection: CollectionReadView})
        const creatorTiles: Tile[] = filteredCreators.map((creator) => ({
            kind: 'creator', creator,
            sortable: {
                title: creator.title, openCount: creator.openCount, lastOpenedAt: creator.lastOpenedAt,
                firstPublishedDate: firstPublished.get(creator.slug) ?? null, createdAt: new Date(creator.createdAt),
            },
        }))
        const tiles: Tile[] = filteredCollections.map((collection) => ({kind: 'collection', collection, sortable: collection}))
        if (searchWords.length > 0) return [...creatorTiles, ...tiles]
        // The collections are in order already; each creator goes in before the first collection it comes before.
        const sortedCreators = creatorTiles.sort((a, b) => compareCollections(a.sortable, b.sortable, collectionSort))
        const merged: Tile[] = []
        let next = 0
        for (const tile of tiles) {
            while (next < sortedCreators.length && compareCollections(sortedCreators[next].sortable, tile.sortable, collectionSort) <= 0) {
                merged.push(sortedCreators[next++])
            }
            merged.push(tile)
        }
        return [...merged, ...sortedCreators.slice(next)]
    }, [collections, filteredCreators, filteredCollections, searchWords, collectionSort])
    const filteredMovies = useMemo(
        () => movies?.filter((movie) => (
            matchesSiteFilter(movie, activeSiteFilter) && matchesLibrarySearch(movie, searchWords)
        )) ?? [],
        [movies, activeSiteFilter, searchWords],
    )
    const filteredVideos = useMemo(
        () => videos?.filter((video) => (
            matchesSiteFilter(video, activeSiteFilter) && matchesLibrarySearch(video, searchWords)
        )) ?? [],
        [videos, activeSiteFilter, searchWords],
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
                JSON.stringify(collectionTypeFilter),
            )
        } catch {
            // Storage can be unavailable in restricted browser contexts. The filter
            // should still work normally for the current page session in that case.
        }
    }, [collectionTypeFilter])

    useEffect(() => {
        try {
            localStorage.setItem(LIBRARY_SITE_FILTER_STORAGE_KEY, JSON.stringify(siteFilter))
        } catch {
            // As above: without storage the filter just isn't remembered.
        }
    }, [siteFilter])

    useEffect(() => {
        try {
            localStorage.setItem(LIBRARY_KIND_FILTER_STORAGE_KEY, JSON.stringify(kindFilter))
        } catch {
            // As above: without storage the filter just isn't remembered.
        }
    }, [kindFilter])

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
    const showSort = activeType === 'collections' && hasCollections
    const showTypeFilter = activeType === 'collections' && hasCollections
    const showChips = siteOptions.length > 1 || showTypeFilter
    const showKindFilter = showTypeFilter && hasCreators
    const activeFilterCount = (activeSiteFilter.length > 0 ? 1 : 0) + (showTypeFilter && activeCollectionTypeFilter.length > 0 ? 1 : 0)
        + (showKindFilter && activeKindFilter.length > 0 ? 1 : 0)
    const filtered = activeFilterCount > 0 || searchWords.length > 0
    const matchingCount = activeType === 'collections' ? filteredCreators.length + filteredCollections.length
        : activeType === 'movies' ? filteredMovies.length
            : filteredVideos.length
    // Name what the count holds: one kind of tile when the kind filter picks one, "items" when creators and
    // collections show together.
    const creatorsNoun = creatorNoun((creators ?? []).map((creator) => creator.creatorNames))
    const matchingNoun = activeType !== 'collections' ? MEDIA_TYPE_NOUNS[activeType]
        : !showKindFilter ? COLLECTION_NOUN
            : activeKindFilter.length !== 1 ? {singular: 'item', plural: 'items'}
                : activeKindFilter[0] === 'creator' ? creatorsNoun : COLLECTION_NOUN
    const resetFilters = () => {
        setSiteFilter([])
        setCollectionTypeFilter([])
        setKindFilter([])
        setSearch('')
    }

    return (
        <section className="view library-view" aria-labelledby="library-title">
            <PageHeader
                className="library-header"
                title="Library"
                titleId="library-title"
                subtitle={<p className="view-description">{hasCreators ? 'Collections, creators, movies and videos' : 'Collections, movies and videos'} indexed by VODLoft.</p>}
                actions={can('add_media') && <PageHeaderAction icon={faIcon('fass', 'plus')} label="Add media" to="/add"/>}
            >
                {showTabs && (
                    <MediaTypeTabs
                        activeType={activeType}
                        onChange={chooseType}
                        ariaLabel="Library media type"
                        types={presentTypes}
                        counts={typeCounts}
                    />
                )}
            </PageHeader>

            {hasAny && (
                <FilterBar
                    search={search}
                    onSearchChange={setSearch}
                    searchPlaceholder={`Search ${activeType}`}
                    beside={showSort && (
                        <CollectionSort order={collectionSort} onChange={chooseCollectionSort} searching={searchWords.length > 0}/>
                    )}
                    hasFilters={showSort || showChips}
                    activeCount={activeFilterCount}
                    footer={filtered && (
                        <div className="filter-bar-count" aria-live="polite">
                            <strong>{matchingCount.toLocaleString()} matching {matchingCount === 1 ? matchingNoun.singular : matchingNoun.plural}</strong>
                            <button type="button" className="filter-chip-reset" onClick={resetFilters}>Reset filters</button>
                        </div>
                    )}
                >
                    {showChips && (
                        <>
                            {showKindFilter && (
                                <ChipFilter label="Kind" options={kindOptions(creatorsNoun)} selected={activeKindFilter} onChange={setKindFilter}/>
                            )}
                            <ChipFilter label="Site" options={siteOptions} selected={activeSiteFilter} onChange={setSiteFilter}/>
                            {showTypeFilter && (
                                <ChipFilter label="Type" options={CollectionTypeReg.options} selected={activeCollectionTypeFilter} onChange={setCollectionTypeFilter}/>
                            )}
                        </>
                    )}
                </FilterBar>
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
            ) : activeType === 'collections' && hasCollections && (!collections || !collectionSortKnown) ? (
                <LibraryTypeLoading what="collections" error={collectionsError}/>
            ) : activeType === 'movies' && hasMovies && !movies ? (
                <LibraryTypeLoading what="movies" error={moviesError}/>
            ) : activeType === 'videos' && hasVideos && !videos ? (
                <LibraryTypeLoading what="videos" error={videosError}/>
            ) : activeType === 'collections' && hasCollections ? (
                filteredCreators.length + filteredCollections.length > 0 ? (
                    <div className="library-collection-grid" role="list" aria-label="Collections">
                        {collectionTiles.map((tile) => {
                            if (tile.kind === 'collection') {
                                const collection = tile.collection
                                return (
                                    <CollectionTile
                                        key={collection.slug} collection={collection}
                                        // A yt-dlp creator's author is usually the creator itself: do not say its name twice.
                                        subtitle={collection.authorName && !sameName(collection.authorName, collection.title) ? collection.authorName : null}
                                    />
                                )
                            }
                            const creator = tile.creator
                            const avatar = toImageUrl(creator.avatarUrl)
                            const banner = toImageUrl(creator.bannerUrl)
                            return (
                                <Link className="library-tile library-tile--creator" to={`/creator/${creator.slug}`} key={`creator-${creator.slug}`} role="listitem">
                                    <span className="library-tile-art" style={banner ? {backgroundImage: `url("${banner}")`} : undefined}>
                                        {avatar
                                            ? <img className="library-creator-avatar" src={avatar} alt="" loading="lazy" decoding="async"/>
                                            : <span className="library-creator-avatar library-creator-avatar--empty" aria-hidden="true">{creator.title.slice(0, 2).toUpperCase()}</span>}
                                        {creator.accounts.length === 1 && <SourceBadge sourceKey={creator.accounts[0].sourceKey} className="library-tile-source"/>}
                                    </span>
                                    <span className="library-tile-copy">
                                        <span className="library-tile-title">{creator.title}</span>
                                        <span className="library-tile-author">{creatorKindText(creator)}</span>
                                        <span className="library-tile-meta">
                                            <span>{creator.collectionCount} {creator.collectionCount === 1 ? 'collection' : 'collections'}</span>
                                            <span>{wordsOf(creator.words).count(creator.episodeCount)}</span>
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
                            const download = latestVideoDownload(downloads, video.id)
                            return (
                                <Link className="episode-card" to={`/video/${video.id}`} key={video.id} role="listitem" aria-label={video.title}>
                                    <span className="cover" style={image ? {backgroundImage: `url(${image})`} : undefined}>
                                        {download && download.presentation.status !== 'not_downloaded' && (
                                            <span className="status-group" role="list" aria-label="Download status">
                                                <DownloadStatusBadge download={download}/>
                                            </span>
                                        )}
                                        {video.drmProtected ? <DrmBadge onCover/> : video.access && !video.accessGranted && <AccessBadge label={video.accessLabel} description={video.accessDescription} onCover/>}
                                        {!image && <FontAwesomeIcon icon={faIcon('fass', 'film')}/>}
                                        {video.duration > 0 && (
                                            <span className="thumb-corner"><DurationPill seconds={video.duration}/></span>
                                        )}
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
