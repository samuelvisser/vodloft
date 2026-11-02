import {useEffect, useMemo, useRef, useState} from 'react'
import {canUseSource} from '../lib/access'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'
import {ClearInputButton} from '../components/common/ClearInputButton'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import MediaTypeTabs, {MediaType} from '../components/MediaTypeTabs/MediaTypeTabs'
import {useDailywireMovieCatalog, useDailywireShowCatalog, useMovies, useCollections, useSourceLookup} from '../lib/queries'
import {DAILYWIRE_SOURCE_KEY, SourceFeature, kindName, pluralKindName, sourceHas} from '../types/schemas/source'
import {
    DailywireCatalogMovieRead,
    DailywireCatalogShowRead,
} from '../types/schemas/dailywire_catalog'

type ShowGrouping = 'alphabetical' | 'host'

/** The catalogue on this page is The Daily Wire's, the only Source that can browse so far. */

type BrowsePageProps = {
    onboarding?: boolean
    onCollectionSelect?: (collection: DailywireCatalogShowRead, url: string) => void
    onMovieSelect?: (movie: DailywireCatalogMovieRead, url: string) => void
    onSkip?: () => void
}

function groupCollections(collections: DailywireCatalogShowRead[], grouping: ShowGrouping) {
    const groups = new Map<string, DailywireCatalogShowRead[]>()
    for (const collection of collections) {
        const key = grouping === 'host' ? (collection.authorName || 'Other') : (collection.title[0]?.toUpperCase() || '#')
        const group = groups.get(key) || []
        group.push(collection)
        groups.set(key, group)
    }
    return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right))
}

