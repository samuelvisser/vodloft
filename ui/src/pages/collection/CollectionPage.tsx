import {sourceControls} from '../../lib/sourceControls'
import {addedByLabel, can} from '../../lib/access'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { useCollectionDownloadProfilesView, useCollectionStreamProfilesView, useEpisodePages, useCollection, useLocalMediaProfiles, useCollectionEpisodeDownloads, useCollectionDownloadedLocalMediaProfiles, useCollectionSeasons, useEpisodeTagsInCollection, useSourceLookup, useCollectionLocked } from '../../lib/queries'
import SourceBadge from '../../components/Source/SourceBadge'
import { toast } from 'react-hot-toast'
import EpisodeCard, {groupDownloadsByEpisodeSlug} from '../../components/Episode/EpisodeCard'
import ActionConfirmDialogue, {type ActionConfirmDialogueLocalMediaProfile} from '../../components/ActionConfirmDialogue/ActionConfirmDialogue'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import {useActiveOperation} from '../../components/OperationNotifier/OperationNotifier'
import CollectionIndexingProgress from '../../components/CollectionIndexingProgress/CollectionIndexingProgress'
import CollectionSyncLogModal from '../../components/CollectionSyncLogModal/CollectionSyncLogModal'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import {OperationControlError, type OperationControlAction, useControlOperation, useStartOperation, useStartingOperations} from '../../lib/operations'
import {PreferredFormatReg} from '../../types/local_media_profile'
import {getEpisodePreviewTotal, loadEpisodePreviewFromStorage} from '../../lib/cache'
import SimpleSelect from '../../components/common/SimpleSelect'
import CollectionDownloadAllDialog from './CollectionDownloadAllDialog'
import {createSelectRegistry} from '../../utils/selectRegistry'
import './CollectionPage.css'
import {faIcon} from '../../icons/faIcon'
import {siteName} from '../../lib/siteName'
import ExistingFilesDialog from '../../components/ExistingFiles/ExistingFilesDialog'
import ExistingFilesBanner from '../../components/ExistingFiles/ExistingFilesBanner'
import {useExistingFilesScans} from '../../components/ExistingFiles/api'
import EpisodeTypeFilter from '../../components/Episode/EpisodeTypeFilter'
import LockedEpisodesFilter from '../../components/Episode/LockedEpisodesFilter'
import {apiFetch, apiUrl} from '../../lib/api'

const EPISODE_TYPE_FILTER_STORAGE_PREFIX = 'collectionEpisodeTypeFilter:'

/** The remembered episode type filter of one collection; empty (every type) when nothing usable is stored. */
function loadEpisodeTypeFilter(collectionSlug: string | undefined): Set<string> {
  if (!collectionSlug) return new Set()
  try {
    const raw = localStorage.getItem(EPISODE_TYPE_FILTER_STORAGE_PREFIX + collectionSlug)
    if (raw === null) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((value): value is string => typeof value === 'string'))
  } catch {
    return new Set()
  }
}

/** The episode type filter of a collection, remembered per collection across page loads. */
function useEpisodeTypeFilter(collectionSlug: string | undefined) {
  const [state, setState] = useState(() => ({slug: collectionSlug, selected: loadEpisodeTypeFilter(collectionSlug)}))
  let current = state
  if (state.slug !== collectionSlug) {
    current = {slug: collectionSlug, selected: loadEpisodeTypeFilter(collectionSlug)}
    setState(current)
  }
  const update = useCallback((selected: Set<string>) => {
    setState({slug: collectionSlug, selected})
    if (!collectionSlug) return
    try {
      const key = EPISODE_TYPE_FILTER_STORAGE_PREFIX + collectionSlug
      if (selected.size === 0) localStorage.removeItem(key)
      else localStorage.setItem(key, JSON.stringify(Array.from(selected)))
    } catch {
      // Without storage the filter still works, it just isn't remembered.
    }
  }, [collectionSlug])
  return [current.selected, update] as const
}

const SHOW_LOCKED_STORAGE_PREFIX = 'collectionShowLocked:'

/** Whether a collection shows the episodes VODLoft has no access to, as the user last chose it there;
 * null while they never did, so the collection's Site decides. */
