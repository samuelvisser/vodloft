import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {siteIcon} from '../../icons/siteIcons'
import {can} from '../../lib/access'
import {apiFetch} from '../../lib/api'
import {combineCreators, splitCreatorAccount, useCreator, useCreatorEpisodes, useCreators} from '../../lib/queries'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import EpisodeCard, {toImageUrl} from '../../components/Episode/EpisodeCard'
import {DrmBadge} from '../../components/common/DrmProtected'
import CollectionTile from '../../components/CollectionTile/CollectionTile'
import SiteLink from '../../components/common/SiteLink'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import {toast} from '../../lib/toast'
import {creatorKindText} from '../../types/creator'
import CreatorHeader from './CreatorHeader'
import CreatorOfferings from './CreatorOfferings'
import './CreatorPages.css'
import {CollectionWords, wordsOf} from '../../lib/collectionWords'
import {nameInText} from '../../lib/nameInText'

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
                    <EpisodeCard key={episode.id} ep={episode} collectionSlug={episode.collectionSlug} collectionTitle={episode.collectionTitle} words={words} unplayableAllowed={episode.unplayableFormatsAllowed}/>
                ))}
                {hasNextPage && <div ref={endRef} className="creator-shelf-more" aria-hidden="true"/>}
            </div>
        </section>
    )
}

export default function CreatorPage() {
    const {slug} = useParams()
    const queryClient = useQueryClient()
    const {data: creator, error} = useCreator(slug)
    // Count each visit once, so the Library can list the most used creators first.
    const countedVisit = useRef<string | null>(null)
    useEffect(() => {
        if (!slug || countedVisit.current === slug) return
        countedVisit.current = slug
        apiFetch(`/creators/${encodeURIComponent(slug)}/opened`, {method: 'POST'}).catch(() => {
            // Only the Library's order misses this visit.
        })
    }, [slug])
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
    const split = async (accountId: number, siteName: string) => {
        try {
            const page = await splitCreatorAccount(creator.slug, accountId)
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creator']}),
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
            ])
            toast.success(`${page.title} on ${siteName} is a ${page.creatorNames.singular} of their own again`)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
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
            toast.success(`${others.find((other) => other.slug === combineWith)?.title ?? 'The creator'} is now part of ${nameInText(creator.title)}`)
            setCombining(false)
            setCombineWith('')
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        }
    }

    const several = creator.accounts.length > 1
    const links = creator.accounts.filter((account) => account.url).map((account) => ({
        siteName: account.site.name, site: account.site, url: account.url!,
    }))
    // The links show their Sites' names while those fit, then just their icons, and else go into the Actions menu.
    const linkButtons = linkFit.fit === 'menu' ? [] : links
    const episodes = creator.collections.reduce((total, collection) => total + collection.episodeCount, 0)
    const words = wordsOf(creator.words)
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
                        {linkButtons.map((link) => <SiteLink key={link.url} url={link.url} siteName={link.siteName} site={link.site} compact={linkFit.fit === 'icons'}/>)}
                        {mayManage && (
                            <>
                                <PageHeaderAction icon={faIcon('fass', 'pen')} label="Edit" variant="secondary" to={`/edit-creator/${creator.slug}`}/>
                                <ActionMenu items={[...(linkButtons.length ? [] : links.map((link) => ({
                                    label: `Open on ${link.siteName}`,
                                    // The menu names the site, so a site without an icon of its own shows just the globe.
                                    icon: siteIcon(link.site.icon) ?? faIcon('fass', 'globe'),
                                    onSelect: () => window.open(link.url, '_blank', 'noreferrer'),
                                }))),
                                {
                                    label: 'Combine with another creator',
                                    description: 'The same person or group, added from another site or twice',
                                    icon: faIcon('fass', 'object-group'),
                                    disabled: !others.length,
                                    disabledReason: others.length ? undefined : 'There is no other creator in your library.',
                                    onSelect: () => setCombining(true),
                                }, ...(several ? creator.accounts.map((account) => ({
                                    label: `Split off ${account.site.name}`,
                                    description: `Makes the ${account.site.name} account a ${account.site.creatorNames.singular} of their own again, with its collections`,
                                    icon: faIcon('fass', 'object-ungroup'),
                                    onSelect: () => void split(account.id, account.site.name),
                                })) : [])]}/>
                            </>
                        )}
                    </>
                )}
            />

            {(creator.collections.length > 0 || !creator.movies.length) && <div className="creator-section-group">
                <h2 className="creator-collections-title">Collections</h2>
                {creator.collections.length ? (
                    <div className="library-collection-grid" role="list" aria-label="Collections">
                        {creator.collections.map((collection) => (
                            <CollectionTile
                                key={collection.slug} collection={collection} showSource={several}
                            />
                        ))}
                    </div>
                ) : (
                    <p className="creator-empty">
                        None of this {creator.creatorNames.singular}'s collections are in your library any more.
                        {mayManage && <> Add a collection to them with <em>Add to {creator.creatorNames.a}</em> on its page.</>}
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

            <CreatorOfferings creator={creator}/>

            <ConfirmDialog
                open={combining}
                title={`Combine ${nameInText(creator.title)} with another creator`}
                icon={faIcon('fass', 'object-group')}
                onDismiss={() => setCombining(false)}
                confirmButton={{label: 'Combine', onClick: combine, disabled: !combineWith}}
            >
                <div className="form-row">
                    <label htmlFor="combine-creator">Who is the same person or group</label>
                    <SimpleSelect
                        inputId="combine-creator" registry={combineRegistry} value={combineWith}
                        onChange={(value) => setCombineWith(value ?? '')}
                    />
                </div>
                <ul className="creator-order-note">
                    <li>Their accounts and collections become {creator.title}'s, and they leave your library as a creator of their own.</li>
                    <li>Nothing in their collections changes.</li>
                    <li>{creator.title}'s name, picture and settings stay.</li>
                </ul>
            </ConfirmDialog>
        </section>
    )
}
