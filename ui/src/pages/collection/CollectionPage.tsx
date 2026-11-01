import {sourceControls} from '../../lib/sourceControls'
import {addedByLabel, can} from '../../lib/access'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useDownloadProfilesView, useEpisodePages, useCollection, useLocalMediaProfiles, useCollectionDownloads, useCollectionSeasons, useSourceLookup, useStreamProfilesView } from '../../lib/queries'
import SourceBadge from '../../components/Source/SourceBadge'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'react-hot-toast'
import EpisodeCard, {groupDownloadsByEpisodeSlug} from '../../components/Episode/EpisodeCard'
import ActionConfirmDialogue, {type ActionConfirmDialogueLocalMediaProfile} from '../../components/ActionConfirmDialogue/ActionConfirmDialogue'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {useActiveOperation} from '../../components/OperationNotifier/OperationNotifier'
import CollectionIndexingProgress from '../../components/CollectionIndexingProgress/CollectionIndexingProgress'
import CollectionSyncLogModal from '../../components/CollectionSyncLogModal/CollectionSyncLogModal'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import {OperationControlError, type OperationControlAction, useControlOperation, useStartOperation} from '../../lib/operations'
import {PreferredFormatReg} from '../../types/local_media_profile'
import {getEpisodePreviewTotal, loadEpisodePreviewFromStorage, removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'
import SimpleSelect from '../../components/common/SimpleSelect'
import CollectionDownloadAllDialog from './CollectionDownloadAllDialog'
import {createSelectRegistry} from '../../utils/selectRegistry'
import './CollectionPage.css'
import {faIcon} from '../../icons/faIcon'
import {siteName} from '../../lib/siteName'


function preferredFormatLabel(value?: string | null) {
  if (!value) return 'Unknown'
  const label = PreferredFormatReg.getLabelLoose(value)
  return label === 'Audio Only' ? 'Audio' : label
}

const EPISODE_SKELETON_COUNT = 12
const OPERATION_WAITING_MESSAGE = 'Operation is waiting, it should resume soon.'

export default function CollectionPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const startOperation = useStartOperation()
  const controlOperation = useControlOperation()
  const PAGE_SIZE = 36

  const { data: collection, isLoading, error } = useCollection(id)
  const sources = useSourceLookup()
  const isSeasonal = collection?.episodeIdentifier === 'seasonal'

  const [confirm, setConfirm] = useState(false)
  const [syncStarting, setSyncStarting] = useState(false)
  const [metadataRefreshConfirm, setMetadataRefreshConfirm] = useState(false)
  const [fileRenameConfirm, setFileRenameConfirm] = useState(false)
  const [deleteDownloadsConfirm, setDeleteDownloadsConfirm] = useState(false)
  const [redownloadConfirm, setRedownloadConfirm] = useState(false)
  const [downloadAllConfirm, setDownloadAllConfirm] = useState(false)
  const [syncLogOpen, setSyncLogOpen] = useState(false)
  const [copiedStreamProfileId, setCopiedStreamProfileId] = useState<number | null>(null)
  const [selectedSeasonId, setSelectedSeasonId] = useState<number | null>(null)
  const [operationControlBusy, setOperationControlBusy] = useState<string | null>(null)

  const {
    data: seasonsData,
    isLoading: seasonsLoading,
    isPlaceholderData: seasonsPlaceholder,
  } = useCollectionSeasons(isSeasonal || collection?.type === 'series' ? id : undefined)
  const seasons = useMemo(
    () => [...(seasonsData ?? [])].sort((a, b) => b.index - a.index),
    [seasonsData],
  )
  const seasonReg = useMemo(() => {
    const spec: Record<string, {label: string}> = {}
    const values: string[] = []
    for (const season of seasons) {
      const value = String(season.id)
      spec[value] = {label: season.name?.trim() || `Season ${season.index}`}
      values.push(value)
    }
    return createSelectRegistry('CollectionSeason', spec, values)
  }, [seasons])

  useEffect(() => {
    if (!isSeasonal || seasons.length === 0) {
      setSelectedSeasonId(null)
      return
    }

    setSelectedSeasonId((current) => {
      if (current !== null && seasons.some((season) => season.id === current)) return current
      return seasons[0].id
    })
  }, [isSeasonal, seasons])

  const episodeSeasonId = isSeasonal ? selectedSeasonId : undefined
  const {
    data: episodePagesData,
    isLoading: episodesLoading,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useEpisodePages(id, {
    pageSize: PAGE_SIZE,
    seasonId: episodeSeasonId,
    enabled: Boolean(collection) && (!isSeasonal || selectedSeasonId !== null),
  })

  const cachedPreviewEpisodes = useMemo(() => loadEpisodePreviewFromStorage(id), [id])
  const cachedCollectionTotal = useMemo(
    () => id ? getEpisodePreviewTotal(id) : undefined,
    [id],
  )
  const cachedPreviewEpisodesForView = useMemo(() => {
    if (!cachedPreviewEpisodes) return []
    if (!isSeasonal) return cachedPreviewEpisodes
    if (selectedSeasonId === null) return []
    return cachedPreviewEpisodes
      .filter((episode) => episode.seasonId === selectedSeasonId)
      .sort((a, b) => a.index - b.index)
  }, [cachedPreviewEpisodes, isSeasonal, selectedSeasonId])
  const fetchedEpisodes = useMemo(
    () => episodePagesData?.pages.flatMap((page) => page.items) ?? [],
    [episodePagesData],
  )
  const episodes = episodePagesData !== undefined ? fetchedEpisodes : cachedPreviewEpisodesForView
  const firstEpisodePage = episodePagesData?.pages[0]
  const total = firstEpisodePage?.collectionTotal ?? cachedCollectionTotal ?? episodes.length
  const displayedTotal = firstEpisodePage?.total
  const episodesInitialLoading = (
    episodePagesData === undefined
    && cachedPreviewEpisodesForView.length === 0
    && episodesLoading
  )

  const {
    data: downloads,
    isLoading: downloadsLoading,
    error: downloadsError,
  } = useCollectionDownloads(id)
  const { data: downloadProfiles } = useDownloadProfilesView()
  const { data: localMediaProfiles } = useLocalMediaProfiles()
  const { data: streamProfiles } = useStreamProfilesView()
  const downloadsBySlug = useMemo(() => groupDownloadsByEpisodeSlug(downloads), [downloads])

  const operationResourceId = collection?.id ?? null
  const syncOperation = useActiveOperation('collection.sync', 'collection', operationResourceId)
  const metadataRefreshOperation = useActiveOperation('collection.refresh_metadata', 'collection', operationResourceId)
  const fileRenameOperation = useActiveOperation('collection.rename_files', 'collection', operationResourceId)
  const deleteDownloadsOperation = useActiveOperation('collection.delete_downloads', 'collection', operationResourceId)
  const redownloadOperation = useActiveOperation('collection.redownload_episodes', 'collection', operationResourceId)
  const downloadAllOperation = useActiveOperation('collection.download_all', 'collection', operationResourceId)
  const manualSyncing = syncOperation !== undefined
  const syncBusy = syncStarting || manualSyncing
  const metadataRefreshBusy = metadataRefreshOperation !== undefined
  const fileRenameBusy = fileRenameOperation !== undefined
  const deleteDownloadsBusy = deleteDownloadsOperation !== undefined
  const redownloadBusy = redownloadOperation !== undefined
  const downloadAllBusy = downloadAllOperation !== undefined

  const attachedDownloadProfiles = useMemo(
    () => (downloadProfiles ?? []).filter((profile) => profile.collectionSlug === id),
    [downloadProfiles, id],
  )
  const attachedStreamProfiles = useMemo(
    () => (streamProfiles ?? []).filter((profile) => profile.collectionSlug === id),
    [streamProfiles, id],
  )
  const downloadLocalMediaProfiles = useMemo(() => {
    const profiles = new Map<number, {id: number; name: string; preferredFormat: string | null}>()
    for (const download of downloads ?? []) {
      if (download.type !== 'episode' || download.collectionSlug !== id) continue
      if (download.artifactStatus === 'absent') continue
      if (profiles.has(download.localMediaProfileId)) continue
      profiles.set(download.localMediaProfileId, {
        id: download.localMediaProfileId,
        name: download.localMediaProfileName?.trim() || `Local Media Profile #${download.localMediaProfileId}`,
        preferredFormat: download.preferredFormat ?? null,
      })
    }
    return [...profiles.values()].sort((left, right) => left.name.localeCompare(right.name))
  }, [downloads, id])
  const actionLocalMediaProfiles = useMemo<ActionConfirmDialogueLocalMediaProfile[]>(
    () => downloadLocalMediaProfiles.map((profile) => ({
      id: profile.id,
      label: `${profile.name} · ${preferredFormatLabel(profile.preferredFormat)}`,
    })),
    [downloadLocalMediaProfiles],
  )
  const displayedEpisodes = episodes
  const seasonViewLoading = Boolean(
    isSeasonal && (
      seasonsLoading
      || seasonsPlaceholder
      || (seasons.length > 0 && selectedSeasonId === null)
    )
  )

  const sentinelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !hasNextPage || isFetchingNextPage) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          void fetchNextPage()
        }
      },
      {rootMargin: '600px'},
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [fetchNextPage, hasNextPage, isFetchingNextPage])

  if (!id) {
    return (
      <section className="view show-view">
        <div className="view-header"><h1>Show</h1></div>
        <p>Collection not found.</p>
      </section>
    )
  }

  if (isLoading && !collection) {
    return (
      <section className="view show-view">
        <div className="view-header"><h1>Show</h1></div>
        <p>Loading show...</p>
      </section>
    )
  }

  if (!collection) {
    return (
      <section className="view show-view">
        <div className="view-header"><h1>Show</h1></div>
        <p>{(error as any)?.message ?? 'Collection not found.'}</p>
      </section>
    )
  }

  const visibleItems = displayedEpisodes
  const hasMore = Boolean(hasNextPage)
  const episodesViewLoading = episodesInitialLoading || seasonViewLoading

  const syncDisabledReason = syncStarting
    ? 'This task is starting...'
    : syncOperation
      ? syncOperation.status === 'WAITING'
        ? syncOperation.message || OPERATION_WAITING_MESSAGE
        : `A sync is running for ${collection.title}.`
      : undefined
  const metadataRefreshDisabledReason = metadataRefreshOperation
    ? metadataRefreshOperation.status === 'WAITING'
      ? metadataRefreshOperation.message || OPERATION_WAITING_MESSAGE
      : `A metadata refresh is running for ${collection.title}.${metadataRefreshOperation.progressTotal > 0
        ? ` ${metadataRefreshOperation.progressCurrent}/${metadataRefreshOperation.progressTotal} episodes have finished.`
        : ''}`
    : undefined
  const downloadStateUnknown = downloadsLoading && downloads === undefined
  const downloadStateFailed = Boolean(downloadsError) && downloads === undefined
  const downloadStateDisabledReason = downloadStateUnknown
    ? 'VODLoft is still checking for downloaded episodes in this show.'
    : downloadStateFailed
      ? 'VODLoft could not determine whether this show has downloaded episodes.'
      : downloadLocalMediaProfiles.length === 0
        ? `No downloaded episodes exist for ${collection.title}.`
        : undefined
  const fileRenameDisabledReason = fileRenameOperation
    ? fileRenameOperation.status === 'WAITING'
      ? fileRenameOperation.message || OPERATION_WAITING_MESSAGE
      : `A File Rename operation is running for ${collection.title}.`
    : downloadStateDisabledReason
  const deleteDownloadsDisabledReason = deleteDownloadsOperation
    ? deleteDownloadsOperation.status === 'WAITING'
      ? deleteDownloadsOperation.message || OPERATION_WAITING_MESSAGE
      : `A bulk delete downloads operation is running for ${collection.title}.`
    : redownloadOperation
      ? `A bulk delete and re-download operation is running for ${collection.title}.`
      : downloadStateDisabledReason
  const redownloadDisabledReason = redownloadOperation
    ? redownloadOperation.status === 'WAITING'
      ? redownloadOperation.message || OPERATION_WAITING_MESSAGE
      : `A bulk delete and re-download operation is running for ${collection.title}.`
    : deleteDownloadsOperation
      ? `A bulk delete downloads operation is running for ${collection.title}.`
      : downloadStateDisabledReason

  const controlTaskOperation = async (
    operationId: string,
    action: OperationControlAction,
    label: string,
  ) => {
    if (operationControlBusy !== null) return
    const busyKey = `${operationId}:${action}`
    setOperationControlBusy(busyKey)
    try {
      await controlOperation(operationId, action)
      toast.success(action === 'restart' ? `${label} restarted` : `${label} canceled`)
    } catch (controlError) {
      const detail = controlError instanceof OperationControlError ? controlError.message : undefined
      toast.error(`Could not ${action} ${label}${detail ? `: ${detail}` : ''}`)
    } finally {
      setOperationControlBusy((current) => current === busyKey ? null : current)
    }
  }

  const operationControls = (
    operationId: string | undefined,
    label: string,
    restartable = true,
  ) => {
    if (!operationId) return undefined
    const controlsBusy = operationControlBusy !== null
    return [
      ...(restartable ? [{
        label: `Restart ${label}`,
        icon: faIcon('fass', 'rotate-right'),
        disabled: controlsBusy,
        onSelect: () => void controlTaskOperation(operationId, 'restart', label),
      }] : []),
      {
        label: `Cancel ${label}`,
        icon: faIcon('fass', 'xmark'),
        tone: 'danger' as const,
        disabled: controlsBusy,
        onSelect: () => void controlTaskOperation(operationId, 'cancel', label),
      },
    ]
  }

  const onDelete = () => setConfirm(true)
  const onEdit = () => navigate(`/edit-collection/${id}`)

  const syncNow = async () => {
    if (syncBusy) {
      toast(`A sync is in progress for ${collection.title}`)
      return
    }
    setSyncStarting(true)
    try {
      const base = (window as any).appConfig?.API_URL || '/api'
      await startOperation(`${base}/collections/${encodeURIComponent(id)}/sync`, {method: 'POST'})
      toast.success(`Sync started for ${collection.title}`)
    } catch {
      toast.error(`Could not start sync for ${collection.title}`)
    } finally {
      setSyncStarting(false)
    }
  }

  const copyFeedUrl = async (profileId: number, feedUrl?: string) => {
    if (!feedUrl) return
    try {
      await navigator.clipboard.writeText(feedUrl)
      setCopiedStreamProfileId(profileId)
      window.setTimeout(() => setCopiedStreamProfileId((current) => current === profileId ? null : current), 1800)
    } catch {
      toast.error('Could not copy the RSS URL')
    }
  }

  const closeConfirm = () => setConfirm(false)
  const onConfirmDelete = async () => {
    if (!id) return
    const url = `${(window as any).appConfig.API_URL}/collections/${id}`
    const r = await fetch(url, { method: 'DELETE', credentials: 'include' })
    if (!r.ok) {
      let friendly = `Failed to delete show (HTTP ${r.status})`
      try {
        const data = await r.json().catch(() => null as any)
        const details: any[] | undefined = data?.detail
        if (Array.isArray(details)) {
          const allErr = details.find((d) => Array.isArray(d?.loc) && d.loc[0] === 'body' && d.loc[1] === '__all__')
          if (allErr && typeof allErr.msg === 'string' && allErr.msg.trim()) friendly = allErr.msg
        }
      } catch (_) {
        // ignore JSON parse errors
      }
      console.error(friendly)
      toast.error(friendly)
      return
    }
    removeEpisodePreviewFromStorage(id)
    removeSeasonsFromStorage(id)
    setConfirm(false)

    await Promise.all([
      qc.cancelQueries({queryKey: ['collection', id]}),
      qc.cancelQueries({queryKey: ['seasons', id]}),
      qc.cancelQueries({queryKey: episodeQueryKeys.forCollection(id)}),
    ])
    qc.removeQueries({queryKey: ['collection', id]})
    qc.removeQueries({queryKey: ['seasons', id]})
    qc.removeQueries({queryKey: episodeQueryKeys.forCollection(id)})

    await Promise.all([
      qc.invalidateQueries({queryKey: ['collections']}),
      qc.invalidateQueries({queryKey: ['collectionsView']}),
    ])
    navigate('/library?type=collections')
  }

  return (
    <section className="view show-view" aria-labelledby="collection-title">
      <div className="view-header"><h1 id="collection-title">{collection.title}</h1></div>

      <article className="collection-details" aria-label="Show details">
        <header className="collection-page-header">
          <div className="collection-page-heading">
            <SourceBadge sourceKey={collection.sourceKey}/>
            <div className="collection-author">{collection.authorName}</div>
            <div className="collection-meta">{[`${total} episodes`, collection.years, addedByLabel(collection.addedBy)].filter(Boolean).join(' • ')}</div>
          </div>

          <div className="collection-page-actions">
            {collection.sharingUrl && (
              <a className="btn" href={collection.sharingUrl} target="_blank" rel="noreferrer">
                <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                <span>Open on {sources.get(collection.sourceKey)?.domains.includes('*') ? siteName(collection.sharingUrl) ?? sources.name(collection.sourceKey) : sources.name(collection.sourceKey)}</span>
              </a>
            )}
            {can('library', 'manage') && (
              <>
            <button type="button" className="btn" title="Edit show" onClick={onEdit}>
              <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/>
              <span>Edit</span>
            </button>
            <button type="button" className="btn btn-danger" onClick={onDelete}>
              <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
              <span>Delete</span>
            </button>
            <ActionMenu
              items={[
                {
                  label: 'Sync now',
                  icon: faIcon('fass', 'arrows-rotate'),
                  disabled: syncBusy,
                  disabledReason: syncDisabledReason,
                  operation: syncOperation,
                  controls: operationControls(syncOperation?.id, 'sync'),
                  onSelect: () => void syncNow(),
                },
                {
                  label: 'Sync log',
                  icon: faIcon('fass', 'clock-rotate-left'),
                  onSelect: () => setSyncLogOpen(true),
                },
                {
                  label: 'Bulk download',
                  icon: faIcon('fass', 'download'),
                  disabled: downloadAllBusy,
                  disabledReason: downloadAllBusy ? `A bulk download is running for ${collection.title}.` : undefined,
                  operation: downloadAllOperation,
                  controls: operationControls(downloadAllOperation?.id, 'bulk download'),
                  onSelect: () => setDownloadAllConfirm(true),
                },
                ...(sourceControls(collection).metadataRefresh ? [{
                  label: 'Refresh all metadata',
                  icon: faIcon('fass', 'clipboard-list') as [string, string],
                  disabled: metadataRefreshBusy,
                  disabledReason: metadataRefreshDisabledReason,
                  operation: metadataRefreshOperation,
                  controls: operationControls(metadataRefreshOperation?.id, 'metadata refresh'),
                  onSelect: () => setMetadataRefreshConfirm(true),
                }] : []),
                {
                  label: 'Rename all episode files',
                  icon: faIcon('fass', 'file-pen'),
                  disabled: fileRenameDisabledReason !== undefined,
                  disabledReason: fileRenameDisabledReason,
                  operation: fileRenameOperation,
                  controls: operationControls(fileRenameOperation?.id, 'File Rename'),
                  onSelect: () => setFileRenameConfirm(true),
                },
                {
                  label: 'Bulk delete downloads',
                  icon: faIcon('fass', 'trash'),
                  tone: 'danger',
                  disabled: deleteDownloadsDisabledReason !== undefined,
                  disabledReason: deleteDownloadsDisabledReason,
                  operation: deleteDownloadsOperation,
                  controls: operationControls(deleteDownloadsOperation?.id, 'bulk delete downloads'),
                  onSelect: () => setDeleteDownloadsConfirm(true),
                },
                {
                  label: 'Bulk delete and re-download',
                  icon: faIcon('fass', 'trash'),
                  tone: 'danger',
                  disabled: redownloadDisabledReason !== undefined,
                  disabledReason: redownloadDisabledReason,
                  operation: redownloadOperation,
                  controls: operationControls(redownloadOperation?.id, 'bulk delete and re-download', false),
                  onSelect: () => setRedownloadConfirm(true),
                },
                {
                  label: 'Create download profile',
                  icon: faIcon('fass', 'download'),
                  separatorBefore: true,
                  onSelect: () => navigate(`/add-download-profile?collection=${encodeURIComponent(id)}`),
                },
                {
                  label: 'Create stream profile',
                  icon: faIcon('fass', 'rss'),
                  onSelect: () => navigate(`/add-stream-profile?collection=${encodeURIComponent(id)}`),
                },
              ]}
            />
              </>
            )}
          </div>

          <CollectionIndexingProgress
            collectionId={collection.id}
            collectionSlug={collection.slug}
            pollForStart={total === 0}
            className="collection-page-indexing"
          />

          {(attachedDownloadProfiles.length > 0 || attachedStreamProfiles.length > 0) && (
            <div className="collection-profile-summary" aria-label="Profiles attached to this show">
              {attachedDownloadProfiles.length > 0 && (
                <div className="collection-profile-group">
                  <div className="collection-profile-group-label">
                    <FontAwesomeIcon icon={faIcon('fass', 'download')} aria-hidden="true"/>
                    <span>Download {attachedDownloadProfiles.length === 1 ? 'profile' : 'profiles'}</span>
                  </div>
                  <div className="collection-profile-links">
                    {attachedDownloadProfiles.map((profile) => (
                      <button
                        key={profile.id}
                        type="button"
                        className="collection-profile-chip"
                        onClick={() => navigate(`/edit-download-profile/${profile.id}`, {state: profile})}
                        title={`Open ${preferredFormatLabel(profile.localMediaProfilePreferredFormat)} download profile`}
                      >
                        <span>{preferredFormatLabel(profile.localMediaProfilePreferredFormat)}</span>
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {attachedStreamProfiles.length > 0 && (
                <div className="collection-profile-group">
                  <div className="collection-profile-group-label">
                    <FontAwesomeIcon icon={faIcon('fass', 'rss')} aria-hidden="true"/>
                    <span>Stream {attachedStreamProfiles.length === 1 ? 'profile' : 'profiles'}</span>
                  </div>
                  <div className="collection-profile-links">
                    {attachedStreamProfiles.map((profile) => {
                      const feedUrl = profile.type === 'rss' ? profile.streamProfileImpl?.feedUrl : undefined
                      const copied = copiedStreamProfileId === profile.id
                      const label = `${profile.type.toUpperCase()} ${preferredFormatLabel(profile.preferredFormat)}`
                      return (
                        <div key={`${profile.type}-${profile.id}`} className="collection-profile-chip-group">
                          <button
                            type="button"
                            className="show-profile-chip show-profile-chip-main"
                            onClick={() => navigate(`/edit-stream-profile/${profile.type}/${profile.id}`, {state: profile})}
                            title={`Open ${label}`}
                          >
                            <span>{label}</span>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                          </button>
                          {profile.type === 'rss' && feedUrl && (
                            <button
                              type="button"
                              className="collection-profile-copy"
                              onClick={() => copyFeedUrl(profile.id, feedUrl)}
                              aria-label={copied ? 'RSS URL copied' : 'Copy RSS URL'}
                              title={copied ? 'Copied!' : 'Copy RSS URL'}
                            >
                              <FontAwesomeIcon icon={faIcon('fass', copied ? 'check' : 'copy') as any} aria-hidden="true"/>
                            </button>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </header>

        {isSeasonal && seasons.length > 0 && (
          <div className="collection-season-filter" aria-label="Season selection">
            <label htmlFor="collection-season">Season</label>
            <SimpleSelect
              inputId="collection-season"
              className="collection-season-select"
              registry={seasonReg}
              value={selectedSeasonId === null ? null : String(selectedSeasonId)}
              onChange={(value) => setSelectedSeasonId(Number(value))}
              placeholder="Select a season"
            />
            {displayedTotal !== undefined && (
              <span className="collection-season-count">
                {displayedTotal} {displayedTotal === 1 ? 'episode' : 'episodes'}
              </span>
            )}
          </div>
        )}

        {isSeasonal && !seasonViewLoading && seasons.length === 0 ? (
          <div className="collection-season-empty" role="status">No seasons are available for this show.</div>
        ) : episodesViewLoading ? (
          <div className="episodes-grid" role="status" aria-label="Loading episodes" aria-busy="true">
            {Array.from({length: EPISODE_SKELETON_COUNT}, (_, index) => (
              <div className="episode-card episode-card-skeleton" key={index} aria-hidden="true">
                <div className="episode-skeleton-cover"/>
                <div className="episode-skeleton-title"/>
                <div className="episode-skeleton-title episode-skeleton-title-short"/>
              </div>
            ))}
          </div>
        ) : (
          <div className="episodes-grid" role="list" aria-label={`${collection.title} episodes`}>
            {visibleItems.map((ep: any) => (
              <EpisodeCard key={ep.id} ep={ep} collectionSlug={id} downloads={downloadsBySlug.get(ep.slug)}/>
            ))}
          </div>
        )}

        {hasMore && !episodesViewLoading && (
          <div ref={sentinelRef} className="episodes-load-more" aria-hidden>Loading more episodes…</div>
        )}
      </article>

      <CollectionSyncLogModal
        collectionSlug={id}
        collectionTitle={collection.title}
        open={syncLogOpen}
        syncing={syncBusy}
        onClose={() => setSyncLogOpen(false)}
        onSyncNow={syncNow}
      />

      {downloadAllConfirm && (
        <CollectionDownloadAllDialog
          collectionSlug={id}
          collectionTitle={collection.title}
          collectionType={collection.type === 'series' ? 'series' : 'podcast'}
          seasons={seasons}
          localMediaProfiles={localMediaProfiles ?? []}
          onDismiss={() => setDownloadAllConfirm(false)}
        />
      )}

      <ActionConfirmDialogue
        open={metadataRefreshConfirm}
        operationDefinition={frontendOperationDefinitions['collection.refresh_metadata']}
        requestPath={`/collections/${encodeURIComponent(id)}/refresh-metadata`}
        resourceLabel={collection.title}
        title="Refresh all metadata"
        onDismiss={() => setMetadataRefreshConfirm(false)}
        icon={faIcon('fass', 'arrows-rotate')}
        confirmLabel="Refresh metadata"
        disabled={metadataRefreshBusy}
      >
        <p>Refresh metadata for every episode in "{collection.title}"? This can take a while and is usually not needed.</p>
      </ActionConfirmDialogue>

      <ActionConfirmDialogue
        open={fileRenameConfirm}
        operationDefinition={frontendOperationDefinitions['collection.rename_files']}
        requestPath={`/collections/${encodeURIComponent(id)}/rename-files`}
        resourceLabel={collection.title}
        title="Rename existing episode files"
        onDismiss={() => setFileRenameConfirm(false)}
        icon={faIcon('fass', 'file-pen')}
        confirmLabel="Rename files"
        disabled={fileRenameBusy}
        scope_by_local_media_profile
        localMediaProfiles={actionLocalMediaProfiles}
      >
        <p>
          Rename existing episode files in "{collection.title}" so their paths match the current Local Media Profile output templates.
        </p>
      </ActionConfirmDialogue>

      <ActionConfirmDialogue
        open={deleteDownloadsConfirm}
        operationDefinition={frontendOperationDefinitions['collection.delete_downloads']}
        requestPath={`/collections/${encodeURIComponent(id)}/delete-downloads`}
        resourceLabel={collection.title}
        title="Bulk delete downloads"
        onDismiss={() => setDeleteDownloadsConfirm(false)}
        icon={faIcon('fass', 'trash')}
        iconTone="danger"
        confirmLabel="Bulk delete downloads"
        disabled={deleteDownloadsBusy || redownloadBusy}
        scope_by_local_media_profile
        showDeleteOlderThan
        localMediaProfiles={actionLocalMediaProfiles}
      >
        <p>
          Delete downloaded episode files in "{collection.title}".
        </p>
        <p>
          When you delete everything, VODLoft first disables any Download Profiles attached to the selected Local Media Profile or Profiles. Re-enable a disabled Download Profile whenever you want VODLoft to download its eligible episodes again.
          Deleting only older episodes leaves Download Profiles on, so they may download those episodes again.
        </p>
      </ActionConfirmDialogue>

      <ActionConfirmDialogue
        open={redownloadConfirm}
        operationDefinition={frontendOperationDefinitions['collection.redownload_episodes']}
        requestPath={`/collections/${encodeURIComponent(id)}/redownload-episodes`}
        resourceLabel={collection.title}
        title="Bulk delete and re-download"
        onDismiss={() => setRedownloadConfirm(false)}
        icon={faIcon('fass', 'arrows-rotate')}
        iconTone="danger"
        confirmLabel="Bulk delete and re-download"
        disabled={deleteDownloadsBusy || redownloadBusy}
        scope_by_local_media_profile
        showDeleteOlderThan
        localMediaProfiles={actionLocalMediaProfiles}
      >
        <p>
          Delete existing episode files in "{collection.title}" and re-download them.
          This can take a long time, use significant bandwidth, and is usually not needed.
        </p>
      </ActionConfirmDialogue>

      <ConfirmDialog
        open={confirm}
        title="Delete show"
        onDismiss={closeConfirm}
        icon={faIcon('fass', 'trash')}
        iconTone="danger"
        confirmButton={{
          label: 'Delete',
          onClick: onConfirmDelete,
          className: 'btn btn-danger',
        }}
      >
        <p>Are you sure you want to delete "{collection.title}"? This action cannot be undone.</p>
      </ConfirmDialog>
    </section>
  )
}
