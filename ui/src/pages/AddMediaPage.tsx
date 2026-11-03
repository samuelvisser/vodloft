import {FormEvent, useEffect, useRef, useState} from 'react'
import {canUseSource} from '../lib/access'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import SourceBadge from '../components/Source/SourceBadge'
import {useQueryClient} from '@tanstack/react-query'
import {addVideo, resolveLink, useMovies, useCollections, useSources, useVideos} from '../lib/queries'
import {linkTarget, type MediaLinkTarget} from '../lib/sourceControls'
import {ResolvedLinkRead, SourceFeature, SourceRead, kindName, searchName, sourceHas} from '../types/schemas/source'
import {DrmNotice} from '../components/common/DrmProtected'
import {SubscriptionNotice} from '../components/common/NeedsSubscription'
import {ClearInputButton} from '../components/common/ClearInputButton'

type AddMediaPageProps = {
    onboarding?: boolean
    onCollection?: (target: MediaLinkTarget) => void
    onMovie?: (target: MediaLinkTarget) => void
    onBrowse?: (sourceId: string) => void
    onBack?: () => void
    onSkip?: () => void
    /** The link to look up right away, when it does not come from the page's own address. */
    initialUrl?: string
}

const KIND_LABEL: Record<ResolvedLinkRead['kind'], string> = {
    collection: 'Collection',
    movie: 'Movie',
    episode: 'Episode',
    video: 'Video',
}

