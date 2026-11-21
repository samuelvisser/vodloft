import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react'
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {siteIcon} from '../../icons/siteIcons'
import {can} from '../../lib/access'
import {apiFetch} from '../../lib/api'
import {checkCreator, combineCreators, useCreator, useCreatorEpisodes, useCreators} from '../../lib/queries'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import EpisodeCard, {toImageUrl} from '../../components/Episode/EpisodeCard'
import {DrmBadge} from '../../components/common/DrmProtected'
import CollectionTile from '../../components/CollectionTile/CollectionTile'
import OpenOnSiteLink from '../../components/common/OpenOnSiteLink'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import ReconcileDialog from '../../components/ReconcileDialog/ReconcileDialog'
import {toast} from '../../lib/toast'
import {creatorKindText, groupNames, joinedNames} from '../../types/creator'
import {useActiveOperation} from '../../components/OperationNotifier/OperationNotifier'
import {placedSections} from './CreatorSectionsEditor'
import CreatorHeader from './CreatorHeader'
import CreatorNotInLibrary from './CreatorNotInLibrary'
import './CreatorPages.css'
import {CollectionWords, wordsOf} from '../../lib/collectionWords'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length === 1) return titles[0]
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
}

/** How a creator's links to their Sites show: by name, as their Sites' icons, or in the Actions menu. */
type LinkFit = 'names' | 'icons' | 'menu'
const LINK_FITS: LinkFit[] = ['names', 'icons', 'menu']

/**
 * The fullest way the creator's links fit in one row beside the other buttons: their Sites' names, else their icons,
 * else the Actions menu, for a user who has that menu (`menu`). It measures again whenever the page's width or the
 * number of links changes.
 */
function useLinkFit(count: number, menu: boolean) {
    const ref = useRef<HTMLDivElement>(null)
    const [width, setWidth] = useState(0)
    const key = `${count}:${width}`
    const [measured, setMeasured] = useState<{key: string, fit: LinkFit}>({key, fit: 'names'})
    const fit = measured.key === key ? measured.fit : 'names'
    const last: LinkFit = menu ? 'menu' : 'icons'
    useEffect(() => {
        const row = ref.current?.parentElement
        if (!row) return
        const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)))
        observer.observe(row)
        return () => observer.disconnect()
        // The row shows once the creator has loaded, with their links.
    }, [count])
    useLayoutEffect(() => {
        const element = ref.current
        if (!element || fit === last) return
        // The row ends on the right on a computer, where scrollWidth misses what overflows on the left: measure the buttons.
        const buttons = [...element.children].map((child) => child.getBoundingClientRect())
        const used = buttons.length ? Math.max(...buttons.map((box) => box.right)) - Math.min(...buttons.map((box) => box.left)) : 0
        if (used > element.clientWidth + 1) setMeasured({key, fit: LINK_FITS[LINK_FITS.indexOf(fit) + 1]})
    }, [key, fit, last])
    return {ref, fit}
}

/** How long ago something happened, in words: "2 days ago". */
function timeAgo(date: Date) {
    const seconds = (date.getTime() - Date.now()) / 1000
    const format = new Intl.RelativeTimeFormat(undefined, {numeric: 'auto'})
    for (const [unit, size] of [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600]] as const) {
        if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit)
    }
    return format.format(Math.round(seconds / 60), 'minute')
}

/** A row of episodes that scrolls sideways, with buttons to scroll it on a computer. */
function EpisodeShelf({slug, words}: {slug: string, words: CollectionWords}) {
    const {data, hasNextPage, isFetchingNextPage, fetchNextPage} = useCreatorEpisodes(slug)
    const episodes = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
    // The next page loads when the end of the row comes near, as the user scrolls it on.
    const loadMore = useCallback(() => { if (!isFetchingNextPage) void fetchNextPage() }, [isFetchingNextPage, fetchNextPage])
    const {rootRef: row, endRef} = useLoadMoreOnScroll<HTMLDivElement, HTMLDivElement>(!!hasNextPage, loadMore)
    if (!episodes.length) return null
    const scroll = (direction: number) => row.current?.scrollBy({left: direction * row.current.clientWidth * 0.8, behavior: 'smooth'})
    return (
        <section className="creator-section-group" aria-labelledby="creator-newest-title">
            <div className="creator-shelf-head">
                <h2 id="creator-newest-title">Newest {words.episode.plural}</h2>
                <div className="creator-shelf-arrows">
                    <button type="button" className="btn" onClick={() => scroll(-1)} aria-label="Scroll back">
                        <FontAwesomeIcon icon={faIcon('fass', 'chevron-left')}/>
                    </button>
                    <button type="button" className="btn" onClick={() => scroll(1)} aria-label="Scroll on">
                        <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')}/>
                    </button>
                </div>
            </div>
            <div className="episodes-row creator-shelf" role="list" ref={row}>
                {episodes.map((episode) => (
                    <EpisodeCard key={episode.id} ep={episode} collectionSlug={episode.collectionSlug} collectionTitle={episode.collectionTitle} words={words}/>
                ))}
                {hasNextPage && <div ref={endRef} className="creator-shelf-more" aria-hidden="true"/>}
            </div>
        </section>
    )
}

