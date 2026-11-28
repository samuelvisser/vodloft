import {useEffect, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {can, canUseSource} from '../../lib/access'
import {addVideo, resolveLink, useCollections, useMovies, useVideos} from '../../lib/queries'
import {fetchQuickDownloadOptions, type QuickDownloadSettingsForUser} from '../../lib/quickDownloads'
import {linkTarget} from '../../lib/sourceControls'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import SourceBadge from '../../components/Source/SourceBadge'
import {DrmNotice} from '../../components/common/DrmProtected'
import {AccessNotice} from '../../components/common/AccessLocked'
import LookupSteps from '../../pages/creator/LookupSteps'
import {capitalized} from '../../types/creator'
import {SourceFeature, kindNames, sourceHas, type LinkFirstLookRead, type ResolvedLinkRead} from '../../types/schemas/source'
import type {QuickDownloadOptions} from '../../types/schemas/quick_download'
import type {ProgressStep} from '../../types/progress'
import {ext, messageOf, signedOut, unreachable} from '../browser'
import QuickDownloadForm from './QuickDownloadForm'

type PageMediaProps = {
    address: string
    pageUrl: string
    settings: QuickDownloadSettingsForUser | undefined
    /** VODLoft stopped answering, or signed the user out, while the page was looked up. */
    onLost: (reason: 'vodloft' | 'sign-in') => void
}

/** Open a page of VODLoft in a new tab, and close the popup. */
function openInVodloft(address: string, path: string) {
    void ext.tabs.create({url: `${address}${path}`})
    window.close()
}

/**
 * The media of the page the user is on, as Add media shows a link: looked up as soon as the popup opens, with a
 * first look while the rest comes, and the same buttons. A collection opens Add collection in VODLoft, which asks
 * how to keep it; a video is added right here. Quick download is chosen and queued in the popup itself.
 */
export default function PageMedia({address, pageUrl, settings, onLost}: PageMediaProps) {
    const {data: localCollections} = useCollections()
    const {data: localMovies} = useMovies()
    const {data: localVideos} = useVideos()
    const [link, setLink] = useState<ResolvedLinkRead | null>(null)
    const [firstLook, setFirstLook] = useState<LinkFirstLookRead | null>(null)
    const [steps, setSteps] = useState<ProgressStep[]>([])
    const [error, setError] = useState<string | null>(null)
    const [resolving, setResolving] = useState(true)
    const [addingVideo, setAddingVideo] = useState(false)
    const [addedVideo, setAddedVideo] = useState<number | null>(null)
    const [quickOpen, setQuickOpen] = useState(false)
    const [options, setOptions] = useState<QuickDownloadOptions | null>(null)
    const [optionsError, setOptionsError] = useState<string | null>(null)
    const optionsAsked = useRef(false)

    const lost = (exc: unknown) => {
        if (unreachable(exc)) onLost('vodloft')
        else if (signedOut(exc)) onLost('sign-in')
        else return false
        return true
    }

    useEffect(() => {
        const controller = new AbortController()
        resolveLink(pageUrl, controller.signal, undefined, {
            onPlan: (plan) => { if (!controller.signal.aborted) setSteps(plan) },
            onPreview: (preview) => { if (!controller.signal.aborted) setFirstLook(preview) },
        }).then((resolved) => {
            if (!controller.signal.aborted) setLink(resolved)
        }, (exc) => {
            if (!controller.signal.aborted && !lost(exc)) setError(messageOf(exc))
        }).finally(() => {
            if (!controller.signal.aborted) setResolving(false)
        })
        return () => controller.abort()
        // Only the page the popup opened on.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pageUrl])

    // What the link is: the full lookup's answer, or until it comes, what the first look could already tell, as on
    // Add media. A collection known only by its link opens Add collection, which needs no more.
    const firstLookSlug = firstLook?.slug ?? (firstLook?.kind === 'collection' ? '' : null)
    const known = link ?? (firstLook?.kind && firstLookSlug !== null && firstLook.url ? {
        source: firstLook.source, kind: firstLook.kind, slug: firstLookSlug, url: firstLook.url, collectionSlug: null,
        collectionUrl: null, preview: {...firstLook, title: firstLook.title ?? ''}, drmProtected: false, accessLocked: false,
    } : null)
    const collectionsUnsupported = !!known && (known.kind === 'collection' || known.kind === 'episode') && !sourceHas(known.source, SourceFeature.COLLECTIONS)
    const target = known && !collectionsUnsupported ? linkTarget(known) : null
    const localCollection = target?.kind === 'collection'
        ? localCollections?.find((collection) => collection.slug === target.slug && collection.sourceKey === target.sourceKey)
        : undefined
    const localMovie = target?.kind === 'movie'
        ? localMovies?.find((movie) => movie.slug === target.slug && movie.sourceKey === target.sourceKey)
        : undefined
    const localVideoId = addedVideo ?? (target?.kind === 'video'
        ? localVideos?.find((video) => video.slug === target.slug && video.sourceKey === target.sourceKey)?.id
        : undefined)

    const mayAdd = can('add_media') && !!known && canUseSource(known.source.id)
    const quickDownloadable = can('quick_downloads') && !!known && known.kind !== 'collection' && known.kind !== 'creator'
        && !known.drmProtected && !known.accessLocked

    // Formats take another lookup: start it as soon as the page is known to be one file, so it is ready, or nearly,
    // when the user chooses Quick download.
    useEffect(() => {
        if (!quickDownloadable || !known || optionsAsked.current) return
        optionsAsked.current = true
        fetchQuickDownloadOptions(known.url, undefined, known.source.id).then(setOptions, (exc) => {
            if (!lost(exc)) setOptionsError(messageOf(exc))
        })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [quickDownloadable, known?.url])

    const proceed = async () => {
        if (!target) return
        if (target.kind === 'video') {
            if (localVideoId != null) return openInVodloft(address, `/video/${localVideoId}`)
            setAddingVideo(true)
            setError(null)
            try {
                const video = await addVideo(target.url, target.sourceKey)
                setAddedVideo(video.id)
            } catch (exc) {
                if (!lost(exc)) setError(messageOf(exc))
            } finally {
                setAddingVideo(false)
            }
            return
        }
        if (target.kind === 'movie') return openInVodloft(address, `/movie/${encodeURIComponent(target.slug)}`)
        if (localCollection) return openInVodloft(address, `/collection/${encodeURIComponent(localCollection.slug)}`)
        openInVodloft(address, `/add-collection?url=${encodeURIComponent(target.url)}`)
    }

    const actionLabel = (() => {
        if (!target) return null
        if (target.kind === 'video') return localVideoId != null ? 'Open video' : addingVideo ? 'Adding to library…' : 'Add to library'
        if (target.kind === 'movie') return localMovie ? 'Open movie' : 'Add to library'
        if (localCollection) return 'Open collection'
        return known?.kind === 'episode' ? 'Add its collection' : 'Add as collection'
    })()

    const actions = target && (mayAdd || quickDownloadable) && (
        <div className="add-media-preview-actions">
            {mayAdd && (
                <button className="btn btn-primary" type="button" onClick={() => void proceed()} disabled={addingVideo}>
                    {actionLabel}
                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')}/>
                </button>
            )}
            {quickDownloadable && (
                <button className={`btn${quickOpen ? ' is-active' : ''}`} type="button" aria-expanded={quickOpen}
                        onClick={() => setQuickOpen((open) => !open)} title="Download the file without adding it to your library">
                    <FontAwesomeIcon icon={faIcon('fass', 'bolt')}/>
                    Quick download
                </button>
            )}
        </div>
    )

    const image = toImageUrl(link?.preview.imageUrl ?? firstLook?.imageUrl)
    const added = addedVideo != null && <p className="quick-ok extension-note" role="status">Added to your library.</p>
    const quick = quickOpen && known && (
        optionsError ? <p className="form-error-card" role="alert">{optionsError}</p> : (
            <QuickDownloadForm
                url={known.url}
                sourceKey={known.source.id}
                title={known.preview.title || firstLook?.title || known.url}
                imageUrl={link?.preview.imageUrl ?? firstLook?.imageUrl ?? null}
                options={options}
                settings={settings}
                waiting={null}
                onQueued={() => setQuickOpen(false)}
            />
        )
    )

    if (error && !link) return <div className="form-error-card extension-problem" role="alert">{error}</div>

    if (resolving && !link) {
        return (
            <>
                <article className="add-media-preview add-media-preview--loading creator-skeleton" aria-label="Looking up this page" aria-busy="true">
                    {image ? (
                        <div className="add-media-preview-art"><img src={image} alt="" decoding="async"/></div>
                    ) : <span className="add-media-preview-art skeleton-block" aria-hidden="true"/>}
                    <div className="add-media-preview-copy">
                        {firstLook?.title ? (
                            <div className="add-media-preview-first-look">
                                {firstLook.authorName && <p>{firstLook.authorName}</p>}
                                <h2>{firstLook.title}</h2>
                            </div>
                        ) : (
                            <div className="creator-skeleton-copy" aria-hidden="true">
                                <span className="skeleton-block creator-skeleton-line creator-skeleton-line--kind"/>
                                <span className="skeleton-block creator-skeleton-line creator-skeleton-line--title-small"/>
                            </div>
                        )}
                        <LookupSteps steps={steps} first="Finding the service the page comes from"/>
                        {actions}
                    </div>
                </article>
                {quick}
            </>
        )
    }

    if (!link) return null
    return (
        <>
            <article className="add-media-preview" aria-label="What VODLoft found on this page">
                {image && <div className="add-media-preview-art"><img src={image} alt="" decoding="async"/></div>}
                <div className="add-media-preview-copy">
                    <SourceBadge sourceKey={link.source.id}/>
                    <p>{[capitalized(kindNames(link.source, link.kind)?.singular ?? ''), link.site, link.preview.authorName].filter(Boolean).join(' · ')}</p>
                    <h2>{link.preview.title}</h2>
                    {link.drmProtected && <DrmNotice/>}
                    {!link.drmProtected && link.accessLocked && <AccessNotice item={link}/>}
                    {error && <p className="form-error-card" role="alert">{error}</p>}
                    {target ? actions : link.kind === 'creator' ? (
                        <p role="alert">
                            This is the page of {kindNames(link.source, 'creator')?.a}. Open one of
                            their {kindNames(link.source, 'collection')?.plural} to add it instead.
                        </p>
                    ) : collectionsUnsupported ? (
                        <p role="alert">VODLoft cannot add creators or playlists from {link.source.name} yet. Open one video instead.</p>
                    ) : (
                        <p role="alert">{link.source.name} did not say which collection this episode belongs to. Open the collection&apos;s page instead.</p>
                    )}
                    {added}
                </div>
            </article>
            {quick}
        </>
    )
}
