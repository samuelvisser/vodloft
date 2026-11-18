import {useMemo, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addCreatorSections, checkCreator, moveCreatorSection, useCreator} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import {postReassignedMove, reassignedMoveMessage} from '../../components/Episode/SeasonPlaceNote'
import {toast} from 'react-hot-toast'
import type {CreatorPageRead, CreatorSectionRead, SectionPlan} from '../../types/schemas/creator'
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

/** The ways a section of a creator in the Library can be added, in the words of this creator. */
function choices(creator: CreatorPageRead, section: CreatorSectionRead): {label: string, plan: SectionPlan}[] {
    const main = creator.collections.find((collection) => collection.slug === creator.mainCollectionSlug)
    const mainTitle = main?.title ?? creator.title
    const options: {label: string, plan: SectionPlan}[] = []
    if (section.kind === 'feed') {
        options.push({label: `Add to ${mainTitle}`, plan: {ref: section.ref, target: 'main'}})
    } else if (section.kind === 'list' && creator.site.linkSeasons) {
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
    const [moving, setMoving] = useState<{section: CreatorSectionRead, to: Place} | null>(null)
    const [sectionBusy, setSectionBusy] = useState(false)

    if (isLoading) return <section className="view"><p>Loading…</p></section>
    if (error || !creator) {
        return (
            <section className="view">
                <div className="form-error-card" role="alert">{error?.message ?? 'This creator was not found'}</div>
            </section>
        )
    }

    const mayAdd = can('add_media')
    const place = async (plan: SectionPlan) => {
        setBusy(plan.ref)
        setActionError(null)
        try {
            const page = await addCreatorSections(creator.slug, [plan])
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

    const mainTitle = creator.collections.find((collection) => collection.slug === creator.mainCollectionSlug)?.title ?? creator.title
    const placed = creator.site.linkSeasons && creator.mainCollectionSlug
        ? creator.sections.filter((section) => (
            section.kind === 'list' && creator.collections.some((collection) => collection.slug === section.collectionSlug)
        ))
        : []
    const placeOf = (section: CreatorSectionRead): Place => section.collectionSlug === creator.mainCollectionSlug ? 'main' : 'own'
    const moveSection = async () => {
        if (!moving) return
        setSectionBusy(true)
        try {
            const page = await moveCreatorSection(creator.slug, moving.section.ref, moving.to)
            queryClient.setQueryData(['creator', slug], page)
            await queryClient.invalidateQueries({queryKey: ['creators']})
            await queryClient.invalidateQueries({queryKey: ['collection']})
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            toast.success(`Moved ${moving.section.title}`)
            setMoving(null)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSectionBusy(false)
        }
    }

    const found = creator.sections.filter((section) => section.status === 'new' && !section.collectionSlug)
    const left = creator.sections.filter((section) => (
        !section.collectionSlug && section.kind !== 'item' && section.status !== 'new'
    ))
    const sectionArt = (section: CreatorSectionRead) => section.imageUrl
        ? <img className="creator-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
        : <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : 'list')}/></span>

    return (
        <section className="view creator-view" aria-labelledby="creator-title">
            <CreatorHeader
                title={creator.title} label={`${creator.site.name} ${creator.creatorLabel}`} handle={creator.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts}
                description={creator.description} url={creator.url} titleId="creator-title"
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

            {found.map((section) => (
                <div key={section.ref} className="creator-found" role="region" aria-label={`New: ${section.title}`}>
                    {sectionArt(section)}
                    <div className="creator-section-copy">
                        <b>New {(section.kindLabel ?? 'section').toLowerCase()}: {section.title}</b>
                        <span>{sectionFacts(section) || `Found on ${creator.title}`}</span>
                    </div>
                    {mayAdd && (
                        <div className="creator-found-actions">
                            {choices(creator, section).map((choice) => (
                                <button key={choice.label} type="button" className="btn" disabled={busy !== null} onClick={() => void place(choice.plan)}>
                                    {choice.label}
                                </button>
                            ))}
                            <button type="button" className="btn btn-link" disabled={busy !== null}
                                    onClick={() => void place({ref: section.ref, target: 'skip'})}>
                                Ignore
                            </button>
                        </div>
                    )}
                </div>
            ))}

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
                    <h2>Where its {(placed[0].kindLabel ?? 'playlist').toLowerCase()}s go</h2>
                    <div className="creator-section-list">
                        {placed.map((section) => (
                            <div key={section.ref} className="creator-section-row">
                                {sectionArt(section)}
                                <div className="creator-section-copy">
                                    <b>{section.title}</b>
                                    <span>{sectionFacts(section)}</span>
                                </div>
                                {can('library', 'manage') ? (
                                    <SectionPlace
                                        section={section} place={placeOf(section)} mainTitle={mainTitle} busy={sectionBusy}
                                        onMove={(to) => setMoving({section, to})}
                                    />
                                ) : (
                                    <span className="creator-section-note">
                                        {placeOf(section) === 'main' ? `Season of ${mainTitle}` : 'Collection of its own'}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <ConfirmDialog
                open={moving !== null}
                title={moving ? `Move ${moving.section.title}` : 'Move'}
                icon={faIcon('fass', 'arrow-right-arrow-left')}
                onDismiss={() => setMoving(null)}
                confirmButton={{label: sectionBusy ? 'Moving…' : 'Move', onClick: moveSection, disabled: sectionBusy}}
            >
                {moving && <p>{moveNote(moving.section, moving.to, mainTitle)}</p>}
            </ConfirmDialog>

            {left.length > 0 && (
                <div className="creator-section-group">
                    <h2>Not in your library</h2>
                    <div className="creator-section-list">
                        {left.map((section) => (
                            <div key={section.ref} className="creator-section-row">
                                {sectionArt(section)}
                                <div className="creator-section-copy">
                                    <b>{section.title}</b>
                                    <span>
                                        {section.access
                                            ? 'Only some members can watch this.'
                                            : [sectionFacts(section), section.status === 'ignored' ? 'ignored' : null].filter(Boolean).join(' · ')}
                                    </span>
                                </div>
                                {mayAdd && (
                                    <div className="creator-found-actions">
                                        {choices(creator, section).map((choice) => (
                                            <button key={choice.label} type="button" className="btn" disabled={busy !== null}
                                                    onClick={() => void place(choice.plan)}>
                                                {busy === section.ref ? 'Adding…' : choice.label}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {creator.checkedAt && (
                <p className="creator-note">
                    VODLoft looks for new playlists and shows once a day. Last look: {new Date(creator.checkedAt).toLocaleString()}.
                </p>
            )}
        </section>
    )
}