export default function CreatorPage() {
    const {slug} = useParams()
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const {data: creator, error} = useCreator(slug)
    // Moving feeds and playlists, started by saving the Edit page.
    const moveOperation = useActiveOperation('creator.move_sections', 'creator', creator?.id ?? null)
    // Count each visit once, so the Library can list the most used creators first.
    const countedVisit = useRef<string | null>(null)
    useEffect(() => {
        if (!slug || countedVisit.current === slug) return
        countedVisit.current = slug
        apiFetch(`/creators/${encodeURIComponent(slug)}/opened`, {method: 'POST'}).catch(() => {
            // Only the Library's order misses this visit.
        })
    }, [slug])
    const [actionError, setActionError] = useState<string | null>(null)
    const [checking, setChecking] = useState(false)
    // The Move action's dialog, which Home links to as well.
    const [searchParams, setSearchParams] = useSearchParams()
    const reconciling = searchParams.get('move') === '1'
    const setReconciling = (open: boolean) => setSearchParams((current) => {
        const next = new URLSearchParams(current)
        if (open) next.set('move', '1')
        else next.delete('move')
        return next
    }, {replace: true})
    const [combining, setCombining] = useState(false)
    const [combineWith, setCombineWith] = useState('')
    const {data: libraryCreators} = useCreators()
    const others = useMemo(
        () => (libraryCreators ?? []).filter((other) => other.slug !== slug),
        [libraryCreators, slug],
    )
    const combineRegistry = useMemo(() => createSelectRegistry(`CombineCreator-${slug}-${others.length}`, {
        '': {label: 'Pick a creator'},
        ...Object.fromEntries(others.map((other) => [other.slug, {label: `${other.title} (${other.kind})`}])),
    }), [others, slug])

    const linkFit = useLinkFit(creator?.accounts.filter((account) => account.url).length ?? 0, can('library', 'manage'))

    // Right after the page opens, before its request starts, there is no creator yet and no error either.
    if (!creator && !error) return <section className="view"><p>Loading…</p></section>
    if (error || !creator) {
        return (
            <section className="view">
                <div className="form-error-card" role="alert">{error?.message ?? 'This creator was not found'}</div>
            </section>
        )
    }

    const mayManage = can('library', 'manage')
    const check = async () => {
        setChecking(true)
        setActionError(null)
        try {
            await checkCreator(creator.slug)
        } catch (exc) {
            setActionError(exc instanceof Error ? exc.message : String(exc))
            setChecking(false)
        }
    }
    const combine = async () => {
        if (!combineWith) return
        try {
            const page = await combineCreators(creator.slug, combineWith)
            queryClient.setQueryData(['creator', slug], page)
            await queryClient.invalidateQueries({queryKey: ['creators']})
            await queryClient.invalidateQueries({queryKey: ['collection']})
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            toast.success(`${others.find((other) => other.slug === combineWith)?.title ?? 'The creator'} is now part of ${creator.title}`)
            setCombining(false)
            setCombineWith('')
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        }
    }

    const several = creator.accounts.length > 1
    // The collections that take an account's uploads, and decide where its new lists land. On a creator with several
    // accounts, each one's badge names its Site, such as "YouTube main collection".
    const mainBadges = new Map(creator.accounts.filter((account) => account.mainCollectionSlug).map((account) => [
        account.mainCollectionSlug!, several ? `${account.site.name} main collection` : 'Main collection',
    ]))
    // The feeds and playlists whose place the Edit page changes, named together, such as "feeds and playlists".
    const placed = placedSections(creator).map(({section}) => section)
    const placedNames = placed.length ? joinedNames(placed.map((section) => groupNames(section, placed))) : null
    const links = creator.accounts.filter((account) => account.url).map((account) => ({
        siteName: account.site.name, site: account.site, url: account.url!,
    }))
    // The links show their Sites' names while those fit, then just their icons, and else go into the Actions menu.
    const linkButtons = linkFit.fit === 'menu' ? [] : links
    const episodes = creator.collections.reduce((total, collection) => total + collection.episodeCount, 0)
    const words = wordsOf(creator.words)
    const fileWords = words
    // The downloaded episodes that wait to go to another collection, or another season of theirs.
    const waitingCount = creator.reassignedCount + creator.movedCount
    const firstDates = creator.collections.map((collection) => collection.firstPublishedDate).filter((date): date is Date => !!date)
    const since = firstDates.length ? Math.min(...firstDates.map((date) => date.getFullYear())) : null
    const newest = creator.lastPublishedDate

    return (
        <section className="view creator-view" aria-labelledby="creator-title">
            <CreatorHeader
                title={creator.title} label={creatorKindText(creator)} actionsRef={linkFit.ref}
                handle={creator.accounts[0]?.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts}
                description={creator.description} titleId="creator-title"
                stats={(creator.collections.length > 0 || creator.movies.length > 0) && (
                    <ul className="creator-stats">
                        <li><b>{creator.collections.length}</b> {creator.collections.length === 1 ? 'collection' : 'collections'}</li>
                        {creator.movies.length > 0 && <li><b>{creator.movies.length}</b> {creator.movies.length === 1 ? 'movie' : 'movies'}</li>}
                        <li><b>{episodes}</b> {episodes === 1 ? words.episode.singular : words.episode.plural}</li>
                        {since && <li>Since <b>{since}</b></li>}
                        {newest && <li>Newest <b>{timeAgo(newest)}</b></li>}
                    </ul>
                )}
                actions={(linkButtons.length > 0 || mayManage) && (
                    <>
                        {linkButtons.map((link) => <OpenOnSiteLink key={link.url} url={link.url} siteName={link.siteName} site={link.site} iconOnly={linkFit.fit === 'icons'}/>)}
                        {mayManage && (
                            <>
                                <PageHeaderAction icon={faIcon('fass', 'pen')} label="Edit" variant="secondary" to={`/edit-creator/${creator.slug}`}/>
                                <ActionMenu items={[{
                                    label: checking ? 'Looking…' : 'Check now',
                                    description: `Look for new ${creator.newListNames.plural}`,
                                    icon: faIcon('fass', 'arrows-rotate'),
                                    disabled: checking,
                                    onSelect: () => void check(),
                                }, ...(linkButtons.length ? [] : links.map((link) => ({
                                    label: `Open on ${link.siteName}`,
                                    // The menu names the site, so a site without an icon of its own shows just the globe.
                                    icon: siteIcon(link.site.icon) ?? faIcon('fass', 'globe'),
                                    onSelect: () => window.open(link.url, '_blank', 'noreferrer'),
                                }))),
                                {
                                    label: `Move ${fileWords.episode.plural}`,
                                    description: waitingCount
                                        ? `${waitingCount} downloaded ${waitingCount === 1 ? `${fileWords.episode.singular} belongs` : `${fileWords.episode.plural} belong`} in another ${creator.movedCount ? `collection or ${words.season.singular}` : 'collection'} now`
                                        : `Moves Reassigned and Moved ${fileWords.episode.plural} to where they belong`,
                                    icon: faIcon('fass', 'arrow-right-from-bracket'),
                                    disabled: !waitingCount,
                                    disabledReason: waitingCount ? undefined : `Every ${fileWords.episode.singular} of this ${creator.creatorNames.singular} is where it belongs.`,
                                    onSelect: () => setReconciling(true),
                                }, {
                                    label: 'Combine with another creator',
                                    description: 'The same person or group, added from another site or twice',
                                    icon: faIcon('fass', 'object-group'),
                                    disabled: !others.length,
                                    disabledReason: others.length ? undefined : 'There is no other creator in your library.',
                                    onSelect: () => setCombining(true),
                                }, ...(placedNames ? [{
                                    label: `Move ${placedNames.plural}`,
                                    description: 'Choose where they go on the Edit page',
                                    icon: faIcon('fass', 'arrow-right-arrow-left'),
                                    // Saving the Edit page starts it; while it runs, its progress shows here.
                                    operation: moveOperation,
                                    onSelect: () => navigate(`/edit-creator/${creator.slug}`),
                                }] : [])]}/>
                            </>
                        )}
                    </>
                )}
            />

            {checking && (
                <p className="creator-note" role="status">
                    VODLoft is looking for new {creator.newListNames.plural}. New ones show under Collections when it is done.
                </p>
            )}
            {actionError && <div className="form-error-card" role="alert">{actionError}</div>}

            {(creator.collections.length > 0 || !creator.movies.length) && <div className="creator-section-group">
                <h2 className="creator-collections-title">Collections</h2>
                {creator.collections.length ? (
                    <div className="library-collection-grid" role="list" aria-label="Collections">
                        {creator.collections.map((collection) => (
                            <CollectionTile
                                key={collection.slug} collection={collection} showSource={several}
                                badge={mainBadges.get(collection.slug) ?? null}
                                // Where it comes from, unless that is just its own title.
                                subtitle={collection.links.length > 1 || (collection.links.length === 1 && collection.links[0] !== collection.title)
                                    ? listedSources(collection.links) : null}
                            />
                        ))}
                    </div>
                ) : (
                    <p className="creator-empty">
                        None of this {creator.creatorNames.singular}'s collections are in your library any more.
                        {mayManage && <> Add some on the <Link to={`/edit-creator/${creator.slug}`}>Edit page</Link>.</>}
                    </p>
                )}
            </div>}

            {/* After the collections, which are what people open most. */}
            <EpisodeShelf slug={creator.slug} words={words}/>

            {creator.movies.length > 0 && (
                <div className="creator-section-group">
                    <h2 className="creator-collections-title">Movies</h2>
                    <div className="movie-poster-grid" role="list" aria-label="Movies">
                        {creator.movies.map((movie) => {
                            const image = toImageUrl(
                                movie.thumbnailPortraitPath || movie.thumbnailLandscapePath || movie.backgroundImagePath || movie.logoImagePath,
                            )
                            const year = (movie.releaseDate ?? '').slice(0, 4) || (movie.publishedAt ? String(movie.publishedAt.getFullYear()) : '')
                            return (
                                <Link className="movie-poster-card" to={`/movie/${movie.slug}`} key={movie.slug} role="listitem">
                                    <span className="movie-poster-art">
                                        {image
                                            ? <img src={image} alt="" loading="lazy" decoding="async"/>
                                            : <FontAwesomeIcon icon={faIcon('fass', 'clapperboard')}/>}
                                        {movie.drmProtected && <DrmBadge onCover/>}
                                    </span>
                                    <span className="movie-poster-title">{movie.title}</span>
                                    {year && <span className="movie-poster-meta">{year}</span>}
                                </Link>
                            )
                        })}
                    </div>
                </div>
            )}

            <CreatorNotInLibrary creator={creator}/>

            <ReconcileDialog
                open={reconciling}
                path={`/creators/${encodeURIComponent(creator.slug)}`}
                what={`the ${fileWords.episode.plural} of ${creator.title}`}
                onDismiss={() => setReconciling(false)}
            />

            <ConfirmDialog
                open={combining}
                title={`Combine ${creator.title} with another creator`}
                icon={faIcon('fass', 'object-group')}
                onDismiss={() => setCombining(false)}
                confirmButton={{label: 'Combine', onClick: combine, disabled: !combineWith}}
            >
                <div className="form-row">
                    <label htmlFor="combine-creator">Who is the same person or group</label>
                    <SimpleSelect
                        inputId="combine-creator" registry={combineRegistry} value={combineWith}
                        menuPortalTarget={document.body} menuPlacement="auto"
                        styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                        onChange={(value) => setCombineWith(value ?? '')}
                    />
                </div>
                <ul className="creator-order-note">
                    <li>Their accounts and collections become {creator.title}'s, and they leave your library as a creator of their own.</li>
                    <li>Collections keep their {words.season.plural}, {words.episode.plural}, profiles and files. Nothing is indexed again.</li>
                    <li>{creator.title}'s name, picture and settings stay.</li>
                </ul>
            </ConfirmDialog>
        </section>
    )
}
