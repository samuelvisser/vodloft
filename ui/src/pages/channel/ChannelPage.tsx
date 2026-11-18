import {useMemo, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addChannelSections, checkChannel, moveChannelSection, useChannel} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import {postReassignedMove, reassignedMoveMessage} from '../../components/Episode/SeasonPlaceNote'
import {toast} from 'react-hot-toast'
import type {ChannelPageRead, ChannelSectionRead, SectionPlan} from '../../types/schemas/channel'
import ChannelHeader from './ChannelHeader'
import './ChannelPages.css'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
}

function sectionFacts(section: ChannelSectionRead) {
    const noun = section.kindLabel === 'Album' ? ['track', 'tracks'] : ['video', 'videos']
    return [section.kindLabel, section.itemCount != null ? `${section.itemCount} ${noun[section.itemCount === 1 ? 0 : 1]}` : null]
        .filter(Boolean).join(' · ')
}

/** The ways a section of a channel in the Library can be added, in the words of this channel. */
function choices(channel: ChannelPageRead, section: ChannelSectionRead): {label: string, plan: SectionPlan}[] {
    const main = channel.collections.find((collection) => collection.slug === channel.mainCollectionSlug)
    const mainTitle = main?.title ?? channel.title
    const options: {label: string, plan: SectionPlan}[] = []
    if (section.kind === 'feed') {
        options.push({label: `Add to ${mainTitle}`, plan: {ref: section.ref, target: 'main'}})
    } else if (section.kind === 'list' && channel.site.linkSeasons) {
        options.push({label: `As a season of ${mainTitle}`, plan: {ref: section.ref, target: 'main'}})
    }
    options.push({label: 'As its own collection', plan: {ref: section.ref, target: 'own'}})
    return options
}

type Place = 'main' | 'own' | 'skip'

/** What moving a playlist does, in words, before the user says yes. */
function moveNote(section: ChannelSectionRead, to: Place, mainTitle: string): string {
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
        + `and videos of other channels that only this ${noun} brought in leave ${mainTitle}, files and all. It stays listed `
        + 'on this page, so you can add it again.'
}

