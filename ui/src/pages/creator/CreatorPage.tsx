import {useMemo, useState} from 'react'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addCreatorSections, checkCreator, combineCreators, moveCreatorSection, splitCreatorAccount, useCreator, useCreators} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import {postReassignedMove, reassignedMoveMessage} from '../../components/Episode/SeasonPlaceNote'
import {toast} from 'react-hot-toast'
import type {CreatorPageAccountRead, CreatorPageRead, CreatorSectionRead, SectionPlan} from '../../types/schemas/creator'
import {creatorKindText} from '../../types/creator'
import CreatorHeader from './CreatorHeader'
import './CreatorPages.css'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
}

function sectionFacts(section: CreatorSectionRead) {
    const noun = section.kindLabel === 'Album' ? ['track', 'tracks'] : ['video', 'videos']
    return [section.kindLabel, section.itemCount != null ? `${section.itemCount} ${noun[section.itemCount === 1 ? 0 : 1]}` : null]
        .filter(Boolean).join(' · ')
}

/** One section of one of the creator's accounts. */
type AccountSection = {account: CreatorPageAccountRead, section: CreatorSectionRead}

/** The title of the collection named after the creator that takes the account's uploads. */
function mainTitleOf(creator: CreatorPageRead, account: CreatorPageAccountRead): string {
    return creator.collections.find((collection) => collection.slug === account.mainCollectionSlug)?.title ?? creator.title
}

/** The ways a section of a creator in the Library can be added, in the words of this creator. */
function choices(creator: CreatorPageRead, {account, section}: AccountSection): {label: string, plan: SectionPlan}[] {
    const mainTitle = mainTitleOf(creator, account)
    const options: {label: string, plan: SectionPlan}[] = []
    if (section.kind === 'feed') {
        options.push({label: `Add to ${mainTitle}`, plan: {ref: section.ref, target: 'main'}})
    } else if (section.kind === 'list' && account.site.linkSeasons) {
        options.push({label: `As a season of ${mainTitle}`, plan: {ref: section.ref, target: 'main'}})
    }
    options.push({label: 'As its own collection', plan: {ref: section.ref, target: 'own'}})
    return options
}

type Place = 'main' | 'own' | 'skip'

/** What moving a playlist does, in words, before the user says yes. */
function moveNote(section: CreatorSectionRead, to: Place, mainTitle: string): string {
    const noun = (section.kindLabel ?? 'playlist').toLowerCase()
    if (to === 'own') {
        return `${section.title} becomes a collection of its own, and takes its videos out of ${mainTitle}. Downloaded videos `
            + 'take their files along, renamed into the new collection as manual downloads, since it has no Download '
            + 'Profiles yet.'
    }
    if (to === 'main') {
        return `${section.title} becomes a season of ${mainTitle}, and its videos move there. Downloaded videos take their `
            + `files along: renamed when ${mainTitle} downloads them with the same Local Media Profile or not at all, and `
            + `downloaded again there when it uses another one; the old files go once that succeeded. The collection `
            + `${section.collectionTitle ?? section.title} goes once it is empty.`
    }
    return `${section.title} is no longer a season of ${mainTitle}. Its videos go to the season of videos in no ${noun}, `
        + `and videos of other creators that only this ${noun} brought in leave ${mainTitle}, files and all. It stays listed `
        + 'on this page, so you can add it again.'
}

/** Where one of the creator's playlists is, and a select to move it, with its videos, somewhere else. */
function SectionPlace({section, place, mainTitle, busy, onMove}: {
    section: CreatorSectionRead, place: Place, mainTitle: string, busy: boolean, onMove: (to: Place) => void,
}) {
    const registry = useMemo(() => createSelectRegistry(`SectionPlace-${place}-${mainTitle}`, {
        main: {label: `Season of ${mainTitle}`},
        own: {label: 'Collection of its own'},
        ...(place === 'main' ? {skip: {label: 'Not in your library'}} : {}),
    } as Record<Place, {label: string}>), [place, mainTitle])
    const inputId = `section-place-${section.ref}`
    return (
        <div className="creator-section-place">
            <label className="sr-only" htmlFor={inputId}>Where {section.title} goes</label>
            <SimpleSelect
                inputId={inputId} registry={registry} value={place} isDisabled={busy}
                menuPortalTarget={document.body} menuPlacement="auto"
                styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                onChange={(value) => { if (value && value !== place) onMove(value as Place) }}
            />
        </div>
    )
}

