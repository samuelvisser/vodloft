import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import {useShows, useSourceLookup, useSourceSearch} from '../lib/queries'
import {SearchResultRead, SourceFeature, sourceHas} from '../types/schemas/source'

const KIND_LABEL: Record<SearchResultRead['kind'], string> = {
    show: 'Show',
    movie: 'Movie',
    episode: 'Episode',
    video: 'Video',
}

/** Browse a Source that has no catalogue by searching it. */
export default function SourceSearchPage() {
    const navigate = useNavigate()
    const {sourceId} = useParams()
    const [params, setParams] = useSearchParams()
    const source = useSourceLookup().get(sourceId ?? '')
    const canSearch = sourceHas(source, SourceFeature.SEARCH)
    const [search, setSearch] = useState(params.get('q') ?? '')
    const [query, setQuery] = useState(search.trim())
    useEffect(() => {
        const timer = window.setTimeout(() => {
            const value = search.trim()
            setQuery(value)
            // Keep the search in the link, so going back returns to the same results.
            if ((params.get('q') ?? '') !== value) setParams(value ? {q: value} : {}, {replace: true})
        }, 400)
        return () => window.clearTimeout(timer)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search])
    const results = useSourceSearch(canSearch ? sourceId : undefined, query)
    const {data: localShows} = useShows()
    const sourceName = source?.name ?? sourceId ?? 'this service'

    const choose = (result: SearchResultRead) => {
        if (result.kind === 'show') {
            const local = localShows?.find((show) => show.sourceKey === sourceId && show.slug === result.slug)
            navigate(local ? `/show/${local.slug}` : `/add-show?url=${encodeURIComponent(result.url)}`)
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
                    <p className="view-description">Find a series or programme to add, view, or download.</p>
                </div>
            </div>
            <div className="browse-toolbar">
                <label className="browse-search">
                    <span className="sr-only">Search {sourceName}</span>
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input autoFocus value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by name"/>
                </label>
            </div>

            {!query ? null : results.isPending ? <p>Searching {sourceName}…</p> : results.error ? (
                <div className="form-error-card" role="alert">{results.error.message}</div>
            ) : !results.data.length ? (
                <div className="catalog-empty">
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')}/>
                    <p>Nothing at {sourceName} matches your search.</p>
                </div>
            ) : (
                <div className="catalog-show-grid" role="list" aria-label={`${sourceName} results`}>
                    {results.data.map((result) => {
                        const image = toImageUrl(result.imageUrl)
                        const added = result.kind === 'show' && localShows?.some((show) => show.sourceKey === sourceId && show.slug === result.slug)
                        return (
                            <button className="show-summary-card catalog-show-card" type="button" role="listitem" key={`${result.kind}-${result.slug}`} onClick={() => choose(result)}>
                                <span className="show-summary-art">
                                    {image ? <img src={image} alt="" loading="lazy" decoding="async"/> : <span className="show-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', 'tv')}/></span>}
                                </span>
                                <span className="show-summary-copy">
                                    <strong className="show-summary-title">{result.title}</strong>
                                    <span className="show-summary-author">{[KIND_LABEL[result.kind], result.authorName].filter(Boolean).join(' · ')}</span>
                                    {result.description && <span className="show-summary-description">{result.description}</span>}
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