export default function BrowsePage({onboarding = false, onCollectionSelect, onMovieSelect, onSkip}: BrowsePageProps = {}) {
    const navigate = useNavigate()
    const [params, setParams] = useSearchParams()
    const sources = useSourceLookup()
    const catalogSource = sources.get(DAILYWIRE_SOURCE_KEY)
    const sourceName = catalogSource?.name ?? 'the catalogue'
    // The catalogue is the Source's own, so it uses the Source's word for a collection.
    const collectionName = kindName(catalogSource, 'collection', 'Collection')
    const collectionsName = pluralKindName(collectionName)
    const mayUse = canUseSource(DAILYWIRE_SOURCE_KEY)
    const canBrowse = mayUse && (!catalogSource || sourceHas(catalogSource, SourceFeature.BROWSE))
    const initialType = params.get('type') === 'movies' ? 'movies' : 'collections'
    const [activeType, setActiveType] = useState<MediaType>(initialType)
    const [grouping, setGrouping] = useState<ShowGrouping>('host')
    const [search, setSearch] = useState('')
    const [debouncedSearch, setDebouncedSearch] = useState('')
    useEffect(() => {
        const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250)
        return () => window.clearTimeout(timer)
    }, [search])

    const showCatalog = useDailywireShowCatalog(debouncedSearch, grouping, canBrowse && activeType === 'collections')
    const movieCatalog = useDailywireMovieCatalog(debouncedSearch, canBrowse && activeType === 'movies')
    const {data: localCollections} = useCollections()
    const {data: localMovies} = useMovies()
    const localCollectionsBySlug = useMemo(
        () => new Map(localCollections?.map((collection) => [collection.slug, collection]) ?? []),
        [localCollections],
    )
    const localMovieSlugs = useMemo(
        () => new Set(localMovies?.map((movie) => movie.slug) ?? []),
        [localMovies],
    )

    const collections = useMemo(
        () => showCatalog.data?.pages.flatMap((page) => page.items) || [],
        [showCatalog.data],
    )
    const movies = useMemo(
        () => movieCatalog.data?.pages.flatMap((page) => page.items) || [],
        [movieCatalog.data],
    )
    const groupedCollections = useMemo(() => groupCollections(collections, grouping), [grouping, collections])

    const activeQuery = activeType === 'collections' ? showCatalog : movieCatalog
    const hasItems = activeType === 'collections' ? collections.length > 0 : movies.length > 0
    const loadMoreRef = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        const node = loadMoreRef.current
        if (!node || !activeQuery.hasNextPage || activeQuery.isFetchingNextPage || activeQuery.isFetchNextPageError) return
        const observer = new IntersectionObserver((entries) => {
            if (entries[0]?.isIntersecting) void activeQuery.fetchNextPage()
        }, {rootMargin: '600px'})
        observer.observe(node)
        return () => observer.disconnect()
    }, [activeQuery.fetchNextPage, activeQuery.hasNextPage, activeQuery.isFetchNextPageError, activeQuery.isFetchingNextPage, activeType])

    const chooseType = (type: MediaType) => {
        setActiveType(type)
        setParams({type}, {replace: true})
    }

    const chooseCollection = (collection: DailywireCatalogShowRead) => {
        const url = `https://www.dailywire.com/show/${collection.slug}`
        if (onCollectionSelect) {
            onCollectionSelect(collection, url)
            return
        }
        const localCollection = localCollectionsBySlug.get(collection.slug)
        if (localCollection) {
            navigate(`/collection/${localCollection.slug}`)
            return
        }
        navigate(`/add-collection?url=${encodeURIComponent(url)}`)
    }

    const chooseMovie = (movie: DailywireCatalogMovieRead) => {
        if (onMovieSelect) {
            onMovieSelect(movie, `https://www.dailywire.com/videos/${movie.slug}`)
            return
        }
        navigate(`/movie/${movie.slug}`)
    }

    if (!canBrowse) {
        return (
            <section className="view browse-view" aria-labelledby="browse-title">
                <h1 id="browse-title">Browse</h1>
                <p>{mayUse ? `${sourceName} cannot be browsed.` : `Your account may not use ${sourceName}.`} Paste a link on the Add media page instead.</p>
                <button className="btn btn-primary" type="button" onClick={() => navigate('/add')}>Add media</button>
            </section>
        )
    }

    return (
        <section className={`view browse-view${onboarding ? ' browse-view--onboarding' : ''}`} aria-labelledby="browse-title">
            <div className="view-header">
                <div>
                    <h1 id="browse-title">{onboarding ? 'Add your first media' : `Browse ${sourceName}`}</h1>
                    <p className="view-description">
                        {onboarding
                            ? `Choose a ${collectionName.toLowerCase()} or movie. VODLoft will let you confirm its download location before anything is saved.`
                            : `Choose a ${collectionName.toLowerCase()} or movie to add, view, or download.`}
                    </p>
                </div>
                {onSkip && (
                    <button className="btn" type="button" onClick={onSkip}>
                        Skip for now
                    </button>
                )}
            </div>
            <MediaTypeTabs activeType={activeType} onChange={chooseType} ariaLabel="Browse media type" labels={{collections: collectionsName}}/>
            <div className="browse-toolbar">
                <label className="browse-search">
                    <span className="sr-only">Search {activeType === 'collections' ? collectionsName.toLowerCase() : activeType}</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Search ${activeType}`}/>
                    {search && <ClearInputButton label="Clear the search" onClear={() => setSearch('')}/>}
                </label>
                {activeType === 'collections' && (
                    <div className="compact-switch" role="group" aria-label={`Group ${collectionsName.toLowerCase()}`}>
                        <button type="button" aria-pressed={grouping === 'alphabetical'} onClick={() => setGrouping('alphabetical')}>A–Z</button>
                        <button type="button" aria-pressed={grouping === 'host'} onClick={() => setGrouping('host')}>By host</button>
                    </div>
                )}
            </div>

            {activeQuery.isPending && !hasItems ? <p>Loading the {sourceName} catalogue…</p> : activeQuery.error && !hasItems ? (
                <div className="form-error-card" role="alert">Could not load the {sourceName} catalogue: {activeQuery.error.message}</div>
            ) : !hasItems ? (
                <div className="catalog-empty">
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')}/>
                    <p>No {activeType === 'collections' ? collectionsName.toLowerCase() : activeType} match your search.</p>
                </div>
            ) : activeType === 'collections' ? (
                <div className="catalog-groups">
                    {groupedCollections.map(([label, items], groupIndex) => (
                        <section className="catalog-group" key={label} aria-labelledby={`catalog-${grouping}-${groupIndex}`}>
                            <h2 id={`catalog-${grouping}-${groupIndex}`}>{label}</h2>
                            <div className="catalog-collection-grid">
                                {items.map((collection) => {
                                    const image = toImageUrl(collection.thumbnailPortraitPath || collection.thumbnailLandscapePath || collection.backgroundImagePath)
                                    const added = localCollectionsBySlug.has(collection.slug)
                                    return (
                                        <button className="show-summary-card catalog-show-card" type="button" key={collection.slug} onClick={() => chooseCollection(collection)}>
                                            <span className="collection-summary-art">
                                                {image ? <img src={image} alt="" loading="lazy" decoding="async"/> : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'tv')}/></span>}
                                            </span>
                                            <span className="collection-summary-copy">
                                                <strong className="collection-summary-title">{collection.title}</strong>
                                                <span className="collection-summary-author">{collection.authorName || sourceName}</span>
                                                {collection.description && <span className="collection-summary-description">{collection.description}</span>}
                                            </span>
                                            {added && <span className="catalog-added"><FontAwesomeIcon icon={faIcon('fass', 'check')}/> In library</span>}
                                        </button>
                                    )
                                })}
                            </div>
                        </section>
                    ))}
                </div>
            ) : (
                <div className="movie-poster-grid catalog-movie-grid" role="list" aria-label={`${sourceName} movies`}>
                    {movies.map((movie) => {
                        const image = toImageUrl(movie.thumbnailPortraitPath || movie.thumbnailLandscapePath || movie.backgroundImagePath)
                        const added = localMovieSlugs.has(movie.slug)
                        return (
                            <button className="movie-poster-card" type="button" key={movie.slug} role="listitem" onClick={() => chooseMovie(movie)}>
                                <span className="movie-poster-art">
                                    {image
                                        ? <img src={image} alt="" loading="lazy" decoding="async"/>
                                        : <FontAwesomeIcon icon={faIcon('fass', 'clapperboard')}/>
                                    }
                                    {added && <span className="badge" style={{top: 8, bottom: 'auto'}}>In library</span>}
                                </span>
                                <span className="movie-poster-title">{movie.title}</span>
                                <span className="movie-poster-meta">{movie.authorName || sourceName}</span>
                            </button>
                        )
                    })}
                </div>
            )}

            {activeQuery.hasNextPage && !activeQuery.isFetchNextPageError && (
                <div ref={loadMoreRef} className="catalog-load-more" aria-live="polite" aria-busy={activeQuery.isFetchingNextPage}>
                    {activeQuery.isFetchingNextPage && <><FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin/> Loading more {activeType}…</>}
                </div>
            )}
            {activeQuery.isFetchNextPageError && (
                <div className="catalog-load-error" role="alert">
                    Could not load more {activeType}.
                    <button type="button" className="btn" onClick={() => void activeQuery.fetchNextPage()}>Try again</button>
                </div>
            )}
        </section>
    )
}