export default function CreatorPage() {
    const {slug} = useParams()
    const queryClient = useQueryClient()
    const {data: creator, error, isLoading} = useCreator(slug)
    const [busy, setBusy] = useState<string | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [checking, setChecking] = useState(false)
    const [movingReassigned, setMovingReassigned] = useState(false)
    const [moving, setMoving] = useState<{item: AccountSection, to: Place} | null>(null)
    const [sectionBusy, setSectionBusy] = useState(false)
    const navigate = useNavigate()
    const [splitting, setSplitting] = useState<CreatorPageAccountRead | null>(null)
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

    if (isLoading) return <section className="view"><p>Loading…</p></section>
    if (error || !creator) {
        return (
            <section className="view">
                <div className="form-error-card" role="alert">{error?.message ?? 'This creator was not found'}</div>
            </section>
        )
    }

    const mayAdd = can('add_media')
    const sectionKey = (account: CreatorPageAccountRead, ref: string) => `${account.id}:${ref}`
    const place = async (account: CreatorPageAccountRead, plan: SectionPlan) => {
        setBusy(sectionKey(account, plan.ref))
        setActionError(null)
        try {
            const page = await addCreatorSections(creator.slug, account.id, [plan])
            queryClient.setQueryData(['creator', slug], page)
            await queryClient.invalidateQueries({queryKey: ['creators']})
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
        } catch (exc) {
            setActionError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(null)
        }
    }
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
            toast.success(reassignedMoveMessage(result))
            await queryClient.invalidateQueries({queryKey: ['creator', slug]})
            await queryClient.invalidateQueries({queryKey: ['collection']})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setMovingReassigned(false)
        }
    }

    const several = creator.accounts.length > 1
    const all: AccountSection[] = creator.accounts.flatMap((account) => account.sections.map((section) => ({account, section})))
    const placed = all.filter(({account, section}) => (
        account.site.linkSeasons && account.mainCollectionSlug && section.kind === 'list'
        && creator.collections.some((collection) => collection.slug === section.collectionSlug)
    ))
    const placeOf = ({account, section}: AccountSection): Place => section.collectionSlug === account.mainCollectionSlug ? 'main' : 'own'
    /** Which account a section is of, when the creator has several. */
    const onSite = (account: CreatorPageAccountRead) => several ? ` on ${account.site.name}` : ''
    const checkedAt = creator.accounts.map((account) => account.checkedAt).filter(Boolean).sort().pop()
    const links = creator.accounts.filter((account) => account.url).map((account) => ({
        label: several ? `Open on ${account.site.name}` : 'Open on the site', url: account.url!,
    }))
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
    const split = async () => {
        if (!splitting) return
        try {
            const page = await splitCreatorAccount(creator.slug, splitting.id)
            await queryClient.invalidateQueries({queryKey: ['creator', slug]})
            await queryClient.invalidateQueries({queryKey: ['creators']})
            await queryClient.invalidateQueries({queryKey: ['collection']})
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            toast.success(`${page.title} is a creator of their own now`)
            setSplitting(null)
            navigate(`/creator/${page.slug}`)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        }
    }
    const moveSection = async () => {
        if (!moving) return
        setSectionBusy(true)
        try {
            const page = await moveCreatorSection(creator.slug, moving.item.account.id, moving.item.section.ref, moving.to)
            queryClient.setQueryData(['creator', slug], page)
            await queryClient.invalidateQueries({queryKey: ['creators']})
            await queryClient.invalidateQueries({queryKey: ['collection']})
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            toast.success(`Moved ${moving.item.section.title}`)
            setMoving(null)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSectionBusy(false)
        }
    }

    const found = all.filter(({section}) => section.status === 'new' && !section.collectionSlug)
    const left = all.filter(({section}) => (
        !section.collectionSlug && section.kind !== 'item' && section.status !== 'new'
    ))
    const sectionArt = (section: CreatorSectionRead) => section.imageUrl
        ? <img className="creator-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
        : <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : 'list')}/></span>

    return (
        <section className="view creator-view" aria-labelledby="creator-title">
            <CreatorHeader
                title={creator.title} label={creatorKindText(creator)}
                handle={creator.accounts[0]?.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts}
                description={creator.description} links={links} titleId="creator-title"
                actions={can('library', 'manage') && (
                    <>
                        <PageHeaderAction icon={faIcon('fass', 'pen')} label="Edit" variant="secondary" to={`/edit-creator/${creator.slug}`}/>
                        <PageHeaderAction
                            icon={faIcon('fass', 'arrows-rotate')} label={checking ? 'Looking…' : 'Check now'} variant="secondary"
                            onClick={() => void check()}
                        />
                        <ActionMenu items={[{
                            label: 'Move reassigned episodes',
                            description: creator.reassignedCount
                                ? `${creator.reassignedCount} downloaded ${creator.reassignedCount === 1 ? 'episode belongs' : 'episodes belong'} in another collection of this ${creator.creatorLabel} now`
                                : undefined,
                            icon: faIcon('fass', 'arrow-right-from-bracket'),
                            disabled: movingReassigned || !creator.reassignedCount,
                            disabledReason: creator.reassignedCount ? undefined : `No episode of this ${creator.creatorLabel} belongs in another of its collections.`,
                            onSelect: () => void moveReassigned(),
                        }, {
                            label: 'Combine with another creator',
                            description: 'The same person or group, added from another site or twice',
                            icon: faIcon('fass', 'object-group'),
                            disabled: !others.length,
                            disabledReason: others.length ? undefined : 'There is no other creator in your library.',
                            onSelect: () => setCombining(true),
                        }]}/>
                    </>
                )}
            />

            {checking && (
                <p className="creator-note" role="status">
                    VODLoft is looking for new playlists and shows. They show here when it is done.
                </p>
            )}
            {actionError && <div className="form-error-card" role="alert">{actionError}</div>}

            {found.map((item) => {
                const {account, section} = item
                return (
                <div key={sectionKey(account, section.ref)} className="creator-found" role="region" aria-label={`New: ${section.title}`}>
                    {sectionArt(section)}
                    <div className="creator-section-copy">
                        <b>New {(section.kindLabel ?? 'section').toLowerCase()}{onSite(account)}: {section.title}</b>
                        <span>{sectionFacts(section) || `Found on ${creator.title}`}</span>
                    </div>
                    {mayAdd && (
                        <div className="creator-found-actions">
                            {choices(creator, item).map((choice) => (
                                <button key={choice.label} type="button" className="btn" disabled={busy !== null} onClick={() => void place(account, choice.plan)}>
                                    {choice.label}
                                </button>
                            ))}
                            <button type="button" className="btn btn-link" disabled={busy !== null}
                                    onClick={() => void place(account, {ref: section.ref, target: 'skip'})}>
                                Ignore
                            </button>
                        </div>
                    )}
                </div>
                )
            })}

            {several && (
                <div className="creator-section-group">
                    <h2>Accounts</h2>
                    <div className="creator-section-list">
                        {creator.accounts.map((account) => (
                            <div key={account.id} className="creator-section-row">
                                <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'circle-user')}/></span>
                                <div className="creator-section-copy">
                                    <b>{account.site.name}</b>
                                    <span>{[account.handle, `${account.sections.length} ${account.sections.length === 1 ? 'section' : 'sections'}`].filter(Boolean).join(' · ')}</span>
                                </div>
                                {can('library', 'manage') && (
                                    <div className="creator-found-actions">
                                        <button type="button" className="btn" onClick={() => setSplitting(account)}>Split off</button>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <div className="creator-section-group">
                <h2>In your library</h2>
                {creator.collections.length ? (
                    <div className="creator-collections">
                        {creator.collections.map((collection) => {
                            const image = toImageUrl(collection.thumbnailLandscapePath)
                            return (
                                <Link key={collection.slug} className="creator-collection" to={`/collection/${collection.slug}`}>
                                    {image
                                        ? <img src={image} alt="" loading="lazy"/>
                                        : <span className="creator-collection-art" aria-hidden="true"><FontAwesomeIcon icon={collection.type === 'music' ? faIcon('fass', 'music') : faIcon('fass', 'tv')}/></span>}
                                    <b>{collection.title}</b>
                                    <span>
                                        {collection.episodeCount} {collection.type === 'music'
                                            ? (collection.episodeCount === 1 ? 'track' : 'tracks')
                                            : (collection.episodeCount === 1 ? 'video' : 'videos')}
                                        {collection.links.length > 1 ? ` from ${listedSources(collection.links)}` : ''}
                                    </span>
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <p>None of this {creator.creatorLabel}'s collections are in your library any more.</p>
                )}
            </div>

            {placed.length > 0 && (
                <div className="creator-section-group">
                    <h2>Where the {(placed[0].section.kindLabel ?? 'playlist').toLowerCase()}s go</h2>
                    <div className="creator-section-list">
                        {placed.map((item) => {
                            const {account, section} = item
                            const mainTitle = mainTitleOf(creator, account)
                            return (
                            <div key={sectionKey(account, section.ref)} className="creator-section-row">
                                {sectionArt(section)}
                                <div className="creator-section-copy">
                                    <b>{section.title}</b>
                                    <span>{[sectionFacts(section), several ? account.site.name : null].filter(Boolean).join(' · ')}</span>
                                </div>
                                {can('library', 'manage') ? (
                                    <SectionPlace
                                        section={section} place={placeOf(item)} mainTitle={mainTitle} busy={sectionBusy}
                                        onMove={(to) => setMoving({item, to})}
                                    />
                                ) : (
                                    <span className="creator-section-note">
                                        {placeOf(item) === 'main' ? `Season of ${mainTitle}` : 'Collection of its own'}
                                    </span>
                                )}
                            </div>
                            )
                        })}
                    </div>
                </div>
            )}

            <ConfirmDialog
                open={moving !== null}
                title={moving ? `Move ${moving.item.section.title}` : 'Move'}
                icon={faIcon('fass', 'arrow-right-arrow-left')}
                onDismiss={() => setMoving(null)}
                confirmButton={{label: sectionBusy ? 'Moving…' : 'Move', onClick: moveSection, disabled: sectionBusy}}
            >
                {moving && <p>{moveNote(moving.item.section, moving.to, mainTitleOf(creator, moving.item.account))}</p>}
            </ConfirmDialog>

            <ConfirmDialog
                open={splitting !== null}
                title={splitting ? `Split ${splitting.site.name} off ${creator.title}` : 'Split off'}
                icon={faIcon('fass', 'object-ungroup')}
                onDismiss={() => setSplitting(null)}
                confirmButton={{label: 'Split off', onClick: split}}
            >
                {splitting && (
                    <ul className="creator-order-note">
                        <li>The account on {splitting.site.name} becomes a creator of its own, named as {splitting.site.name} names them.</li>
                        <li>Its own collection and the collections of its playlists and shows go along. Collections that joined {creator.title} by another link stay.</li>
                        <li>Collections keep their seasons, episodes, profiles and files. Nothing is indexed again.</li>
                    </ul>
                )}
            </ConfirmDialog>

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
                    <li>Collections keep their seasons, episodes, profiles and files. Nothing is indexed again.</li>
                    <li>{creator.title}'s name, picture and settings stay.</li>
                </ul>
            </ConfirmDialog>

            {left.length > 0 && (
                <div className="creator-section-group">
                    <h2>Not in your library</h2>
                    <div className="creator-section-list">
                        {left.map((item) => {
                            const {account, section} = item
                            return (
                            <div key={sectionKey(account, section.ref)} className="creator-section-row">
                                {sectionArt(section)}
                                <div className="creator-section-copy">
                                    <b>{section.title}</b>
                                    <span>
                                        {section.access
                                            ? 'Only some members can watch this.'
                                            : [sectionFacts(section), several ? account.site.name : null, section.status === 'ignored' ? 'ignored' : null].filter(Boolean).join(' · ')}
                                    </span>
                                </div>
                                {mayAdd && (
                                    <div className="creator-found-actions">
                                        {choices(creator, item).map((choice) => (
                                            <button key={choice.label} type="button" className="btn" disabled={busy !== null}
                                                    onClick={() => void place(account, choice.plan)}>
                                                {busy === sectionKey(account, section.ref) ? 'Adding…' : choice.label}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                            )
                        })}
                    </div>
                </div>
            )}

            {checkedAt && (
                <p className="creator-note">
                    VODLoft looks for new playlists and shows once a day. Last look: {new Date(checkedAt).toLocaleString()}.
                </p>
            )}
        </section>
    )
}
