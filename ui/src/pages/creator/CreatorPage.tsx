import {useMemo, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {checkCreator, combineCreators, useCreator, useCreators} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import {PageHeaderAction} from '../../components/common/PageHeader'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import SourceBadge from '../../components/Source/SourceBadge'
import {postReassignedMove, reassignedMoveMessage} from '../../components/Episode/SeasonPlaceNote'
import {toast} from 'react-hot-toast'
import {creatorKindText} from '../../types/creator'
import CreatorHeader from './CreatorHeader'
import './CreatorPages.css'

/** The places a collection lists, short enough for a card: "Videos, Live and 9 more". */
function listedSources(titles: string[]) {
    if (titles.length <= 3) return titles.slice(0, -1).join(', ') + ' and ' + titles[titles.length - 1]
    return `${titles.slice(0, 2).join(', ')} and ${titles.length - 2} more`
}

export default function CreatorPage() {
    const {slug} = useParams()
    const queryClient = useQueryClient()
    const {data: creator, error, isLoading} = useCreator(slug)
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

    if (isLoading) return <section className="view"><p>Loading…</p></section>
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
            toast.success(reassignedMoveMessage(result))
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
    const links = creator.accounts.filter((account) => account.url).map((account) => ({
        label: several ? `Open on ${account.site.name}` : 'Open on the site', url: account.url!,
    }))
    const waiting = creator.accounts.flatMap((account) => account.sections)
        .filter((section) => section.status === 'new' && !section.collectionSlug)
    const episodes = creator.collections.reduce((total, collection) => total + collection.episodeCount, 0)

    return (
        <section className="view creator-view" aria-labelledby="creator-title">
            <CreatorHeader
                title={creator.title} label={creatorKindText(creator)}
                handle={creator.accounts[0]?.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts}
                description={creator.description} links={links} titleId="creator-title"
                actions={mayManage && (
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
                    VODLoft is looking for new playlists and shows. They show on the Edit page when it is done.
                </p>
            )}
            {actionError && <div className="form-error-card" role="alert">{actionError}</div>}

            {waiting.length > 0 && mayManage && (
                <Link className="creator-waiting" to={`/edit-creator/${creator.slug}`}>
                    <FontAwesomeIcon icon={faIcon('fass', 'circle-plus')}/>
                    <span>
                        <b>{waiting.length === 1 ? `New on ${creator.title}: ${waiting[0].title}` : `${waiting.length} new playlists and shows on ${creator.title}`}</b>
                        <span>Choose whether to add {waiting.length === 1 ? 'it' : 'them'} to your library</span>
                    </span>
                    <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')} className="creator-waiting-go"/>
                </Link>
            )}

            <div className="creator-section-group">
                <h2 className="creator-collections-title">
                    Collections <span>{episodes} {episodes === 1 ? 'episode' : 'episodes'}</span>
                </h2>
                {creator.collections.length ? (
                    <div className="creator-collections" role="list">
                        {creator.collections.map((collection) => {
                            const image = toImageUrl(collection.thumbnailLandscapePath)
                            const noun = collection.type === 'music'
                                ? (collection.episodeCount === 1 ? 'track' : 'tracks')
                                : (collection.episodeCount === 1 ? 'video' : 'videos')
                            return (
                                <Link key={collection.slug} className="creator-collection" to={`/collection/${collection.slug}`} role="listitem">
                                    <span className="creator-collection-art">
                                        {image
                                            ? <img src={image} alt="" loading="lazy"/>
                                            : <FontAwesomeIcon icon={collection.type === 'music' ? faIcon('fass', 'music') : faIcon('fass', 'tv')}/>}
                                        {several && <SourceBadge sourceKey={collection.sourceKey} className="creator-collection-source"/>}
                                        <span className="creator-collection-count">{collection.episodeCount} {noun}</span>
                                    </span>
                                    <b>{collection.title}</b>
                                    {collection.links.length > 1 && <span>From {listedSources(collection.links)}</span>}
                                </Link>
                            )
                        })}
                    </div>
                ) : (
                    <p className="creator-empty">
                        None of this {creator.creatorLabel}'s collections are in your library any more.
                        {mayManage && <> Add some on the <Link to={`/edit-creator/${creator.slug}`}>Edit page</Link>.</>}
                    </p>
                )}
            </div>

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
        </section>
    )
}
