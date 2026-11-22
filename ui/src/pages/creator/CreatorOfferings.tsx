import {useState} from 'react'
import {Link, useNavigate} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addCollectionToCreator, addCreatorMovies, useCreatorOfferings} from '../../lib/queries'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import CollectionTileArt from '../../components/CollectionTileArt/CollectionTileArt'
import {joinedNames} from '../../types/creator'
import type {CreatorOffering, CreatorPageRead} from '../../types/schemas/creator'

// Tiles shown before "Show all": two rows on a computer, two on a phone.
const DESKTOP_TILES = 12
const PHONE_TILES = 4

type Item = {accountId: number, siteName: string, offering: CreatorOffering}

/** Whether the Library has the show or movie as one of this creator's already. */
const joined = ({offering}: Item) => offering.kind === 'show' ? offering.collectionJoined : offering.movieJoined

/**
 * What the creator has at their Sites beside their channel and the Library does not have as theirs yet, such as a
 * Daily Wire host's other shows and movies: one folded line until the user opens it, then faded Library tiles with a
 * button that adds each one.
 */
export default function CreatorOfferings({creator}: {creator: CreatorPageRead}) {
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const offers = creator.accounts.some((account) => account.offers)
    const {data, isLoading, error} = useCreatorOfferings(creator.slug, offers)
    const [open, setOpen] = useState(false)
    const [showAll, setShowAll] = useState(false)
    const [busy, setBusy] = useState<string | null>(null)
    if (!offers) return null
    if (isLoading) {
        return (
            <p className="creator-note" role="status">
                <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Looking up what else {creator.title} has…
            </p>
        )
    }
    if (error) return <p className="creator-note" role="alert">Could not look up what else {creator.title} has: {error.message}</p>
    const several = creator.accounts.length > 1
    const items: Item[] = (data?.accounts ?? [])
        .flatMap((account) => account.offerings.map((offering) => ({accountId: account.accountId, siteName: account.site.name, offering})))
        .filter((item) => !joined(item))
    if (!items.length) return null

    const mayAdd = can('add_media')
    const key = ({accountId, offering}: Item) => `${accountId}:${offering.ref}`
    const nouns = joinedNames([...new Map(items.map(({offering}) => [offering.names.plural, offering.names])).values()])
    const counted = `${items.length} more ${items.length === 1 ? nouns.singular : nouns.plural}`
    const arts = items.map(({offering}) => toImageUrl(offering.imageUrl)).filter((url): url is string => !!url).slice(0, 4)

    const refresh = async (movies: boolean) => {
        await Promise.all([
            queryClient.invalidateQueries({queryKey: ['creator', creator.slug]}),
            queryClient.invalidateQueries({queryKey: ['creators']}),
            queryClient.invalidateQueries({queryKey: ['collectionsView']}),
            ...(movies ? [queryClient.invalidateQueries({queryKey: ['movies']})] : []),
        ])
    }
    const add = async (item: Item) => {
        const {offering} = item
        // A show not in the Library is added with the Add Collection wizard, which adds it to this creator.
        if (offering.kind === 'show' && !offering.collectionSlug) {
            navigate(`/add-collection?url=${encodeURIComponent(offering.url)}&creator=${encodeURIComponent(creator.slug)}`)
            return
        }
        setBusy(key(item))
        try {
            if (offering.kind === 'show') await addCollectionToCreator(offering.collectionSlug!, creator.slug)
            else queryClient.setQueryData(['creator', creator.slug], await addCreatorMovies(creator.slug, item.accountId, [offering.ref]))
            await refresh(offering.kind === 'item')
            toast.success(`${offering.title} is now part of ${creator.title}`)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(null)
        }
    }

    const away = items.some(({offering}) => offering.collectionSlug || offering.movieSlug) ? `not with ${creator.title}` : 'not in your library'
    return (
        <section className={`creator-more${open ? ' is-open' : ''}`} aria-label="Not in your library">
            <div className="creator-more-head" onClick={(event) => { if (event.target === event.currentTarget) setOpen(!open) }}>
                <button type="button" className="creator-more-summary" aria-expanded={open} onClick={() => setOpen(!open)}>
                    {arts.length > 0 && (
                        <span className="creator-more-stack" aria-hidden="true">
                            {arts.map((url) => <img key={url} src={url} alt="" loading="lazy"/>)}
                        </span>
                    )}
                    <span className="creator-more-text">
                        <b>
                            <span className="creator-more-long">{creator.title} has {counted}</span>
                            <span className="creator-more-short">{counted}</span>
                        </b>
                        <span className="creator-more-sub">
                            {open
                                ? `${away[0].toUpperCase()}${away.slice(1)} yet${mayAdd ? `: add ${items.length === 1 ? 'it' : 'any of them'} with its + button` : ''}`
                                : `${items.length === 1 ? 'It is' : 'They are'} ${away}`}
                        </span>
                    </span>
                </button>
                <button type="button" className="btn btn-secondary creator-more-toggle" aria-expanded={open} onClick={() => setOpen(!open)} tabIndex={-1}>
                    <span className="creator-more-toggle-label">{open ? 'Hide' : 'Show'}</span>
                    <FontAwesomeIcon icon={faIcon('fass', open ? 'chevron-up' : 'chevron-down')} aria-hidden="true"/>
                </button>
            </div>
            {open && (
                <div className="creator-more-body">
                    <div className={`creator-more-grid${showAll ? '' : ' is-cut'}`} role="list">
                        {items.map((item) => {
                            const {offering} = item
                            const image = toImageUrl(offering.imageUrl)
                            const inLibrary = offering.collectionSlug ?? offering.movieSlug
                            const facts = [
                                offering.names.singular[0].toUpperCase() + offering.names.singular.slice(1),
                                offering.year, inLibrary ? 'In your library' : null, several ? item.siteName : null,
                            ].filter(Boolean).join(' · ')
                            return (
                                <div key={key(item)} role="listitem" className={`creator-more-tile${mayAdd ? ' is-addable' : ''}`}>
                                    <span className="library-tile-art creator-more-art">
                                        {image
                                            ? <CollectionTileArt key={image} src={image}/>
                                            : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', offering.kind === 'item' ? 'film' : 'list')}/></span>}
                                    </span>
                                    {mayAdd && (
                                        <div className="creator-more-add">
                                            <button
                                                type="button" className="btn btn-secondary creator-more-plus" disabled={busy !== null}
                                                aria-label={`Add ${offering.title}`} title={inLibrary ? `Add to ${creator.title}` : 'Add to your library'}
                                                onClick={() => void add(item)}
                                            >
                                                <FontAwesomeIcon icon={faIcon('fass', busy === key(item) ? 'spinner' : 'plus')} spin={busy === key(item)}/>
                                            </button>
                                        </div>
                                    )}
                                    <span className="library-tile-copy">
                                        {offering.collectionSlug
                                            ? <Link className="library-tile-title" to={`/collection/${offering.collectionSlug}`}>{offering.title}</Link>
                                            : offering.movieSlug
                                                ? <Link className="library-tile-title" to={`/movie/${offering.movieSlug}`}>{offering.title}</Link>
                                                : <span className="library-tile-title">{offering.title}</span>}
                                        {facts && <span className="library-tile-meta"><span>{facts}</span></span>}
                                    </span>
                                </div>
                            )
                        })}
                    </div>
                    {!showAll && items.length > PHONE_TILES && (
                        <div className={`creator-more-all${items.length > DESKTOP_TILES ? '' : ' is-phone-only'}`}>
                            <button type="button" className="btn btn-secondary" onClick={() => setShowAll(true)}>Show all {items.length}</button>
                        </div>
                    )}
                </div>
            )}
        </section>
    )
}
