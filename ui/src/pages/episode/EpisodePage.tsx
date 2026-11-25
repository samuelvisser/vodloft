import {sourceControls} from '../../lib/sourceControls'
import {useState} from 'react'
import {Link, useLocation, useParams} from 'react-router-dom'
import toast from '../../lib/toast'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {useCollection, useEpisode, useEpisodeDownloads, useLocalMediaProfiles, usePublishStatusLabels, useSkippedByFilter, useSourceLookup, useWaitingForCountdown} from '../../lib/queries'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {isCollectionLocalMediaProfileAvailableFor, isLocalMediaProfileAvailableForSite} from '../../types/local_media_profile'
import {EpisodePublishStatus, PUBLISH_STATUS_LABELS} from '../../types/episode'
import {MediaDownloadViewRead} from '../../types/schemas/media_download'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import DisabledReason from '../../components/common/DisabledReason'
import {siteName} from '../../lib/siteName'
import {EpisodeDownloadRow} from '../../components/Episode/EpisodeDownloadRow'
import {useActiveOperation} from '../../components/OperationNotifier/OperationNotifier'
import {formatDate} from "../../utils/formatting";
import './EpisodePage.css'
import {faIcon} from '../../icons/faIcon'
import SiteLink from '../../components/common/SiteLink'
import {DrmBadge, DrmNotice} from '../../components/common/DrmProtected'
import {RemovedBadge, ExpiredBadge} from '../../components/common/RemovedFromSource'
import SeasonPlaceNote, {MovedBadge, useSeasonPlace} from '../../components/Episode/SeasonPlaceNote'
import ReconcileDialog from '../../components/ReconcileDialog/ReconcileDialog'
import {can} from '../../lib/access'
import {AccessNotice, ItemAccessBadge} from '../../components/common/AccessLocked'
import SponsorBlockTimeline from '../../components/Episode/SponsorBlockTimeline'
import {apiUrl} from '../../lib/api'
import DurationPill from '../../components/common/DurationPill'
import EpisodeTypePill from '../../components/Episode/EpisodeTypePill'
import {fileWordsFor, wordsFor} from '../../lib/collectionWords'
import {addLocalMediaProfilePath} from '../../types/local_media_profile'
import Breadcrumb from '../../components/common/Breadcrumb/Breadcrumb'
import LinkedText from '../../components/common/LinkedText'
import {nameInText} from '../../lib/nameInText'


const OPERATION_STARTING_MESSAGE = 'This task is starting...'

/** A date on the summary line, shown with an icon only. What it is shows on hover, focus or a tap. */
function SummaryDate({label, icon, value, placement}: {
    label: string
    icon: IconProp
    value: Date | string | null | undefined
    placement: 'below' | 'below-start'
}) {
    const text = `${label} ${formatDate(value)}`
    return (
        <DisabledReason reason={text} placement={placement} className="episode-summary-date">
            {({describedBy, explain}) => (
                <span
                    className="episode-summary-item"
                    tabIndex={0}
                    aria-describedby={describedBy}
                    onClick={explain}
                >
                    <FontAwesomeIcon icon={icon} aria-hidden="true"/>
                    <span className="sr-only">{label} </span>
                    <span>{formatDate(value)}</span>
                </span>
            )}
        </DisabledReason>
    )
}

function EpisodePageSkeleton() {
    return (
        <section
            className="view episode-view episode-page-skeleton"
            aria-label="Loading"
            aria-busy="true"
        >
            <article className="episode-details" aria-hidden="true">
                <div className="episode-page-skeleton-block episode-page-skeleton-breadcrumb"/>
                <div className="episode-page-skeleton-block episode-page-skeleton-cover"/>
                <div className="episode-page-skeleton-header">
                    <div className="episode-page-skeleton-block episode-page-skeleton-title"/>
                    <div className="episode-page-skeleton-meta">
                        <div className="episode-page-skeleton-block episode-page-skeleton-meta-item"/>
                        <div className="episode-page-skeleton-block episode-page-skeleton-meta-item episode-page-skeleton-meta-item-wide"/>
                    </div>
                </div>
                <div className="episode-page-skeleton-description">
                    <div className="episode-page-skeleton-block episode-page-skeleton-section-title"/>
                    <div className="episode-page-skeleton-block episode-page-skeleton-line"/>
                    <div className="episode-page-skeleton-block episode-page-skeleton-line episode-page-skeleton-line-medium"/>
                    <div className="episode-page-skeleton-block episode-page-skeleton-line episode-page-skeleton-line-short"/>
                </div>
            </article>

        </section>
    )
}