function loadShowLocked(collectionSlug: string | undefined): boolean | null {
  if (!collectionSlug) return null
  try {
    const raw = localStorage.getItem(SHOW_LOCKED_STORAGE_PREFIX + collectionSlug)
    return raw === 'true' ? true : raw === 'false' ? false : null
  } catch {
    return null
  }
}

/** The locked episodes filter of a collection, remembered per collection across page loads. */
function useShowLocked(collectionSlug: string | undefined) {
  const [state, setState] = useState(() => ({slug: collectionSlug, shown: loadShowLocked(collectionSlug)}))
  let current = state
  if (state.slug !== collectionSlug) {
    current = {slug: collectionSlug, shown: loadShowLocked(collectionSlug)}
    setState(current)
  }
  const update = useCallback((shown: boolean) => {
    setState({slug: collectionSlug, shown})
    if (!collectionSlug) return
    try {
      localStorage.setItem(SHOW_LOCKED_STORAGE_PREFIX + collectionSlug, String(shown))
    } catch {
      // Without storage the filter still works, it just isn't remembered.
    }
  }, [collectionSlug])
  return [current.shown, update] as const
}

function preferredFormatLabel(value?: string | null) {
  if (!value) return 'Unknown'
  const label = PreferredFormatReg.getLabelLoose(value)
  return label === 'Audio Only' ? 'Audio' : label
}

const EPISODE_SKELETON_COUNT = 12
const OPERATION_WAITING_MESSAGE = 'Operation is waiting, it should resume soon.'