export default function AddMediaPage({onboarding = false, onCollection, onMovie, onBrowse, onBack, onSkip, initialUrl}: AddMediaPageProps = {}) {
    const navigate = useNavigate()
    const [params] = useSearchParams()
    const {data: sources} = useSources()
    const {data: localCollections} = useCollections()
    const {data: localMovies} = useMovies()
    const {data: localVideos} = useVideos()
    const queryClient = useQueryClient()
    const [addingVideo, setAddingVideo] = useState(false)
    const [url, setUrl] = useState(initialUrl ?? params.get('url') ?? '')
    const [link, setLink] = useState<ResolvedLinkRead | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [resolving, setResolving] = useState(false)
    // The Sources that can handle the link's site, kept while another one is tried.
    const [candidates, setCandidates] = useState<SourceRead[]>([])
    const [askedSource, setAskedSource] = useState<string | null>(null)
    const requestRef = useRef<AbortController | null>(null)
    const inputRef = useRef<HTMLInputElement>(null)

    const lookUp = async (value: string, sourceKey?: string) => {
        const trimmed = value.trim()
        if (!trimmed) return
        if (!sourceKey) setCandidates([])
        setAskedSource(sourceKey ?? null)
        requestRef.current?.abort()
        const controller = new AbortController()
        requestRef.current = controller
        setResolving(true)
        setError(null)
        setLink(null)
        try {
            const resolved = await resolveLink(trimmed, controller.signal, sourceKey)
            if (!controller.signal.aborted) {
                setLink(resolved)
                if (resolved.candidates.length) setCandidates(resolved.candidates)
            }
        } catch (exc) {
            if (!controller.signal.aborted) setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            if (!controller.signal.aborted) setResolving(false)
        }
    }

    useEffect(() => {
        const initial = initialUrl ?? params.get('url')
        if (initial) void lookUp(initial)
        return () => requestRef.current?.abort()
        // Only look up the link the page was opened with.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const clear = () => {
        requestRef.current?.abort()
        setUrl('')
        setLink(null)
        setError(null)
        setCandidates([])
        setAskedSource(null)
        setResolving(false)
        inputRef.current?.focus()
    }

    const submit = (event: FormEvent) => {
        event.preventDefault()
        void lookUp(url)
    }

    // A collection link from a Source that cannot add collections yet, such as a playlist at a video site.
    const collectionsUnsupported = !!link && (link.kind === 'collection' || link.kind === 'episode') && !sourceHas(link.source, SourceFeature.COLLECTIONS)
    const target = link && !collectionsUnsupported ? linkTarget(link) : null
    const localCollection = target?.kind === 'collection'
        ? localCollections?.find((collection) => collection.slug === target.slug && collection.sourceKey === target.sourceKey)
        : undefined
    const localMovie = target?.kind === 'movie'
        ? localMovies?.find((movie) => movie.slug === target.slug && movie.sourceKey === target.sourceKey)
        : undefined

    const localVideo = target?.kind === 'video'
        ? localVideos?.find((video) => video.slug === target.slug && video.sourceKey === target.sourceKey)
        : undefined

    const openVideo = async (videoTarget: MediaLinkTarget) => {
        if (localVideo) {
            navigate(`/video/${localVideo.id}`)
            return
        }
        setAddingVideo(true)
        setError(null)
        try {
            const video = await addVideo(videoTarget.url, videoTarget.sourceKey)
            await queryClient.invalidateQueries({queryKey: ['videos']})
            navigate(`/video/${video.id}`)
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setAddingVideo(false)
        }
    }

    const proceed = () => {
        if (!target) return
        if (target.kind === 'video') {
            void openVideo(target)
            return
        }
        if (target.kind === 'movie') {
            if (onMovie) onMovie(target)
            else navigate(`/movie/${target.slug}`)
            return
        }
        if (onCollection) {
            onCollection(target)
            return
        }
        if (localCollection) navigate(`/collection/${localCollection.slug}`)
        else navigate(`/add-collection?url=${encodeURIComponent(target.url)}`)
    }

    // A Source with a catalogue is browsed; one without is searched.
    const browseSources = (sources ?? []).filter((source) => canUseSource(source.id) && (sourceHas(source, SourceFeature.BROWSE) || sourceHas(source, SourceFeature.SEARCH)))
    const browse = (source: SourceRead) => {
        if (onBrowse) onBrowse(source.id)
        else if (!sourceHas(source, SourceFeature.BROWSE)) navigate(`/browse/${encodeURIComponent(source.id)}`)
        else navigate('/browse')
    }

    // Hand the link to the Quick download page: one video, episode or movie that can be downloaded.
    const quickDownloadable = !!link && link.kind !== 'collection' && !link.drmProtected && !link.needsSubscription
    const quickDownload = () => {
        if (!link) return
        navigate(`/quick-download?url=${encodeURIComponent(link.url)}&source=${encodeURIComponent(link.source.id)}`)
    }

    const image = toImageUrl(link?.preview.imageUrl)
    const actionLabel = (() => {
        if (!target) return null
        if (target.kind === 'video') return localVideo ? 'Open video' : addingVideo ? 'Adding video…' : 'Add this video'
        if (target.kind === 'movie') return localMovie ? 'Open movie' : 'Continue with this movie'
        if (localCollection) return 'Open collection'
        return link?.kind === 'episode' ? 'Add its collection' : 'Continue with this collection'
    })()

    return (
        <section className={`view add-media-view${onboarding ? ' add-media-view--onboarding' : ''}`} aria-labelledby="add-media-title">
            <div className="view-header">
                <div>
                    <h1 id="add-media-title">{onboarding ? 'Add your first media' : 'Add media'}</h1>
                    <p className="view-description">
                        Paste a link to a collection, an episode, a movie or a video. VODLoft finds the service it comes from and
                        lets you confirm everything before anything is saved.
                    </p>
                </div>
                {(onBack || onSkip) && (
                    <div className="add-media-header-actions">
                        {onBack && <button className="btn" type="button" onClick={onBack}>Back</button>}
                        {onSkip && <button className="btn" type="button" onClick={onSkip}>Skip for now</button>}
                    </div>
                )}
            </div>

            <form className="add-media-form" onSubmit={submit}>
                <label className="sr-only" htmlFor="add-media-url">Link</label>
                <span className="add-media-field">
                    <input
                        ref={inputRef}
                        id="add-media-url"
                        className="input add-media-input"
                        type="text"
                        inputMode="url"
                        autoComplete="off"
                        placeholder="https://…"
                        value={url}
                        onChange={(event) => setUrl(event.target.value)}
                    />
                    {url && <ClearInputButton onClear={clear} label="Clear the link"/>}
                </span>
                <button className="btn btn-primary" type="submit" disabled={resolving || !url.trim()}>
                    {resolving ? 'Looking up…' : 'Look up'}
                </button>
            </form>

            {candidates.length > 1 && (
                <div className="add-media-sources" role="group" aria-label="Source to look the link up with">
                    <span>Look up with</span>
                    {candidates.map((candidate) => {
                        const current = (link?.source.id ?? askedSource) === candidate.id
                        return (
                            <button
                                key={candidate.id}
                                type="button"
                                className={`btn${current ? ' btn-primary' : ''}`}
                                aria-pressed={current}
                                disabled={resolving}
                                onClick={() => { if (!current) void lookUp(url, candidate.id) }}
                            >
                                {candidate.name}
                            </button>
                        )
                    })}
                </div>
            )}

            {error && <div className="form-error-card add-media-error" role="alert">{error}</div>}

            {link && (
                <article className="add-media-preview" aria-label="Link preview">
                    {image && (
                        <div className="add-media-preview-art">
                            <img src={image} alt="" loading="lazy" decoding="async"/>
                        </div>
                    )}
                    <div className="add-media-preview-copy">
                        <SourceBadge sourceKey={link.source.id}/>
                        <p>{[kindName(link.source, link.kind, KIND_LABEL[link.kind]), link.site, link.preview.authorName].filter(Boolean).join(' · ')}</p>
                        <h2>{link.preview.title}</h2>
                        {link.preview.description && (
                            <p className="add-media-preview-description">{link.preview.description}</p>
                        )}
                        {link.drmProtected && <DrmNotice/>}
                        {!link.drmProtected && link.needsSubscription && !link.source.subscriptionActive && <SubscriptionNotice sourceKey={link.source.id}/>}
                        {target ? (
                            <div className="add-media-preview-actions">
                                <button className="btn btn-primary" type="button" onClick={proceed} disabled={addingVideo}>
                                    {actionLabel}
                                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')}/>
                                </button>
                                {quickDownloadable && !onboarding && (
                                    <button className="btn" type="button" onClick={quickDownload}
                                            title="Download the file without adding it to your library">
                                        <FontAwesomeIcon icon={faIcon('fass', 'bolt')}/>
                                        Quick download
                                    </button>
                                )}
                            </div>
                        ) : collectionsUnsupported ? (
                            <p role="alert">
                                VODLoft cannot add channels or playlists from {link.source.name} yet. Paste the link to one video instead.
                            </p>
                        ) : (
                            <p role="alert">
                                {link.source.name} did not say which collection this episode belongs to. Paste the collection's link instead.
                            </p>
                        )}
                    </div>
                </article>
            )}

            {browseSources.length > 0 && (
                <div className="add-media-browse">
                    <h2>Or browse</h2>
                    <div className="add-media-browse-list">
                        {browseSources.map((source) => (
                            <button key={source.id} className="btn" type="button" onClick={() => browse(source)}>
                                <FontAwesomeIcon icon={faIcon('fass', sourceHas(source, SourceFeature.BROWSE) ? 'compass' : 'magnifying-glass')}/>
                                {sourceHas(source, SourceFeature.BROWSE) ? `Browse ${source.name}` : `Search ${searchName(source)}`}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </section>
    )
}