export default function EpisodePage() {
    const {id: collectionId, episodeId} = useParams()
    const startOperation = useStartOperation()
    const [metadataRefreshStarting, setMetadataRefreshStarting] = useState(false)

    const {data: collection, isPending: isCollectionPending, isFetching: isCollectionFetching, error} = useCollection(collectionId)
    const words = wordsFor(collection)
    const {data: skipped} = useSkippedByFilter(collection?.id)
    const {
        data: episode,
        isPending: isEpisodePending,
        isFetching: isEpisodeFetching,
    } = useEpisode(episodeId)
    const {data: profiles, error: profilesError} = useLocalMediaProfiles()
    // A Music collection's files are tracks while only profiles for Music that download audio only are offered for it.
    const fileWords = fileWordsFor(collection, profiles
        ?.filter((profile) => isCollectionLocalMediaProfileAvailableFor(profile, collection?.type)))
    const {data: waitingForCountdown} = useWaitingForCountdown(
        collection?.id,
        String(episode?.publishStatus) === 'published_preliminary',
    )
    const sourceLookup = useSourceLookup()
    const sourceName = sourceLookup.name(episode?.sourceKey ?? collection?.sourceKey)
    // The Source's release date marks when the item was finished and put up, not when it began.
    const releasedAtEnd = sourceLookup.get(episode?.sourceKey ?? collection?.sourceKey)?.releaseDate === 'end'
    const {data: publishStatusLabels} = usePublishStatusLabels(episode?.sourceKey)
    const {
        data: downloads,
        error: downloadsError,
        hasDomainData: hasDownloadState,
    } = useEpisodeDownloads(episodeId)
    const location = useLocation()
    // Its collection's playlists put it in another season, where it waits for the user to move it.
    const {data: seasonPlace} = useSeasonPlace(episodeId)
    const moved = !!seasonPlace?.belongsElsewhere
    const [reconciling, setReconciling] = useState(false)
    const collectionProfiles = profiles?.filter((profile) => (
        isCollectionLocalMediaProfileAvailableFor(profile, collection?.type)
        // A profile limited to other Sites still shows the download it already made.
        && (isLocalMediaProfileAvailableForSite(profile, collection?.site?.key)
            || !!downloads?.some((download) => download.localMediaProfileId === profile.id))
    ))
    const metadataRefreshOperation = useActiveOperation(
        'episode.refresh_metadata',
        'episode',
        episode?.id ?? null,
    )
    const metadataRefreshBusy = metadataRefreshStarting || metadataRefreshOperation !== undefined

    if (!collectionId) {
        return (
            <section className="view episode-view">
                <div className="view-header">
                    <h1>{words.episode.Singular}</h1>
                </div>
                <p>Collection not found.</p>
                <p><Link to="/">Go home</Link></p>
            </section>
        )
    }

    if (!collection && (isCollectionPending || isCollectionFetching)) return <EpisodePageSkeleton/>

    if (!collection) {
        return (
            <section className="view episode-view">
                <div className="view-header">
                    <h1>{words.episode.Singular}</h1>
                </div>
                <p>{(error as any)?.message ?? 'Collection not found.'}</p>
                <p><Link to="/">Go home</Link></p>
            </section>
        )
    }

    if (!episode && (isEpisodePending || isEpisodeFetching)) return <EpisodePageSkeleton/>

    if (!episode) {
        return (
            <section className="view episode-view">
                <div className="view-header">
                    <h1>{words.episode.Singular}</h1>
                </div>
                <p>{words.episode.Singular} not found.</p>
                <p><Link to={`/collection/${collectionId}`}>Back to collection</Link></p>
            </section>
        )
    }

    const publishStatus = String(episode.publishStatus)
    const sourceStatus = publishStatusLabels?.[publishStatus]
    const statusLabel = sourceStatus?.label ?? PUBLISH_STATUS_LABELS[publishStatus] ?? publishStatus
    const isLive = publishStatus === 'live' || publishStatus === EpisodePublishStatus.live
    const isUpcoming = publishStatus === 'scheduled' || publishStatus === 'delayed'
    // An upcoming episode shows when it is due to start instead of when it was released.
    const startsAt = isUpcoming ? episode.scheduledDate : null
    const containsCountdown = (
        publishStatus === 'published_preliminary'
        || publishStatus === EpisodePublishStatus.publishedPreliminary
    )
    const isDownloadable = (
        containsCountdown
        || publishStatus === 'published_final'
        || publishStatus === EpisodePublishStatus.publishedFinal
    )
    // Media protected by DRM or only given to members or subscribers cannot be downloaded. A collection whose own
    // yt-dlp options allow unplayable formats lets yt-dlp try media protected by DRM.
    const drmBlocked = episode.drmProtected && !collection.allowsUnplayableFormats
    const locked = drmBlocked || episode.accessLocked
    const downloadStateError = (profiles === undefined ? profilesError : null)
        ?? (!hasDownloadState ? downloadsError : null)

    const coverUrl: string = episode.thumbnailLandscapePath
        || episode.backgroundImagePath
        || episode.thumbnailPortraitPath
        || `https://placehold.co/960x540/png?text=${encodeURIComponent(words.episode.Singular)}+%23${episode.index}`

    const downloadByProfileId = new Map<number, MediaDownloadViewRead>(
        (downloads ?? []).map((d) => [d.localMediaProfileId, d]),
    )
    // When the episode was first downloaded, by any profile that still has its file.
    const firstDownloadedAt = (downloads ?? []).reduce<Date | null>((first, download) => {
        if (download.artifactStatus !== 'available' || !download.firstDownloadedAt) return first
        return first === null || download.firstDownloadedAt.getTime() < first.getTime()
            ? download.firstDownloadedAt
            : first
    }, null)
    const siteLabel = collection.site?.name ?? (episode.sharingUrl ? siteName(episode.sharingUrl) : null) ?? sourceName
    const detailsChecked = episode.metadataRefreshedAt
        ? `Details checked ${formatDate(episode.metadataRefreshedAt)}`
        : undefined

    const refreshMetadata = async () => {
        if (metadataRefreshBusy) return

        setMetadataRefreshStarting(true)
        try {
            const base = apiUrl()
            await startOperation(
                `${base}/episodes/${encodeURIComponent(episode.slug)}/refresh-metadata`,
                {method: 'POST'},
            )
            toast.success('Info refresh started')
        } catch (error) {
            const detail = error instanceof OperationStartError ? error.message : undefined
            toast.error(detail || 'Could not start the info refresh')
        } finally {
            setMetadataRefreshStarting(false)
        }
    }

    return (
        <section className="view episode-view" aria-labelledby="episode-title">
            <article className="episode-details" aria-label={`${words.episode.Singular} details`}>
                {/* The buttons share the breadcrumb's row, so the title below gets the full width. */}
                <div className="episode-topbar">
                    <Breadcrumb items={[
                        {label: 'Library', to: '/library'},
                        {label: collection.title, to: (location.state as {fromCollection?: string} | null)?.fromCollection ?? `/collection/${collectionId}`},
                    ]}/>
                    <div className="episode-title-actions">
                        {episode.sharingUrl && (
                            <SiteLink className="btn-secondary episode-open-link" url={episode.sharingUrl} siteName={siteLabel} site={collection.site}/>
                        )}
                        <ActionMenu
                            items={[
                                ...(sourceControls(collection).metadataRefresh ? [{
                                    label: `Refresh info from ${siteLabel}`,
                                    description: detailsChecked,
                                    icon: faIcon('fass', 'arrows-rotate'),
                                    disabled: metadataRefreshBusy,
                                    disabledReason: metadataRefreshStarting
                                        ? OPERATION_STARTING_MESSAGE
                                        : metadataRefreshOperation
                                            ? `VODLoft is refreshing the info of this ${words.episode.singular}.`
                                            : undefined,
                                    operation: metadataRefreshOperation,
                                    onSelect: () => void refreshMetadata(),
                                }] : []),
                                ...(moved && can('library', 'manage') ? [{
                                    label: `Move to its new ${words.season.singular}`,
                                    description: `Moves the ${words.episode.singular} and renames its files to match`,
                                    icon: faIcon('fass', 'arrow-right-arrow-left'),
                                    onSelect: () => setReconciling(true),
                                }] : []),
                            ]}
                            note={sourceControls(collection).metadataRefresh ? undefined : detailsChecked}
                        />
                    </div>
                </div>

                <div className="episode-cover">
                    <img src={coverUrl} alt={`${words.episode.Singular} cover`}/>
                    {(episode.duration > 0 || isUpcoming) && (
                        <span className="thumb-corner thumb-corner-large">
                            <DurationPill seconds={episode.duration} upcoming={isUpcoming} large/>
                        </span>
                    )}
                    {isLive && (
                        <span className="episode-live-badge" aria-label={`${words.episode.Singular} is live`}>Live</span>
                    )}
                </div>

                <header className="episode-header">
                    <h1 id="episode-title" className="episode-title-text">{episode.title}</h1>
                    <div className="episode-summary" aria-label={`${words.episode.Singular} metadata`}>
                        <EpisodeTypePill sourceKey={episode.sourceKey} type={episode.episodeType} asText/>
                        {episode.drmProtected && <DrmBadge asText unplayableAllowed={collection.allowsUnplayableFormats}/>}
                        <ItemAccessBadge item={episode} asText/>
                        {episode.removedBy
                            ? <ExpiredBadge removedBy={episode.removedBy}/>
                            : episode.removedFromSource && <RemovedBadge asText/>}
                        {moved && <MovedBadge asText words={words}/>}
                        <span className={`episode-status${isLive ? ' is-live' : ''}`} title={sourceStatus?.help}>
                            {isLive && <span className="episode-status-dot" aria-hidden="true"/>}
                            {statusLabel}
                        </span>
                        <span className="episode-summary-separator" aria-hidden="true"/>
                        {/* On a phone the dates start a line of their own, so the summary takes two lines at most. */}
                        <span className="episode-summary-break" aria-hidden="true"/>
                        {startsAt ? (
                            <span className="episode-summary-item">
                                <FontAwesomeIcon icon={faIcon('fass', 'calendar')} aria-hidden="true"/>
                                <span>{`${publishStatus === 'delayed' ? 'Was due' : 'Starts'} ${formatDate(startsAt)}`}</span>
                            </span>
                        ) : (
                            <SummaryDate
                                label={releasedAtEnd ? 'Published' : 'Released'}
                                icon={releasedAtEnd ? faIcon('fass', 'calendar-check') : faIcon('fass', 'calendar-day')}
                                value={episode.publishedDate}
                                placement="below-start"
                            />
                        )}
                        {firstDownloadedAt && (
                            <>
                                <span className="episode-summary-separator" aria-hidden="true"/>
                                <SummaryDate
                                    label="Downloaded"
                                    icon={faIcon('fass', 'circle-down')}
                                    value={firstDownloadedAt}
                                    placement="below"
                                />
                            </>
                        )}
                    </div>
                </header>

                <SeasonPlaceNote episodeSlug={episode.slug} canManage={can('library', 'manage')} onMove={() => setReconciling(true)} words={words} fileWords={fileWords}/>
                <ReconcileDialog
                    open={reconciling}
                    path={`/episodes/${encodeURIComponent(episode.slug)}`}
                    what={episode.title}
                    onDismiss={() => setReconciling(false)}
                />

                {!!episode.description?.trim() && (
                    <section className="episode-description" aria-labelledby="episode-description-title">
                        <h2 id="episode-description-title">Description</h2>
                        <p><LinkedText text={episode.description}/></p>
                    </section>
                )}

                {isDownloadable && (
                    <div className="episode-downloads" aria-labelledby="episode-downloads-title">
                        <h2 id="episode-downloads-title">Downloads</h2>
                        {episode.drmProtected && <DrmNotice unplayableAllowed={collection.allowsUnplayableFormats}/>}
                        {!drmBlocked && episode.accessLocked && <AccessNotice item={episode}/>}
                        {!locked && downloadStateError && (
                            <div className="form-error-card" role="alert">
                                Could not load download status: {downloadStateError.message}
                            </div>
                        )}
                        {!locked && !downloadStateError && profiles === undefined && (
                            <div role="status" aria-busy="true" className="episode-downloads-loading">
                                Loading download options…
                            </div>
                        )}
                        {!locked && !downloadStateError && profiles !== undefined && !collectionProfiles?.length && (
                            <p>
                                {profiles.length ? `No Local Media Profile fits ${nameInText(collection.title)} yet.` : 'No Local Media Profiles configured yet.'}{' '}
                                <Link to={addLocalMediaProfilePath({collectionType: collection.type, siteKey: collection.site?.key, from: collection.title, collectionId: collection.id, returnTo: `${location.pathname}${location.search}`})}>Add one</Link>
                                {' '}to download this {words.episode.singular}.
                            </p>
                        )}
                        {!locked && !downloadStateError && !!collectionProfiles?.length && (
                            <div role="list" aria-label="Available downloads per Local Media Profile">
                                {collectionProfiles.map((profile) => {
                                    const download = downloadByProfileId.get(profile.id)
                                    const skippedBy = skipped?.find((item) => (
                                        item.episodeId === episode.id && item.localMediaProfileId === profile.id
                                    ))?.filter
                                    const waitsForCountdown = !!waitingForCountdown?.some((item) => (
                                        item.episodeId === episode.id && item.localMediaProfileId === profile.id
                                    ))
                                    return (
                                        <EpisodeDownloadRow
                                            key={profile.id}
                                            profile={profile}
                                            download={download}
                                            downloadStateKnown={hasDownloadState || download !== undefined}
                                            episodeSlug={episode.slug}
                                            confirmCountdownDownload={containsCountdown}
                                            confirmSafeDelayDownload={!containsCountdown && !episode.downloadDelayPassed}
                                            safeDelayReadyAt={episode.downloadDelayReadyAt}
                                            skippedBy={skippedBy}
                                            season={words.season}
                                            waitsForCountdown={containsCountdown && waitsForCountdown}
                                            goneReason={episode.removedBy
                                                ? `This ${words.episode.singular} expired on ${episode.removedBy.siteName}, so it can't be downloaded again`
                                                : undefined}
                                        />
                                    )
                                })}
                            </div>
                        )}
                        {(downloads ?? [])
                            .filter((download) => download.artifactStatus === 'available' && download.sponsorblockSegments?.length)
                            .map((download, _index, shown) => (
                                <SponsorBlockTimeline
                                    key={download.id}
                                    segments={download.sponsorblockSegments ?? []}
                                    duration={episode.duration}
                                    title={shown.length > 1
                                        ? `SponsorBlock: ${collectionProfiles?.find((profile) => profile.id === download.localMediaProfileId)?.name ?? 'download'}`
                                        : 'SponsorBlock'}
                                />
                            ))}
                    </div>
                )}
            </article>


        </section>
    )
}
