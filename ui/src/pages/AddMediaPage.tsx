import {FormEvent, useEffect, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {faIcon} from '../icons/faIcon'

import {toImageUrl} from '../components/Episode/EpisodeCard'
import SourceBadge from '../components/Source/SourceBadge'
import {useQueryClient} from '@tanstack/react-query'
import {addVideo, resolveLink, useMovies, useShows, useSources, useVideos} from '../lib/queries'
import {linkTarget, type MediaLinkTarget} from '../lib/sourceControls'
import {ResolvedLinkRead, SourceFeature, SourceRead, searchName, sourceHas} from '../types/schemas/source'
import {DrmNotice} from '../components/common/DrmProtected'

type AddMediaPageProps = {
    onboarding?: boolean
    onShow?: (target: MediaLinkTarget) => void
    onMovie?: (target: MediaLinkTarget) => void
    onBrowse?: (sourceId: string) => void
    onSkip?: () => void
}

const KIND_LABEL: Record<ResolvedLinkRead['kind'], string> = {
    show: 'Show',
    movie: 'Movie',
    episode: 'Episode',
    video: 'Video',
}

export default function AddMediaPage({onboarding = false, onShow, onMovie, onBrowse, onSkip}: AddMediaPageProps = {}) {
    const navigate = useNavigate()
    const [params] = useSearchParams()
    const {data: sources} = useSources()
    const {data: localShows} = useShows()
    const {data: localMovies} = useMovies()
    const {data: localVideos} = useVideos()
    const queryClient = useQueryClient()
    const [addingVideo, setAddingVideo] = useState(false)
    const [url, setUrl] = useState(params.get('url') ?? '')
    const [link, setLink] = useState<ResolvedLinkRead | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [resolving, setResolving] = useState(false)
    // The Sources that can handle the link's site, kept while another one is tried.
    const [candidates, setCandidates] = useState<SourceRead[]>([])
    const [askedSource, setAskedSource] = useState<string | null>(null)
    const requestRef = useRef<AbortController | null>(null)

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
        const initial = params.get('url')
        if (initial) void lookUp(initial)
        return () => requestRef.current?.abort()
        // Only look up the link the page was opened with.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const submit = (event: FormEvent) => {
        event.preventDefault()
        void lookUp(url)
    }

    // A show link from a Source that cannot add shows yet, such as a playlist at a video site.
    const showsUnsupported = !!link && (link.kind === 'show' || link.kind === 'episode') && !sourceHas(link.source, SourceFeature.SHOWS)
    const target = link && !showsUnsupported ? linkTarget(link) : null
    const localShow = target?.kind === 'show'
        ? localShows?.find((show) => show.slug === target.slug && show.sourceKey === target.sourceKey)
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
        if (onShow) {
            onShow(target)
            return
        }
        if (localShow) navigate(`/show/${localShow.slug}`)
        else navigate(`/add-show?url=${encodeURIComponent(target.url)}`)
    }

    // A Source with a catalogue is browsed; one without is searched. Onboarding only browses.
    const browseSources = (sources ?? []).filter((source) => sourceHas(source, SourceFeature.BROWSE) || (!onboarding && sourceHas(source, SourceFeature.SEARCH)))
    const browse = (source: SourceRead) => {
        if (!sourceHas(source, SourceFeature.BROWSE)) navigate(`/browse/${encodeURIComponent(source.id)}`)
        else if (onBrowse) onBrowse(source.id)
        else navigate('/browse')
    }

    const image = toImageUrl(link?.preview.imageUrl)
    const actionLabel = (() => {
        if (!target) return null
        if (target.kind === 'video') return localVideo ? 'Open video' : addingVideo ? 'Adding video…' : 'Add this video'
        if (target.kind === 'movie') return localMovie ? 'Open movie' : 'Continue with this movie'
        if (localShow) return 'Open show'
        return link?.kind === 'episode' ? 'Add its show' : 'Continue with this show'
    })()

    return (
        <section className={`view add-media-view${onboarding ? ' add-media-view--onboarding' : ''}`} aria-labelledby="add-media-title">
            <div className="view-header">
                <div>
                    <h1 id="add-media-title">{onboarding ? 'Add your first media' : 'Add media'}</h1>
                    <p className="view-description">
                        Paste a link to a show, an episode, a movie or a video. VODLoft finds the service it comes from and
                        lets you confirm everything before anything is saved.
                    </p>
                </div>
                {onSkip && (
                    <button className="btn" type="button" onClick={onSkip}>Skip for now</button>
                )}
            </div>

            <form className="add-media-form" onSubmit={submit}>
                <label className="sr-only" htmlFor="add-media-url">Link</label>
                <input
                    id="add-media-url"
                    className="input add-media-input"
                    type="text"
                    inputMode="url"
                    autoComplete="off"
                    placeholder="https://…"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                />
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
                        <p>{[KIND_LABEL[link.kind], link.site, link.preview.authorName].filter(Boolean).join(' · ')}</p>
                        <h2>{link.preview.title}</h2>
                        {link.preview.description && (
                            <p className="add-media-preview-description">{link.preview.description}</p>
                        )}
                        {link.drmProtected && <DrmNotice/>}
                        {target ? (
                            <div className="add-media-preview-actions">
                                <button className="btn btn-primary" type="button" onClick={proceed} disabled={addingVideo}>
                                    {actionLabel}
                                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')}/>
                                </button>
                            </div>
                        ) : showsUnsupported ? (
                            <p role="alert">
                                VODLoft cannot add channels or playlists from {link.source.name} yet. Paste the link to one video instead.
                            </p>
                        ) : (
                            <p role="alert">
                                {link.source.name} did not say which show this episode belongs to. Paste the show's link instead.
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
