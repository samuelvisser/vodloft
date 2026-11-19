import {useCallback, useMemo, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {checkCreator, combineCreators, useCreator, useCreatorEpisodes, useCreators} from '../../lib/queries'
import {useLoadMoreOnScroll} from '../../lib/useLoadMoreOnScroll'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import EpisodeCard from '../../components/Episode/EpisodeCard'
import CollectionTile from '../../components/CollectionTile/CollectionTile'
import OpenOnSiteLink from '../../components/common/OpenOnSiteLink'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import {postReassignedMove, reassignedMoveMessage} from '../../components/Episode/SeasonPlaceNote'
import {toast} from 'react-hot-toast'
import {creatorKindText} from '../../types/creator'
import CreatorHeader from './CreatorHeader'
import CreatorNotInLibrary from './CreatorNotInLibrary'
import './CreatorPages.css'
import {collectionWords, CollectionWords} from '../../lib/collectionWords'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length === 1) return titles[0]
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
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
                <h2 id="creator-newest-title">Newest {words.episode.many}</h2>
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
    const {data: creator, error} = useCreator(slug)
    const [actionError, setActionError] = useState<string | null>(null)
    const [checking, setChecking] = useState(false)
    const [movingReassigned, setMovingReassigned] = useState(false)
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
    const moveReassigned = async () => {
        setMovingReassigned(true)
        try {
            const result = await postReassignedMove(`/creators/${encodeURIComponent(creator.slug)}/move-reassigned`)
            toast.success(reassignedMoveMessage(result, fileWords))
            await queryClient.invalidateQueries({queryKey: ['creator', slug]})
            await queryClient.invalidateQueries({queryKey: ['collection']})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setMovingReassigned(false)
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
    const links = creator.accounts.filter((account) => account.url).map((account) => ({siteName: account.site.name, url: account.url!}))
    // Two sites fit as buttons; more go into the Actions menu.
    const linkButtons = links.length <= 2 ? links : []
    const episodes = creator.collections.reduce((total, collection) => total + collection.episodeCount, 0)
    // An artist whose collections are all Music collections has albums, and tracks on a Site with sound only.
    const music = creator.collections.length > 0 && creator.collections.every((collection) => collection.type === 'music')
    const words = collectionWords(music ? 'music' : null, creator.accounts.every((account) => account.site.audio) ? 'audio' : 'video')
    const fileWords = collectionWords(music ? 'music' : null, 'audio')
    const firstDates = creator.collections.map((collection) => collection.firstPublishedDate).filter((date): date is Date => !!date)
    const since = firstDates.length ? Math.min(...firstDates.map((date) => date.getFullYear())) : null
    const newest = creator.lastPublishedDate

    return (
        <section className="view creator-view" aria-labelledby="creator-title">
            <CreatorHeader
                title={creator.title} label={creatorKindText(creator)}
                handle={creator.accounts[0]?.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts}
                description={creator.description} titleId="creator-title"
                stats={creator.collections.length > 0 && (
                    <ul className="creator-stats">
                        <li><b>{creator.collections.length}</b> {creator.collections.length === 1 ? 'collection' : 'collections'}</li>
                        <li><b>{episodes}</b> {episodes === 1 ? words.episode.one : words.episode.many}</li>
                        {since && <li>Since <b>{since}</b></li>}
                        {newest && <li>Newest <b>{timeAgo(newest)}</b></li>}
                    </ul>
                )}
                actions={(linkButtons.length > 0 || mayManage) && (
                    <>
                        {linkButtons.map((link) => <OpenOnSiteLink key={link.url} url={link.url} siteName={link.siteName}/>)}
                        {mayManage && (
                            <>
                                <PageHeaderAction icon={faIcon('fass', 'pen')} label="Edit" variant="secondary" to={`/edit-creator/${creator.slug}`}/>
                                <ActionMenu items={[{
                                    label: checking ? 'Looking…' : 'Check now',
                                    description: `Look for new ${creator.sectionNames.many}`,
                                    icon: faIcon('fass', 'arrows-rotate'),
                                    disabled: checking,
                                    onSelect: () => void check(),
                                }, ...(linkButtons.length ? [] : links.map((link) => ({
                                    label: `Open on ${link.siteName}`,
                                    icon: faIcon('fass', 'arrow-up-right-from-square'),
                                    onSelect: () => window.open(link.url, '_blank', 'noreferrer'),
                                }))),
                                // Episodes can only move between collections, so a creator with one has nothing to move.
                                ...(creator.collections.length > 1 ? [{
                                    label: `Move reassigned ${fileWords.episode.many}`,
                                    description: creator.reassignedCount
                                        ? `${creator.reassignedCount} downloaded ${creator.reassignedCount === 1 ? `${fileWords.episode.one} belongs` : `${fileWords.episode.many} belong`} in another collection of this ${creator.creatorLabel} now`
                                        : undefined,
                                    icon: faIcon('fass', 'arrow-right-from-bracket'),
                                    disabled: movingReassigned || !creator.reassignedCount,
                                    disabledReason: creator.reassignedCount ? undefined : `No ${fileWords.episode.one} of this ${creator.creatorLabel} belongs in another of its collections.`,
                                    onSelect: () => void moveReassigned(),
                                }] : []), {
                                    label: 'Combine with another creator',
                                    description: 'The same person or group, added from another site or twice',
                                    icon: faIcon('fass', 'object-group'),
                                    disabled: !others.length,
                                    disabledReason: others.length ? undefined : 'There is no other creator in your library.',
                                    onSelect: () => setCombining(true),
                                }]}/>
                            </>
                        )}
                    </>
                )}
            />

            {checking && (
                <p className="creator-note" role="status">
                    VODLoft is looking for new {creator.sectionNames.many}. New ones show under Collections when it is done.
                </p>
            )}
            {actionError && <div className="form-error-card" role="alert">{actionError}</div>}

            <EpisodeShelf slug={creator.slug} words={words}/>

            <div className="creator-section-group">
                <h2 className="creator-collections-title">Collections</h2>
                {creator.collections.length ? (
                    <div className="library-collection-grid" role="list" aria-label="Collections">
                        {creator.collections.map((collection) => (
                            <CollectionTile
                                key={collection.slug} collection={collection} showSource={several}
                                // Where it comes from, unless that is just its own title.
                                subtitle={collection.links.length > 1 || (collection.links.length === 1 && collection.links[0] !== collection.title)
                                    ? listedSources(collection.links) : null}
                            />
                        ))}
                    </div>
                ) : (
                    <p className="creator-empty">
                        None of this {creator.creatorLabel}'s collections are in your library any more.
                        {mayManage && <> Add some on the <Link to={`/edit-creator/${creator.slug}`}>Edit page</Link>.</>}
                    </p>
                )}
            </div>

            <CreatorNotInLibrary creator={creator}/>

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
                    <li>Collections keep their {words.season.many}, {words.episode.many}, profiles and files. Nothing is indexed again.</li>
                    <li>{creator.title}'s name, picture and settings stay.</li>
                </ul>
            </ConfirmDialog>
        </section>
    )
}
