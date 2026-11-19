import {useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addChannelSections, checkChannel, useChannel} from '../../lib/queries'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import {PageHeaderAction} from '../../components/common/PageHeader'
import type {ChannelPageRead, ChannelSectionRead, SectionPlan} from '../../types/schemas/channel'
import ChannelHeader from './ChannelHeader'
import './ChannelPages.css'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
}

function sectionFacts(section: ChannelSectionRead) {
    return [section.kindLabel, section.itemCount != null ? `${section.itemCount} ${section.itemCount === 1 ? 'video' : 'videos'}` : null]
        .filter(Boolean).join(' · ')
}

/** The ways a section of a channel in the Library can be added, in the words of this channel. */
function choices(channel: ChannelPageRead, section: ChannelSectionRead): {label: string, plan: SectionPlan}[] {
    const main = channel.collections.find((collection) => collection.slug === channel.mainCollectionSlug)
    const mainTitle = main?.title ?? channel.title
    const options: {label: string, plan: SectionPlan}[] = []
    if (section.kind === 'feed') {
        options.push({label: `Add to ${mainTitle}`, plan: {ref: section.ref, target: 'main', placement: 'site_seasons'}})
    } else if (!section.hasSeasons) {
        options.push({label: `As a season of ${mainTitle}`, plan: {ref: section.ref, target: 'main', placement: 'one_season'}})
    }
    options.push({label: 'As its own collection', plan: {ref: section.ref, target: 'own', placement: 'site_seasons'}})
    return options
}

export default function ChannelPage() {
    const {slug} = useParams()
    const queryClient = useQueryClient()
    const {data: channel, error, isLoading} = useChannel(slug)
    const [busy, setBusy] = useState<string | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [checking, setChecking] = useState(false)

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
                                    onClick={() => void place({ref: section.ref, target: 'skip', placement: 'site_seasons'})}>
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
                                        : <span className="channel-collection-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'tv')}/></span>}
                                    <b>{collection.title}</b>
                                    <span>
                                        {collection.episodeCount} {collection.episodeCount === 1 ? 'video' : 'videos'}
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