/** Where one of the channel's playlists is, and a select to move it, with its videos, somewhere else. */
function SectionPlace({section, place, mainTitle, busy, onMove}: {
    section: ChannelSectionRead, place: Place, mainTitle: string, busy: boolean, onMove: (to: Place) => void,
}) {
    const registry = useMemo(() => createSelectRegistry(`SectionPlace-${place}-${mainTitle}`, {
        main: {label: `Season of ${mainTitle}`},
        own: {label: 'Collection of its own'},
        ...(place === 'main' ? {skip: {label: 'Not in your library'}} : {}),
    } as Record<Place, {label: string}>), [place, mainTitle])
    const inputId = `section-place-${section.ref}`
    return (
        <div className="channel-section-place">
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

export default function ChannelPage() {
    const {slug} = useParams()
    const queryClient = useQueryClient()
    const {data: channel, error, isLoading} = useChannel(slug)
    const [busy, setBusy] = useState<string | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [checking, setChecking] = useState(false)
    const [movingReassigned, setMovingReassigned] = useState(false)
    const [moving, setMoving] = useState<{section: ChannelSectionRead, to: Place} | null>(null)
    const [sectionBusy, setSectionBusy] = useState(false)

    if (isLoading) return <section className="view"><p>Loading…</p></section>
    if (error || !channel) {
        return (
            <section className="view">
                <div className="form-error-card" role="alert">{error?.message ?? 'This channel was not found'}</div>
            </section>
        )
    }

    const mayAdd = can('add_media')
    const place = async (plan: SectionPlan) => {
        setBusy(plan.ref)
        setActionError(null)
        try {
            const page = await addChannelSections(channel.slug, [plan])
            queryClient.setQueryData(['channel', slug], page)
            await queryClient.invalidateQueries({queryKey: ['channels']})
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
            await checkChannel(channel.slug)
        } catch (exc) {
            setActionError(exc instanceof Error ? exc.message : String(exc))
            setChecking(false)
        }
    }

    const moveReassigned = async () => {
        setMovingReassigned(true)
        try {
            const result = await postReassignedMove(`/channels/${encodeURIComponent(channel.slug)}/move-reassigned`)
            toast.success(reassignedMoveMessage(result))
            await queryClient.invalidateQueries({queryKey: ['channel', slug]})
            await queryClient.invalidateQueries({queryKey: ['collection']})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setMovingReassigned(false)
        }
    }

    const mainTitle = channel.collections.find((collection) => collection.slug === channel.mainCollectionSlug)?.title ?? channel.title
    const placed = channel.site.linkSeasons && channel.mainCollectionSlug
        ? channel.sections.filter((section) => (
            section.kind === 'list' && channel.collections.some((collection) => collection.slug === section.collectionSlug)
        ))
        : []
    const placeOf = (section: ChannelSectionRead): Place => section.collectionSlug === channel.mainCollectionSlug ? 'main' : 'own'
    const moveSection = async () => {
        if (!moving) return
        setSectionBusy(true)
        try {
            const page = await moveChannelSection(channel.slug, moving.section.ref, moving.to)
            queryClient.setQueryData(['channel', slug], page)
            await queryClient.invalidateQueries({queryKey: ['channels']})
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

    const found = channel.sections.filter((section) => section.status === 'new' && !section.collectionSlug)
    const left = channel.sections.filter((section) => (
        !section.collectionSlug && section.kind !== 'item' && section.status !== 'new'
    ))
    const sectionArt = (section: ChannelSectionRead) => section.imageUrl
        ? <img className="channel-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
        : <span className="channel-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : 'list')}/></span>

    return (
        <section className="view channel-view" aria-labelledby="channel-title">
            <ChannelHeader
                title={channel.title} label={`${channel.site.name} ${channel.channelLabel}`} handle={channel.handle}
                avatarUrl={channel.avatarUrl} bannerUrl={channel.bannerUrl} facts={channel.facts}
                description={channel.description} url={channel.url} titleId="channel-title"
                actions={can('library', 'manage') && (
                    <>
                        <PageHeaderAction icon={faIcon('fass', 'pen')} label="Edit" variant="secondary" to={`/edit-channel/${channel.slug}`}/>
                        <PageHeaderAction
                            icon={faIcon('fass', 'arrows-rotate')} label={checking ? 'Looking…' : 'Check now'} variant="secondary"
                            onClick={() => void check()}
                        />
                        <ActionMenu items={[{
                            label: 'Move reassigned episodes',
                            description: channel.reassignedCount
                                ? `${channel.reassignedCount} downloaded ${channel.reassignedCount === 1 ? 'episode belongs' : 'episodes belong'} in another collection of this ${channel.channelLabel} now`
                                : undefined,
                            icon: faIcon('fass', 'arrow-right-from-bracket'),
                            disabled: movingReassigned || !channel.reassignedCount,
                            disabledReason: channel.reassignedCount ? undefined : `No episode of this ${channel.channelLabel} belongs in another of its collections.`,
                            onSelect: () => void moveReassigned(),
                        }]}/>
                    </>
                )}
            />

            {checking && (
                <p className="channel-note" role="status">
                    VODLoft is looking for new playlists and shows. They show here when it is done.
                </p>
            )}
            {actionError && <div className="form-error-card" role="alert">{actionError}</div>}

            {found.map((section) => (
                <div key={section.ref} className="channel-found" role="region" aria-label={`New: ${section.title}`}>
                    {sectionArt(section)}
                    <div className="channel-section-copy">
                        <b>New {(section.kindLabel ?? 'section').toLowerCase()}: {section.title}</b>
                        <span>{sectionFacts(section) || `Found on ${channel.title}`}</span>
                    </div>
                    {mayAdd && (
                        <div className="channel-found-actions">
                            {choices(channel, section).map((choice) => (
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

            <div className="channel-section-group">
                <h2>In your library</h2>
                {channel.collections.length ? (
                    <div className="channel-collections">
                        {channel.collections.map((collection) => {
                            const image = toImageUrl(collection.thumbnailLandscapePath)
                            return (
                                <Link key={collection.slug} className="channel-collection" to={`/collection/${collection.slug}`}>
                                    {image
                                        ? <img src={image} alt="" loading="lazy"/>
                                        : <span className="channel-collection-art" aria-hidden="true"><FontAwesomeIcon icon={collection.type === 'music' ? faIcon('fass', 'music') : faIcon('fass', 'tv')}/></span>}
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
                    <p>None of this {channel.channelLabel}'s collections are in your library any more.</p>
                )}
            </div>

            {placed.length > 0 && (
                <div className="channel-section-group">
                    <h2>Where its {(placed[0].kindLabel ?? 'playlist').toLowerCase()}s go</h2>
                    <div className="channel-section-list">
                        {placed.map((section) => (
                            <div key={section.ref} className="channel-section-row">
                                {sectionArt(section)}
                                <div className="channel-section-copy">
                                    <b>{section.title}</b>
                                    <span>{sectionFacts(section)}</span>
                                </div>
                                {can('library', 'manage') ? (
                                    <SectionPlace
                                        section={section} place={placeOf(section)} mainTitle={mainTitle} busy={sectionBusy}
                                        onMove={(to) => setMoving({section, to})}
                                    />
                                ) : (
                                    <span className="channel-section-note">
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
                <div className="channel-section-group">
                    <h2>Not in your library</h2>
                    <div className="channel-section-list">
                        {left.map((section) => (
                            <div key={section.ref} className="channel-section-row">
                                {sectionArt(section)}
                                <div className="channel-section-copy">
                                    <b>{section.title}</b>
                                    <span>
                                        {section.access
                                            ? 'Only some members can watch this.'
                                            : [sectionFacts(section), section.status === 'ignored' ? 'ignored' : null].filter(Boolean).join(' · ')}
                                    </span>
                                </div>
                                {mayAdd && (
                                    <div className="channel-found-actions">
                                        {choices(channel, section).map((choice) => (
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

            {channel.checkedAt && (
                <p className="channel-note">
                    VODLoft looks for new playlists and shows once a day. Last look: {new Date(channel.checkedAt).toLocaleString()}.
                </p>
            )}
        </section>
    )
}
