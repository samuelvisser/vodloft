import {useEffect, useState} from 'react'
import {canUseSource} from '../lib/access'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'
import {ClearInputButton} from '../components/common/ClearInputButton'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import {useCollections, useSourceLookup, useSourceSearch} from '../lib/queries'
import {SearchNoticeRead, SearchResultRead, SourceFeature, kindName, searchName, sourceHas} from '../types/schemas/source'
import {SubscriptionBadge} from '../components/common/NeedsSubscription'

const KIND_LABEL: Record<SearchResultRead['kind'], string> = {
    collection: 'Collection',
    movie: 'Movie',
    episode: 'Episode',
    video: 'Video',
}

/** How the search was answered, such as through an API or a slower fallback. */
function SearchNotice({notice}: {notice: SearchNoticeRead}) {
    return (
        <p className={`search-notice search-notice--${notice.tone}`} role="status">
            <span className="search-notice__badge">{notice.badge}</span>
            <span>
                {notice.text}
                {notice.linkLabel && notice.linkPath && <> <Link to={notice.linkPath}>{notice.linkLabel}</Link></>}
            </span>
        </p>
    )
}

type SourceSearchPageProps = {
    /** The Source to search, when it does not come from the page's address. */
    sourceId?: string
    /** What choosing a result does, instead of opening the page that adds it. */
    onChoose?: (result: SearchResultRead) => void
}

/** Browse a Source that has no catalogue by searching it. */
export default function SourceSearchPage({sourceId: givenSourceId, onChoose}: SourceSearchPageProps = {}) {
    const navigate = useNavigate()
    const routeParams = useParams()
    const sourceId = givenSourceId ?? routeParams.sourceId
    const [params, setParams] = useSearchParams()
    const source = useSourceLookup().get(sourceId ?? '')
    const canSearch = sourceHas(source, SourceFeature.SEARCH) && canUseSource(source?.id ?? '')
    // Each search costs something at such a Source, so it searches on Enter instead of while typing.
    const onEnter = sourceHas(source, SourceFeature.COSTLY_SEARCH)
    const [search, setSearch] = useState(params.get('q') ?? '')
    const [query, setQuery] = useState(search.trim())
    const submit = (value: string) => {
        setQuery(value)
        // Keep the search in the link, so going back returns to the same results.
        if ((params.get('q') ?? '') !== value) setParams(value ? {q: value} : {}, {replace: true})
    }
    useEffect(() => {
        if (onEnter) return
        const timer = window.setTimeout(() => submit(search.trim()), 400)
        return () => window.clearTimeout(timer)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search, onEnter])
    const results = useSourceSearch(canSearch ? sourceId : undefined, query)
    const searching = !!query && results.isFetching
    const {data: localCollections} = useCollections()
    const sourceName = searchName(source) ?? sourceId ?? 'this service'

    const choose = (result: SearchResultRead) => {
        if (onChoose) {
            onChoose(result)
            return
        }
        if (result.kind === 'collection') {
            const local = localCollections?.find((collection) => collection.sourceKey === sourceId && collection.slug === result.slug)
            navigate(local ? `/collection/${local.slug}` : `/add-collection?url=${encodeURIComponent(result.url)}`)
            return
        }
        navigate(`/add?url=${encodeURIComponent(result.url)}`)
    }

    if (source && !canSearch) {
        return (
            <section className="view browse-view" aria-labelledby="browse-title">
                <h1 id="browse-title">Browse</h1>
                <p>{sourceName} cannot be searched. Paste a link on the Add media page instead.</p>
                <button className="btn btn-primary" type="button" onClick={() => navigate('/add')}>Add media</button>
            </section>
        )
    }

    return (
        <section className="view browse-view" aria-labelledby="browse-title">
            <div className="view-header">
                <div>
                    <h1 id="browse-title">Search {sourceName}</h1>
                    <p className="view-description">Find a collection or video to add, view, or download.</p>
                </div>
            </div>
            <form className={`browse-toolbar${onEnter ? ' browse-toolbar--submit' : ''}`} role="search" onSubmit={(event) => {
                event.preventDefault()
                submit(search.trim())
            }}>
                <label className="browse-search has-clear-button">
                    <span className="sr-only">Search {sourceName}</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input type="search" enterKeyHint="search" autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by name"/>
                    {search && <ClearInputButton label="Clear the search" onClear={() => {
                        setSearch('')
                        submit('')
                    }}/>}
                </label>
                {onEnter && (
                    <button className="btn btn-primary browse-search__submit" type="submit" disabled={searching || !search.trim()}>
                        {searching ? 'Searching…' : 'Search'}
                    </button>
                )}
            </form>

            {query && results.data?.notice && <SearchNotice notice={results.data.notice}/>}

            {!query ? null : results.isPending ? <p>Searching {sourceName}…</p> : results.error ? (
                <div className="form-error-card" role="alert">{results.error.message}</div>
            ) : !results.data.results.length ? (
                <div className="catalog-empty">
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')}/>
                    <p>Nothing at {sourceName} matches your search.</p>
                </div>
            ) : (
                <div className="catalog-collection-grid" role="list" aria-label={`${sourceName} results`}>
                    {results.data.results.map((result) => {
                        const image = toImageUrl(result.imageUrl)
                        const added = result.kind === 'collection' && localCollections?.some((collection) => collection.sourceKey === sourceId && collection.slug === result.slug)
                        return (
                            <button className="collection-summary-card catalog-collection-card" type="button" role="listitem" key={`${result.kind}-${result.slug}`} onClick={() => choose(result)}>
                                <span className="collection-summary-art">
                                    {image ? <img src={image} alt="" loading="lazy" decoding="async"/> : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'tv')}/></span>}
                                </span>
                                <span className="collection-summary-copy">
                                    <strong className="collection-summary-title">{result.title}</strong>
                                    <span className="collection-summary-author">{[result.kindLabel ?? kindName(source, result.kind, KIND_LABEL[result.kind]), result.authorName, ...(result.facts ?? [])].filter(Boolean).join(' · ')}</span>
                                    {result.description && <span className="collection-summary-description">{result.description}</span>}
                                    {result.needsSubscription && <span><SubscriptionBadge sourceKey={sourceId}/></span>}
                                </span>
                                {added && <span className="catalog-added"><FontAwesomeIcon icon={faIcon('fass', 'check')}/> In library</span>}
                            </button>
                        )
                    })}
                </div>
            )}
        </section>
    )
}
