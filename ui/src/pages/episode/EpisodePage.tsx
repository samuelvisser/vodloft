import {sourceControls} from '../../lib/sourceControls'
import {useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import toast from 'react-hot-toast'
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
import {DrmBadge, DrmNotice} from '../../components/common/DrmProtected'
import {RemovedBadge} from '../../components/common/RemovedFromSource'
import SeasonPlaceNote, {MovedBadge, ReassignedBadge, useMoveToCollection, useMoveToSeason, useSeasonPlace} from '../../components/Episode/SeasonPlaceNote'
import {can} from '../../lib/access'
import {AccessNotice, ItemAccessBadge} from '../../components/common/AccessLocked'
import SponsorBlockTimeline from '../../components/Episode/SponsorBlockTimeline'
import {apiUrl} from '../../lib/api'
import DurationPill from '../../components/common/DurationPill'
import EpisodeTypePill from '../../components/Episode/EpisodeTypePill'
import {wordsFor} from '../../lib/collectionWords'


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
    // A Music collection is downloaded by Music Local Media Profiles, as tracks.
    const fileWords = wordsFor(collection, 'audio')
    const {data: skipped} = useSkippedByFilter(collection?.id)
    const {
        data: episode,
        isPending: isEpisodePending,
        isFetching: isEpisodeFetching,
    } = useEpisode(episodeId)
    const {data: profiles, error: profilesError} = useLocalMediaProfiles()
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
    // Its collection's playlists put it in another season, where it waits for the user to move it.
    const {data: seasonPlace} = useSeasonPlace(episodeId)
    const moved = !!seasonPlace?.belongsElsewhere
    const {move: moveToSeason, moving: movingToSeason} = useMoveToSeason(episodeId ?? '', collectionId, words)
    const reassignedTo = seasonPlace?.collectionTitle ?? null
    const {move: moveToCollection, moving: movingToCollection} = useMoveToCollection(episodeId ?? '', collectionId, words)
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
                    <h1>{words.episode.One}</h1>
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
                    <h1>{words.episode.One}</h1>
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
                    <h1>{words.episode.One}</h1>
                </div>
                <p>{words.episode.One} not found.</p>
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
    // Media protected by DRM or only given to members or subscribers cannot be downloaded.
    const locked = episode.drmProtected || episode.accessLocked
    const downloadStateError = (profiles === undefined ? profilesError : null)
        ?? (!hasDownloadState ? downloadsError : null)

    const coverUrl: string = episode.thumbnailLandscapePath
        || episode.backgroundImagePath
        || episode.thumbnailPortraitPath
        || `https://placehold.co/960x540/png?text=${encodeURIComponent(words.episode.One)}+%23${episode.index}`

    const downloadByProfileId = new Map<number, MediaDownloadViewRead>(
        (downloads ?? []).map((d) => [d.localMediaProfileId, d]),
    )
    const latestDownloadedAt = (downloads ?? []).reduce<Date | null>((latest, download) => {
        if (download.artifactStatus !== 'available' || !download.downloadedAt) return latest
        return latest === null || download.downloadedAt.getTime() > latest.getTime()
            ? download.downloadedAt
            : latest
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
            toast.success('Metadata refresh started')
        } catch (error) {
            const detail = error instanceof OperationStartError ? error.message : undefined
            toast.error(detail || 'Could not start metadata refresh')
        } finally {
            setMetadataRefreshStarting(false)
        }
    }

    return (
        <section className="view episode-view" aria-labelledby="episode-title">
            <article className="episode-details" aria-label={`${words.episode.One} details`}>
                {/* The buttons share the breadcrumb's row, so the title below gets the full width. */}
                <div className="episode-topbar">
                    <nav className="episode-breadcrumb" aria-label="Breadcrumb">
                        <Link className="quiet-link" to="/library">Library</Link>
                        <FontAwesomeIcon icon={faIcon('fass', 'chevron-right')} aria-hidden="true"/>
                        <Link className="quiet-link" to={`/collection/${collectionId}`}>{collection.title}</Link>
                    </nav>
                    <div className="episode-title-actions">
                        {episode.sharingUrl && (
                            <a
                                className="btn btn-secondary episode-open-link"
                                href={episode.sharingUrl}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={`Open on ${siteLabel}`}
                                title={`Open on ${siteLabel}`}
                            >
                                <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                                <span className="episode-open-link-text">{siteLabel}</span>
                            </a>
                        )}
                        <ActionMenu
                            items={[
                                ...(sourceControls(collection).metadataRefresh ? [{
                                    label: 'Refresh metadata',
                                    description: detailsChecked,
                                    icon: faIcon('fass', 'arrows-rotate'),
                                    disabled: metadataRefreshBusy,
                                    disabledReason: metadataRefreshStarting
                                        ? OPERATION_STARTING_MESSAGE
                                        : metadataRefreshOperation
                                            ? `A metadata refresh is running for this ${words.episode.one}.`
                                            : undefined,
                                    operation: metadataRefreshOperation,
                                    onSelect: () => void refreshMetadata(),
                                }] : []),
                                ...(reassignedTo && can('library', 'manage') ? [{
                                    label: `Move to ${reassignedTo}`,
                                    description: `Moves the ${words.episode.one} to the collection its creator places it in now, with its files`,
                                    icon: faIcon('fass', 'arrow-right-from-bracket'),
                                    disabled: movingToCollection,
                                    onSelect: () => void moveToCollection(),
                                }] : []),
                                ...(moved && can('library', 'manage') ? [{
                                    label: `Move to its new ${words.season.one}`,
                                    description: `Moves the ${words.episode.one} and renames its files to match`,
                                    icon: faIcon('fass', 'arrow-right-arrow-left'),
                                    disabled: movingToSeason,
                                    onSelect: () => void moveToSeason(),
                                }] : []),
                            ]}
                            note={sourceControls(collection).metadataRefresh ? undefined : detailsChecked}
                        />
                    </div>
                </div>

                <div className="episode-cover">
                    <img src={coverUrl} alt={`${words.episode.One} cover`}/>
                    {(episode.duration > 0 || isUpcoming) && (
                        <span className="thumb-corner thumb-corner-large">
                            <DurationPill seconds={episode.duration} upcoming={isUpcoming} large/>
                        </span>
                    )}
                    {isLive && (
                        <span className="episode-live-badge" aria-label={`${words.episode.One} is live`}>Live</span>
                    )}
                </div>

                <header className="episode-header">
                    <h1 id="episode-title" className="episode-title-text">{episode.title}</h1>
                    <div className="episode-summary" aria-label={`${words.episode.One} metadata`}>
                        <EpisodeTypePill sourceKey={episode.sourceKey} type={episode.episodeType} asText/>
                        {episode.drmProtected && <DrmBadge asText/>}
                        <ItemAccessBadge item={episode} asText/>
                        {episode.removedFromSource && <RemovedBadge asText/>}
                        {reassignedTo && <ReassignedBadge collectionTitle={reassignedTo} asText/>}
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
                        {latestDownloadedAt && (
                            <>
                                <span className="episode-summary-separator" aria-hidden="true"/>
                                <SummaryDate
                                    label="Downloaded"
                                    icon={faIcon('fass', 'circle-down')}
                                    value={latestDownloadedAt}
                                    placement="below"
                                />
                            </>
                        )}
                    </div>
                </header>

                <SeasonPlaceNote episodeSlug={episode.slug} collectionSlug={collectionId} canManage={can('library', 'manage')} words={words} fileWords={fileWords}/>

                {!!episode.description?.trim() && (
                    <section className="episode-description" aria-labelledby="episode-description-title">
                        <h2 id="episode-description-title">Description</h2>
                        <p>{episode.description}</p>
                    </section>
                )}

                {isDownloadable && (
                    <div className="episode-downloads" aria-labelledby="episode-downloads-title">
                        <h2 id="episode-downloads-title">Downloads</h2>
                        {episode.drmProtected && <DrmNotice/>}
                        {!episode.drmProtected && episode.accessLocked && <AccessNotice item={episode}/>}
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
                                No Local Media Profiles configured yet.{' '}
                                <Link to="/add-local-media-profile">Add one</Link> to download this {words.episode.one}.
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
                                            waitsForCountdown={containsCountdown && waitsForCountdown}
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