export default function CollectionPage() {
  const { id } = useParams()
  const startOperation = useStartOperation()
  const controlOperation = useControlOperation()
  const {isStarting, onStartingChange} = useStartingOperations()
  const PAGE_SIZE = 36

  const { data: collection, isLoading, error } = useCollection(id)
  // Count each visit once, so the Library can list the most used Collections first.
  const countedVisit = useRef<string | null>(null)
  useEffect(() => {
    if (!id || countedVisit.current === id) return
    countedVisit.current = id
    apiFetch(`/collections/${encodeURIComponent(id)}/opened`, {method: 'POST'}).catch(() => {
      // Only the Library's order misses this visit.
    })
  }, [id])
  const sources = useSourceLookup()
  const isSeasonal = collection?.episodeIdentifier === 'seasonal'

  const [syncStarting, setSyncStarting] = useState(false)
  const [metadataRefreshConfirm, setMetadataRefreshConfirm] = useState(false)
  const [fileRenameConfirm, setFileRenameConfirm] = useState(false)
  const [fileRenameProfileId, setFileRenameProfileId] = useState<number | undefined>(undefined)
  const [searchParams, setSearchParams] = useSearchParams()
  const existingFilesParam = Number(searchParams.get('existingFiles'))
  const [existingFilesProfileId, setExistingFilesProfileId] = useState<number | null>(
    Number.isInteger(existingFilesParam) && existingFilesParam > 0 ? existingFilesParam : null,
  )
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

  const {data: episodeTags, isError: episodeTagsFailed, refetch: refetchEpisodeTags} = useEpisodeTagsInCollection(id)
  const {data: lockedCount, refetch: refetchLocked} = useCollectionLocked(id, can('managed_downloads', 'manage'))
  const [lockedCheckBusy, setLockedCheckBusy] = useState(false)
  // Hidden on purpose: most users never gain the access, so only the Actions menu offers this.
  const checkLockedAgain = async () => {
    if (!id || lockedCheckBusy) return
    setLockedCheckBusy(true)
    try {
      const response = await fetch(`${apiUrl()}/collections/${encodeURIComponent(id)}/locked/check`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!response.ok) throw new Error()
      toast.success('VODLoft checks the locked videos again and downloads those it can')
      void refetchLocked()
    } catch {
      toast.error('Could not check the locked videos again')
    } finally {
      setLockedCheckBusy(false)
    }
  }
  const [storedEpisodeTypes, setEpisodeTypeFilter] = useEpisodeTypeFilter(id)
  // A remembered type can disappear from the collection. Once its types are known, only apply
  // the ones still present, and every type while the chips are hidden, so nothing stays
  // filtered out without a visible way to clear it.
  const episodeTypeFilter = useMemo(() => {
    if (episodeTags === undefined) return storedEpisodeTypes
    if (episodeTags.length < 2) return new Set<string>()
    const kept = episodeTags.map((tag) => tag.key).filter((key) => storedEpisodeTypes.has(key))
    return kept.length === episodeTags.length ? new Set<string>() : new Set(kept)
  }, [episodeTags, storedEpisodeTypes])
  const episodeTypes = useMemo(() => [...episodeTypeFilter].sort(), [episodeTypeFilter])
  const typeFiltered = episodeTypes.length > 0
  // With one type selected, the count names it, such as "726 livestreams".
  const singleTypeTag = episodeTypes.length === 1 ? episodeTags?.find((tag) => tag.key === episodeTypes[0]) : undefined
  const countNouns = singleTypeTag ?? {singular: 'episode', plural: 'episodes'}
  // Locked episodes start shown, unless the collection's Site mixes them among open ones, such as a
  // YouTube channel's members-only videos. Episodes the account can watch are never hidden.
  const [storedShowLocked, setShowLocked] = useShowLocked(id)
  const showLocked = storedShowLocked ?? collection?.site?.showsLocked ?? true
  const {
    data: episodePagesData,
    isLoading: episodesLoading,
    isFetching: episodesFetching,
    isPlaceholderData: episodesPlaceholder,
    isError: episodesError,
    isFetchNextPageError,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
    refetch: refetchEpisodes,
  } = useEpisodePages(id, {
    pageSize: PAGE_SIZE,
    seasonId: episodeSeasonId,
    episodeTypes,
    hideLocked: !showLocked,
    enabled: Boolean(collection) && (!isSeasonal || selectedSeasonId !== null),
  })

  const cachedPreviewEpisodes = useMemo(() => loadEpisodePreviewFromStorage(id), [id])
  const cachedCollectionTotal = useMemo(
    () => id ? getEpisodePreviewTotal(id) : undefined,
    [id],
  )
  // A seasonal collection orders each season; the preview of every episode is always newest first.
  const newestFirst = collection?.episodeOrder !== 'oldest_first'
  const cachedPreviewEpisodesForView = useMemo(() => {
    if (!cachedPreviewEpisodes) return []
    const ofTypes = cachedPreviewEpisodes.filter((episode) => (
      (!typeFiltered || (episode.episodeType !== null && episodeTypeFilter.has(episode.episodeType)))
      && (showLocked || !episode.access || episode.accessGranted)
    ))
    if (!isSeasonal) return ofTypes
    if (selectedSeasonId === null) return []
    return ofTypes
      .filter((episode) => episode.seasonId === selectedSeasonId)
      .sort((a, b) => newestFirst ? b.index - a.index : a.index - b.index)
  }, [cachedPreviewEpisodes, isSeasonal, selectedSeasonId, typeFiltered, episodeTypeFilter, showLocked, newestFirst])
  const fetchedEpisodes = useMemo(
    () => episodePagesData?.pages.flatMap((page) => page.items) ?? [],
    [episodePagesData],
  )
  const episodes = episodePagesData !== undefined ? fetchedEpisodes : cachedPreviewEpisodesForView
  const firstEpisodePage = episodePagesData?.pages[0]
  const total = firstEpisodePage?.collectionTotal ?? cachedCollectionTotal ?? episodes.length
  const displayedTotal = firstEpisodePage?.total
  const lockedTotal = firstEpisodePage?.lockedTotal ?? 0
  const lockedHidden = !showLocked && lockedTotal > 0
  const episodesInitialLoading = (
    episodePagesData === undefined
    && cachedPreviewEpisodesForView.length === 0
    && episodesLoading
  )

  const episodeIdPages = useMemo(
    () => episodePagesData?.pages.map((page) => page.items.map((episode) => episode.id)) ?? [],
    [episodePagesData],
  )
  const {data: downloads} = useCollectionEpisodeDownloads(id, episodeIdPages)
  const {
    data: downloadedLocalMediaProfiles,
    isLoading: downloadsLoading,
    error: downloadsError,
  } = useCollectionDownloadedLocalMediaProfiles(id)
  const { data: downloadProfiles } = useCollectionDownloadProfilesView(id)
  const { data: localMediaProfiles } = useLocalMediaProfiles()
  const { data: streamProfiles } = useCollectionStreamProfilesView(id)
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

  const attachedDownloadProfiles = useMemo(() => downloadProfiles ?? [], [downloadProfiles])
  const attachedStreamProfiles = useMemo(() => streamProfiles ?? [], [streamProfiles])
  const downloadLocalMediaProfiles = useMemo(
    () => (downloadedLocalMediaProfiles ?? [])
      .map((profile) => ({
        id: profile.id,
        name: profile.name.trim() || `Local Media Profile #${profile.id}`,
        preferredFormat: profile.preferredFormat ?? null,
      }))
      .sort((left, right) => left.name.localeCompare(right.name)),
    [downloadedLocalMediaProfiles],
  )
  const actionLocalMediaProfiles = useMemo<ActionConfirmDialogueLocalMediaProfile[]>(
    () => downloadLocalMediaProfiles.map((profile) => ({
      id: profile.id,
      label: `${profile.name} · ${preferredFormatLabel(profile.preferredFormat)}`,
    })),
    [downloadLocalMediaProfiles],
  )
  const existingFilesProfiles = useMemo(() => {
    const attached = new Set(attachedDownloadProfiles.map((profile) => profile.localMediaProfileId))
    return [...(localMediaProfiles ?? [])]
      .sort((left, right) => Number(attached.has(right.id)) - Number(attached.has(left.id)) || left.name.localeCompare(right.name))
      .map((profile) => ({id: profile.id, name: profile.name}))
  }, [localMediaProfiles, attachedDownloadProfiles])
  // "?existingFiles=open" comes from the add wizard: open the scan it started once it shows up.
  const openFirstScan = searchParams.get('existingFiles') === 'open'
  const {data: existingFilesScans} = useExistingFilesScans(id, openFirstScan && can('library', 'manage'))
  useEffect(() => {
    if (!openFirstScan || existingFilesProfileId !== null) return
    const scan = existingFilesScans?.find((candidate) => candidate.status !== 'finished')
    if (scan) setExistingFilesProfileId(scan.localMediaProfileId)
  }, [openFirstScan, existingFilesScans, existingFilesProfileId])
  const closeExistingFiles = () => {
    setExistingFilesProfileId(null)
    if (searchParams.has('existingFiles')) {
      const next = new URLSearchParams(searchParams)
      next.delete('existingFiles')
      setSearchParams(next, {replace: true})
    }
  }
  const displayedEpisodes = episodes
  const seasonViewLoading = Boolean(
    isSeasonal && (
      seasonsLoading
      || seasonsPlaceholder
      || (seasons.length > 0 && selectedSeasonId === null)
    )
  )

  // Until the first page arrives, the grid shows the episodes this browser remembered.
  const episodesFromCache = episodePagesData === undefined || episodesPlaceholder
  const episodesFailed = episodesError && !episodesFetching
  const sentinelShown = Boolean(hasNextPage) && !seasonViewLoading && !episodesInitialLoading && !episodesFailed
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !sentinelShown || isFetchingNextPage) return

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
  }, [fetchNextPage, sentinelShown, isFetchingNextPage])
  const retryEpisodes = () => {
    if (episodeTagsFailed) void refetchEpisodeTags()
    void (isFetchNextPageError ? fetchNextPage() : refetchEpisodes())
  }

  if (!id) {
    return (
      <section className="view collection-view">
        <div className="view-header"><h1>Show</h1></div>
        <p>Collection not found.</p>
      </section>
    )
  }

  if (isLoading && !collection) {
    return (
      <section className="view collection-view">
        <div className="view-header"><h1>Show</h1></div>
        <p>Loading show...</p>
      </section>
    )
  }

  if (!collection) {
    return (
      <section className="view collection-view">
        <div className="view-header"><h1>Show</h1></div>
        <p>{(error as any)?.message ?? 'Collection not found.'}</p>
      </section>
    )
  }

  const visibleItems = displayedEpisodes
  const episodesViewLoading = episodesInitialLoading || seasonViewLoading

  const metadataRefreshDisabledReason = metadataRefreshOperation
    ? metadataRefreshOperation.status === 'WAITING'
      ? metadataRefreshOperation.message || OPERATION_WAITING_MESSAGE
      : `A metadata refresh is running for ${collection.title}.${metadataRefreshOperation.progressTotal > 0
        ? ` ${metadataRefreshOperation.progressCurrent}/${metadataRefreshOperation.progressTotal} episodes have finished.`
        : ''}`
    : undefined
  const downloadStateUnknown = downloadsLoading && downloadedLocalMediaProfiles === undefined
  const downloadStateFailed = Boolean(downloadsError) && downloadedLocalMediaProfiles === undefined
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

  const syncNow = async () => {
    if (syncBusy) {
      toast(`A sync is in progress for ${collection.title}`)
      return
    }
    setSyncStarting(true)
    try {
      const base = apiUrl()
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

  const openOnName = collection.site?.name ?? (sources.get(collection.sourceKey)?.domains.includes('*') ? siteName(collection.sharingUrl) ?? sources.name(collection.sourceKey) : sources.name(collection.sourceKey))

  return (
    <section className="view collection-view" aria-labelledby="collection-title">
      <div className="view-header collection-title-row">
        <h1 id="collection-title">{collection.title}</h1>
        <SourceBadge sourceKey={collection.sourceKey}/>
      </div>

      <article className="collection-details" aria-label="Show details">
        <header className="collection-page-header">
          <div className="collection-page-heading">
            <div className="collection-author">{collection.authorName}</div>
            <div className="collection-meta">{[`${total} episodes`, collection.years, addedByLabel(collection.addedBy)].filter(Boolean).join(' • ')}</div>
          </div>

          <div className="collection-page-actions">
            {collection.sharingUrl && (
              <a className="btn collection-open-link" href={collection.sharingUrl} target="_blank" rel="noreferrer" title={`Open on ${openOnName}`}>
                <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                <span className="collection-open-label"><span className="collection-open-prefix">Open on </span>{openOnName}</span>
              </a>
            )}
            {can('library', 'manage') && (
              <>
            <Link className="btn" title="Edit show" to={`/edit-collection/${id}`}>
              <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/>
              <span>Edit</span>
            </Link>
            <ActionMenu
              items={[
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
                  starting: isStarting('collection.download_all'),
                  controls: operationControls(downloadAllOperation?.id, 'bulk download'),
                  onSelect: () => setDownloadAllConfirm(true),
                },
                ...(lockedCount ? [{
                  label: `Check locked videos again (${lockedCount})`,
                  icon: faIcon('fass', 'unlock') as [string, string],
                  disabled: lockedCheckBusy,
                  onSelect: () => void checkLockedAgain(),
                }] : []),
                ...(sourceControls(collection).metadataRefresh ? [{
                  label: 'Refresh all metadata',
                  icon: faIcon('fass', 'clipboard-list') as [string, string],
                  disabled: metadataRefreshBusy,
                  disabledReason: metadataRefreshDisabledReason,
                  operation: metadataRefreshOperation,
                  starting: isStarting('collection.refresh_metadata'),
                  controls: operationControls(metadataRefreshOperation?.id, 'metadata refresh'),
                  onSelect: () => setMetadataRefreshConfirm(true),
                }] : []),
                {
                  label: 'Rename all episode files',
                  icon: faIcon('fass', 'file-pen'),
                  disabled: fileRenameDisabledReason !== undefined,
                  disabledReason: fileRenameDisabledReason,
                  operation: fileRenameOperation,
                  starting: isStarting('collection.rename_files'),
                  controls: operationControls(fileRenameOperation?.id, 'File Rename'),
                  onSelect: () => setFileRenameConfirm(true),
                },
                {
                  label: 'Match existing files',
                  icon: faIcon('fass', 'file-import'),
                  disabled: existingFilesProfiles.length === 0,
                  disabledReason: existingFilesProfiles.length === 0 ? 'Add a Local Media Profile first.' : undefined,
                  onSelect: () => setExistingFilesProfileId(existingFilesProfiles[0]?.id ?? null),
                },
                {
                  label: 'Bulk delete downloads',
                  icon: faIcon('fass', 'trash'),
                  tone: 'danger',
                  disabled: deleteDownloadsDisabledReason !== undefined,
                  disabledReason: deleteDownloadsDisabledReason,
                  operation: deleteDownloadsOperation,
                  starting: isStarting('collection.delete_downloads'),
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
                  starting: isStarting('collection.redownload_episodes'),
                  controls: operationControls(redownloadOperation?.id, 'bulk delete and re-download', false),
                  onSelect: () => setRedownloadConfirm(true),
                },
                {
                  label: 'Create download profile',
                  icon: faIcon('fass', 'download'),
                  separatorBefore: true,
                  href: `/add-download-profile?collection=${encodeURIComponent(id)}`,
                },
                {
                  label: 'Create stream profile',
                  icon: faIcon('fass', 'rss'),
                  href: `/add-stream-profile?collection=${encodeURIComponent(id)}`,
                },
              ]}
            />
              </>
            )}
          </div>

          {can('library', 'manage') && (
            <ExistingFilesBanner
              collectionSlug={id}
              profileName={(profileId) => localMediaProfiles?.find((profile) => profile.id === profileId)?.name ?? `Local Media Profile #${profileId}`}
              onOpen={setExistingFilesProfileId}
            />
          )}

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
                  <div className="collection-profile-group-label" title={`Download ${attachedDownloadProfiles.length === 1 ? 'profile' : 'profiles'}`}>
                    <FontAwesomeIcon icon={faIcon('fass', 'download')} aria-hidden="true"/>
                    <span className="collection-profile-group-name">Download {attachedDownloadProfiles.length === 1 ? 'profile' : 'profiles'}</span>
                  </div>
                  <div className="collection-profile-links">
                    {attachedDownloadProfiles.map((profile) => (
                      <Link
                        key={profile.id}
                        className="collection-profile-chip"
                        to={`/edit-download-profile/${profile.id}`}
                        title={`Open ${preferredFormatLabel(profile.localMediaProfilePreferredFormat)} download profile`}
                      >
                        <span>{preferredFormatLabel(profile.localMediaProfilePreferredFormat)}</span>
                        <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                      </Link>
                    ))}
                  </div>
                </div>
              )}

              {attachedStreamProfiles.length > 0 && (
                <div className="collection-profile-group">
                  <div className="collection-profile-group-label" title={`Stream ${attachedStreamProfiles.length === 1 ? 'profile' : 'profiles'}`}>
                    <FontAwesomeIcon icon={faIcon('fass', 'rss')} aria-hidden="true"/>
                    <span className="collection-profile-group-name">Stream {attachedStreamProfiles.length === 1 ? 'profile' : 'profiles'}</span>
                  </div>
                  <div className="collection-profile-links">
                    {attachedStreamProfiles.map((profile) => {
                      const feedUrl = profile.type === 'rss' ? profile.streamProfileImpl?.feedUrl : undefined
                      const copied = copiedStreamProfileId === profile.id
                      const label = `${profile.type.toUpperCase()} ${preferredFormatLabel(profile.preferredFormat)}`
                      return (
                        <div key={`${profile.type}-${profile.id}`} className="collection-profile-chip-group">
                          <Link
                            className="collection-profile-chip collection-profile-chip-main"
                            to={`/edit-stream-profile/${profile.type}/${profile.id}`}
                            title={`Open ${label}`}
                          >
                            <span>{label}</span>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')} aria-hidden="true"/>
                          </Link>
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
                {displayedTotal} {displayedTotal === 1 ? countNouns.singular : countNouns.plural}
              </span>
            )}
          </div>
        )}

        {((episodeTags && episodeTags.length > 1) || lockedTotal > 0) && (
          <div className="collection-type-filter">
            {episodeTags && (
              <EpisodeTypeFilter
                tags={episodeTags}
                selected={episodeTypeFilter}
                onChange={setEpisodeTypeFilter}
              />
            )}
            <LockedEpisodesFilter lockedTotal={lockedTotal} shown={showLocked} onChange={setShowLocked}/>
            {(typeFiltered || lockedHidden) && !isSeasonal && displayedTotal !== undefined && (
              <span className="collection-type-count">
                {displayedTotal} {displayedTotal === 1 ? countNouns.singular : countNouns.plural}
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
        ) : (typeFiltered || lockedHidden) && visibleItems.length === 0 && episodePagesData !== undefined ? (
          <div className="collection-season-empty" role="status">
            {typeFiltered
              ? `No ${lockedHidden ? 'unlocked ' : ''}episodes of the selected types${isSeasonal ? ' in this season' : ''}.`
              : `Every episode${isSeasonal ? ' in this season' : ''} is locked. Turn on Locked to show them.`}
          </div>
        ) : (
          <div className="episodes-grid" role="list" aria-label={`${collection.title} episodes`}>
            {visibleItems.map((ep: any) => (
              <EpisodeCard
                key={ep.id} ep={ep} collectionSlug={id} downloads={downloadsBySlug.get(ep.slug)}
              />
            ))}
          </div>
        )}

        {!episodesViewLoading && (episodesFailed ? (
          <div className="episodes-load-more episodes-load-failed" role="alert">
            <span>
              {isFetchNextPageError || visibleItems.length > 0
                ? `Could not load the rest of the episodes, ${visibleItems.length} of ${total} are shown.`
                : 'Could not load the episodes.'}
            </span>
            <button type="button" className="btn" onClick={retryEpisodes}>
              <FontAwesomeIcon icon={faIcon('fass', 'rotate-right')} aria-hidden="true"/> Try again
            </button>
          </div>
        ) : episodesFromCache && visibleItems.length > 0 ? (
          <div className="episodes-load-more" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Loading episodes…
          </div>
        ) : sentinelShown ? (
          <div ref={sentinelRef} className="episodes-load-more" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Loading more episodes…
          </div>
        ) : null)}
      </article>

      <CollectionSyncLogModal
        collectionId={collection.id}
        collectionSlug={id}
        collectionTitle={collection.title}
        open={syncLogOpen}
        starting={syncStarting}
        onClose={() => setSyncLogOpen(false)}
        onSyncNow={syncNow}
        onCancelSync={syncOperation ? () => void controlTaskOperation(syncOperation.id, 'cancel', 'Sync') : undefined}
        cancelSyncDisabled={operationControlBusy !== null}
      />

      {existingFilesProfileId !== null && can('library', 'manage') && (
        <ExistingFilesDialog
          collectionSlug={id}
          collectionTitle={collection.title}
          profiles={existingFilesProfiles}
          initialProfileId={existingFilesProfileId}
          onClose={closeExistingFiles}
          onRename={(profileId) => {
            closeExistingFiles()
            setFileRenameProfileId(profileId)
            setFileRenameConfirm(true)
          }}
        />
      )}

      {downloadAllConfirm && (
        <CollectionDownloadAllDialog
          collectionSlug={id}
          collectionTitle={collection.title}
          collectionType={collection.type === 'series' ? 'series' : 'podcast'}
          sourceKey={collection.sourceKey}
          seasons={seasons}
          localMediaProfiles={localMediaProfiles ?? []}
          onDismiss={() => setDownloadAllConfirm(false)}
          onStartingChange={onStartingChange('collection.download_all')}
        />
      )}

      <ActionConfirmDialogue
        open={metadataRefreshConfirm}
        operationDefinition={frontendOperationDefinitions['collection.refresh_metadata']}
        onStartingChange={onStartingChange('collection.refresh_metadata')}
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
        onStartingChange={onStartingChange('collection.rename_files')}
        requestPath={`/collections/${encodeURIComponent(id)}/rename-files`}
        resourceLabel={collection.title}
        title="Rename existing episode files"
        onDismiss={() => { setFileRenameConfirm(false); setFileRenameProfileId(undefined) }}
        icon={faIcon('fass', 'file-pen')}
        confirmLabel="Rename files"
        disabled={fileRenameBusy}
        scope_by_local_media_profile
        localMediaProfiles={actionLocalMediaProfiles}
        initialLocalMediaProfileId={fileRenameProfileId}
      >
        <p>
          Rename existing episode files in "{collection.title}" so their paths match the current Local Media Profile output templates.
        </p>
      </ActionConfirmDialogue>

      <ActionConfirmDialogue
        open={deleteDownloadsConfirm}
        operationDefinition={frontendOperationDefinitions['collection.delete_downloads']}
        onStartingChange={onStartingChange('collection.delete_downloads')}
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
        onStartingChange={onStartingChange('collection.redownload_episodes')}
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

    </section>
  )
}
