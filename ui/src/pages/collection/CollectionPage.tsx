import {sourceControls} from '../../lib/sourceControls'
import type {TaskOperationRead} from '../../types/schemas/operation'
import {operationControls as sharedOperationControls} from '../../lib/operationControls'
import SiteLink from '../../components/common/SiteLink'
import CreatorLink from '../../components/Creator/CreatorLink'
import ReconcileDialog from '../../components/ReconcileDialog/ReconcileDialog'
import {useMovedEpisodes} from '../../components/Episode/SeasonPlaceNote'
import {addedByLabel, can} from '../../lib/access'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import Switch from 'react-switch'
import { useCollectionDownloadProfilesView, useCollectionStreamProfilesView, useEpisodePages, useCollection, useLocalMediaProfiles, useCollectionEpisodeDownloads, useCollectionDownloadedLocalMediaProfiles, useCollectionSeasons, useEpisodeTagsInCollection, useSourceLookup, useCollectionLocked } from '../../lib/queries'
import SourceBadge from '../../components/Source/SourceBadge'
import { toast } from '../../lib/toast'
import EpisodeCard, {groupDownloadsByEpisodeSlug} from '../../components/Episode/EpisodeCard'
import ActionConfirmDialogue, {type ActionConfirmDialogueLocalMediaProfile} from '../../components/ActionConfirmDialogue/ActionConfirmDialogue'
import RedownloadSwitch from '../../components/ActionConfirmDialogue/RedownloadSwitch'
import ActionMenu, {type ActionMenuItem} from '../../components/ActionMenu/ActionMenu'
import {useActiveOperation} from '../../components/OperationNotifier/OperationNotifier'
import RunningActions from '../../components/RunningActions/RunningActions'
import CollectionSyncLogModal from '../../components/CollectionSyncLogModal/CollectionSyncLogModal'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import {OperationControlError, type OperationControlAction, useControlOperation, useStartOperation, useStartingOperations} from '../../lib/operations'
import {PreferredFormatReg} from '../../types/local_media_profile'
import {getEpisodePreviewTotal, loadEpisodePreviewFromStorage} from '../../lib/cache'
import SimpleSelect from '../../components/common/SimpleSelect'
import CollectionDownloadAllDialog from './CollectionDownloadAllDialog'
import {AddToCreatorDialog, RemoveFromCreatorDialog} from './CollectionCreatorDialogs'
import {createSelectRegistry} from '../../utils/selectRegistry'
import './CollectionPage.css'
import {faIcon} from '../../icons/faIcon'
import {presentIndexingStatus, presentScanningStatus} from '../../lib/operationProgress'
import {siteName} from '../../lib/siteName'
import ExistingFilesDialog from '../../components/ExistingFiles/ExistingFilesDialog'
import ExistingFilesBanner from '../../components/ExistingFiles/ExistingFilesBanner'
import {useExistingFilesScans} from '../../components/ExistingFiles/api'
import EpisodeTypeFilter from '../../components/Episode/EpisodeTypeFilter'
import LockedEpisodesFilter from '../../components/Episode/LockedEpisodesFilter'
import {ApiError, apiFetch, apiUrl, publicAddress} from '../../lib/api'
import {fileWordsFor, wordsFor} from '../../lib/collectionWords'
import {isCollectionLocalMediaProfileAvailableFor, type CollectionLocalMediaProfileContext} from '../../types/local_media_profile'
import {nameInText} from '../../lib/nameInText'

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
  const {data: movedEpisodes} = useMovedEpisodes(id)
  // Moved episodes wait for the Move action, which Home links to as well.
  const waitingCount = movedEpisodes?.size ?? 0
  const startOperation = useStartOperation()
  const controlOperation = useControlOperation()
  const {isStarting, onStartingChange} = useStartingOperations()
  const PAGE_SIZE = 36

  const { data: collection, isLoading, error } = useCollection(id)
  const words = wordsFor(collection)
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
  // A collection whose lists bring in videos it would not have, or only theirs, is browsed by season, as its lists
  // are its seasons, whatever numbers its episodes.
  const isSeasonal = collection?.episodeIdentifier === 'seasonal'
    || (!!collection?.outsideVideos && collection.outsideVideos !== 'leave_out')

  const [syncStarting, setSyncStarting] = useState(false)
  const [metadataRefreshConfirm, setMetadataRefreshConfirm] = useState(false)
  const [fileRenameConfirm, setFileRenameConfirm] = useState(false)
  const [metadataRewriteConfirm, setMetadataRewriteConfirm] = useState(false)
  const [renameSeasonFolders, setRenameSeasonFolders] = useState(true)
  const [fileRenameProfileId, setFileRenameProfileId] = useState<number | undefined>(undefined)
  const [searchParams, setSearchParams] = useSearchParams()
  const reconciling = searchParams.get('move') === '1'
  const seasonParam = searchParams.get('season')
  const setReconciling = (open: boolean) => setSearchParams((current) => {
    const next = new URLSearchParams(current)
    if (open) next.set('move', '1')
    else next.delete('move')
    return next
  }, {replace: true})
  const existingFilesParam = Number(searchParams.get('existingFiles'))
  const [existingFilesProfileId, setExistingFilesProfileId] = useState<number | null>(
    Number.isInteger(existingFilesParam) && existingFilesParam > 0 ? existingFilesParam : null,
  )
  const [deleteDownloadsConfirm, setDeleteDownloadsConfirm] = useState(false)
  const [redownloadAfterDelete, setRedownloadAfterDelete] = useState(false)
  const [downloadAllConfirm, setDownloadAllConfirm] = useState(false)
  const [creatorDialog, setCreatorDialog] = useState<'add' | 'remove' | null>(null)
  const [syncLogOpen, setSyncLogOpen] = useState(false)
  const [copiedStreamProfileId, setCopiedStreamProfileId] = useState<number | null>(null)
  const [selectedSeasonId, setSelectedSeasonId] = useState<number | null>(null)
  const [operationControlBusy, setOperationControlBusy] = useState<string | null>(null)

  const {
    data: seasonsData,
    isLoading: seasonsLoading,
    isPlaceholderData: seasonsPlaceholder,
  } = useCollectionSeasons(collection ? id : undefined)
  const seasons = useMemo(
    () => [...(seasonsData ?? [])].sort((a, b) => b.index - a.index),
    [seasonsData],
  )
  const seasonReg = useMemo(() => {
    const spec: Record<string, {label: string}> = {}
    const values: string[] = []
    for (const season of seasons) {
      const value = String(season.id)
      spec[value] = {label: season.name?.trim() || `${words.season.Singular} ${season.index}`}
      values.push(value)
    }
    return createSelectRegistry('CollectionSeason', spec, values)
  }, [seasons, words])
  // A collection that lists every season's episodes together names each one's season, so that a video in several
  // seasons, such as a channel's and two playlists', is not taken for a duplicate.
  const seasonNames = useMemo(
    () => !isSeasonal && seasons.length > 1 ? new Map(seasons.map((season) => [season.id, seasonReg.getLabel(String(season.id))])) : undefined,
    [isSeasonal, seasons, seasonReg],
  )

  useEffect(() => {
    if (!isSeasonal || seasons.length === 0) {
      setSelectedSeasonId(null)
      return
    }

    setSelectedSeasonId((current) => {
      if (current !== null && seasons.some((season) => season.id === current)) return current
      // The season the page's address names, as it does after the user picked one and came back to the page.
      const named = seasonParam ? seasons.find((season) => season.slug === seasonParam) : undefined
      if (named) return named.id
      // It opens on the channel season while that holds the whole channel, such as Channel on YouTube.
      const channel = seasons.find((season) => season.wholeChannel)
      if (channel) return channel.id
      // Otherwise on the season with the newest episode, which is the last one unless a season such as a
      // channel's Videos keeps growing beside the others.
      const newest = seasons.reduce((best, season) => (
        (season.newestPublishedAt?.getTime() ?? 0) > (best.newestPublishedAt?.getTime() ?? 0) ? season : best
      ), seasons[0])
      return newest.id
    })
  }, [isSeasonal, seasons, seasonParam])

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
  const countNouns = singleTypeTag?.names ?? words.episode
  // Locked episodes start shown, unless the collection's Site mixes them among open ones, such as a
  // YouTube channel's members-only videos. Episodes the account can watch are never hidden.
  const [storedShowLocked, setShowLocked] = useShowLocked(id)
  const showLocked = storedShowLocked ?? collection?.site?.showsLocked ?? true
  // A Music collection's creator is an artist, as VODLoft calls any creator with Music collections.
  const creatorNames = collection?.creatorNames
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
  // A Music collection's files are tracks while only profiles for Music that download audio only are offered for it.
  const fileWords = fileWordsFor(collection, localMediaProfiles
    ?.filter((profile) => isCollectionLocalMediaProfileAvailableFor(profile, collection?.type)))
  const { data: streamProfiles } = useCollectionStreamProfilesView(id)
  const downloadsBySlug = useMemo(() => groupDownloadsByEpisodeSlug(downloads), [downloads])

  const operationResourceId = collection?.id ?? null
  const indexingOperation = useActiveOperation('collection.index', 'collection', operationResourceId)
  const syncOperation = useActiveOperation('collection.sync', 'collection', operationResourceId)
  const metadataRefreshOperation = useActiveOperation('collection.refresh_metadata', 'collection', operationResourceId)
  const fileRenameOperation = useActiveOperation('collection.rename_files', 'collection', operationResourceId)
  const deleteDownloadsOperation = useActiveOperation('collection.delete_downloads', 'collection', operationResourceId)
  const redownloadOperation = useActiveOperation('collection.redownload_episodes', 'collection', operationResourceId)
  const downloadAllOperation = useActiveOperation('collection.download_all', 'collection', operationResourceId)
  const metadataRewriteOperation = useActiveOperation('collection.rewrite_metadata', 'collection', operationResourceId)
  const identificationOperation = useActiveOperation('collection.change_identification', 'collection', operationResourceId)
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
        <p>{error instanceof ApiError && error.status === 404 ? 'This collection no longer exists.' : (error as any)?.message ?? 'Collection not found.'}</p>
      </section>
    )
  }

  const visibleItems = displayedEpisodes
  const episodesViewLoading = episodesInitialLoading || seasonViewLoading

  const openOnName = collection.site?.name ?? (sources.get(collection.sourceKey)?.domains.includes('*') ? (collection.sharingUrl ? siteName(collection.sharingUrl) : null) ?? sources.name(collection.sourceKey) : sources.name(collection.sourceKey))

  const metadataRefreshDisabledReason = metadataRefreshOperation
    ? metadataRefreshOperation.status === 'WAITING'
      ? metadataRefreshOperation.message || OPERATION_WAITING_MESSAGE
      : `VODLoft is refreshing the info of ${nameInText(collection.title)} from ${openOnName}.${metadataRefreshOperation.progressTotal > 0
        ? ` ${metadataRefreshOperation.progressCurrent}/${metadataRefreshOperation.progressTotal} ${words.episode.plural} have finished.`
        : ''}`
    : undefined
  const downloadStateUnknown = downloadsLoading && downloadedLocalMediaProfiles === undefined
  const downloadStateFailed = Boolean(downloadsError) && downloadedLocalMediaProfiles === undefined
  const downloadStateDisabledReason = downloadStateUnknown
    ? `VODLoft is still checking for downloaded ${fileWords.episode.plural} in ${nameInText(collection.title)}.`
    : downloadStateFailed
      ? `VODLoft could not determine whether ${nameInText(collection.title)} has downloaded ${fileWords.episode.plural}.`
      : downloadLocalMediaProfiles.length === 0
        ? `No downloaded ${fileWords.episode.plural} exist for ${nameInText(collection.title)}.`
        : undefined
  const identificationDisabledReason = identificationOperation
    ? `VODLoft is numbering the ${words.episode.plural} of ${nameInText(collection.title)} again and renaming their files.`
    : undefined
  const fileRenameDisabledReason = fileRenameOperation
    ? fileRenameOperation.status === 'WAITING'
      ? fileRenameOperation.message || OPERATION_WAITING_MESSAGE
      : `A File Rename operation is running for ${nameInText(collection.title)}.`
    : identificationDisabledReason ?? downloadStateDisabledReason
  const metadataRewriteDisabledReason = metadataRewriteOperation
    ? metadataRewriteOperation.status === 'WAITING'
      ? metadataRewriteOperation.message || OPERATION_WAITING_MESSAGE
      : `VODLoft is writing the info of ${nameInText(collection.title)} into its files.`
    : identificationDisabledReason ?? downloadStateDisabledReason
  const bulkDeleteOperation = deleteDownloadsOperation ?? redownloadOperation
  const deleteDownloadsDisabledReason = bulkDeleteOperation
    ? bulkDeleteOperation.status === 'WAITING'
      ? bulkDeleteOperation.message || OPERATION_WAITING_MESSAGE
      : deleteDownloadsOperation
        ? `A bulk delete downloads operation is running for ${nameInText(collection.title)}.`
        : `A bulk delete and re-download operation is running for ${nameInText(collection.title)}.`
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

  const operationControls = (operation: TaskOperationRead | undefined, label: string, restartable = true) => (
    sharedOperationControls(operation, label, {
      restartable, busy: operationControlBusy !== null,
      onControl: (operationId, action) => void controlTaskOperation(operationId, action, label),
    })
  )

  const syncNow = async () => {
    if (syncBusy) {
      toast(`A sync is in progress for ${nameInText(collection.title)}`)
      return
    }
    setSyncStarting(true)
    try {
      const base = apiUrl()
      await startOperation(`${base}/collections/${encodeURIComponent(id)}/sync`, {method: 'POST'})
      toast.success(`Sync started for ${nameInText(collection.title)}`)
    } catch {
      toast.error(`Could not start sync for ${nameInText(collection.title)}`)
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

  const actionItems: ActionMenuItem[] = [
    {
      label: 'Sync log',
      icon: faIcon('fass', 'clock-rotate-left'),
      onSelect: () => setSyncLogOpen(true),
    },
    {
      label: 'Bulk download',
      icon: faIcon('fass', 'download'),
      disabled: downloadAllBusy,
      disabledReason: downloadAllBusy ? `A bulk download is running for ${nameInText(collection.title)}.` : undefined,
      operation: downloadAllOperation,
      starting: isStarting('collection.download_all'),
      controls: operationControls(downloadAllOperation, 'bulk download'),
      onSelect: () => setDownloadAllConfirm(true),
    },
    ...(lockedCount ? [{
      label: `Check locked videos again (${lockedCount})`,
      icon: faIcon('fass', 'unlock') as [string, string],
      disabled: lockedCheckBusy,
      disabledReason: lockedCheckBusy ? 'The locked videos are being checked again.' : undefined,
      onSelect: () => void checkLockedAgain(),
    }] : []),
    ...(collection.creatorSlug ? [{
      label: `Remove from ${creatorNames?.singular}`,
      icon: faIcon('fass', 'link-slash') as [string, string],
      onSelect: () => setCreatorDialog('remove'),
    }] : collection.kind === 'channel' ? [{
      label: `Add to ${creatorNames?.singular}`,
      icon: faIcon('fass', 'circle-user') as [string, string],
      onSelect: () => setCreatorDialog('add'),
    }] : []),
    ...(sourceControls(collection).metadataRefresh ? [{
      label: `Refresh info from ${openOnName}`,
      description: `Looks every ${words.episode.singular} up again`,
      icon: faIcon('fass', 'clipboard-list') as [string, string],
      disabled: metadataRefreshBusy,
      disabledReason: metadataRefreshDisabledReason,
      operation: metadataRefreshOperation,
      starting: isStarting('collection.refresh_metadata'),
      controls: operationControls(metadataRefreshOperation, 'info refresh'),
      onSelect: () => setMetadataRefreshConfirm(true),
    }] : []),
    ...(waitingCount ? [{
      label: `Move ${fileWords.episode.plural}`,
      description: `${waitingCount} downloaded ${waitingCount === 1 ? `${fileWords.episode.singular} belongs` : `${fileWords.episode.plural} belong`} in another ${words.season.singular} now`,
      icon: faIcon('fass', 'arrow-right-arrow-left') as [string, string],
      onSelect: () => setReconciling(true),
    }] : []),
    {
      label: `Rename all ${fileWords.episode.singular} files`,
      icon: faIcon('fass', 'file-pen'),
      disabled: fileRenameDisabledReason !== undefined,
      disabledReason: fileRenameDisabledReason,
      operation: fileRenameOperation,
      starting: isStarting('collection.rename_files'),
      controls: operationControls(fileRenameOperation, 'File Rename'),
      onSelect: () => setFileRenameConfirm(true),
    },
    {
      label: 'Write info into files',
      description: 'Updates the tags and NFO files of downloads',
      icon: faIcon('fass', 'file-lines'),
      disabled: metadataRewriteDisabledReason !== undefined,
      disabledReason: metadataRewriteDisabledReason,
      operation: metadataRewriteOperation,
      starting: isStarting('collection.rewrite_metadata'),
      controls: operationControls(metadataRewriteOperation, 'writing info into files'),
      onSelect: () => setMetadataRewriteConfirm(true),
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
      operation: bulkDeleteOperation,
      starting: isStarting('collection.delete_downloads') || isStarting('collection.redownload_episodes'),
      controls: deleteDownloadsOperation
        ? operationControls(deleteDownloadsOperation, 'bulk delete downloads')
        : operationControls(redownloadOperation, 'bulk delete and re-download', false),
      onSelect: () => {
        setRedownloadAfterDelete(false)
        setDeleteDownloadsConfirm(true)
      },
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
    ]

  return (
    <section className="view collection-view" aria-labelledby="collection-title">
      <div className="view-header collection-title-row">
        <h1 id="collection-title">{collection.title}</h1>
        <SourceBadge sourceKey={collection.sourceKey}/>
      </div>

      <article className="collection-details" aria-label="Show details">
        <header className="collection-page-header">
          <div className="collection-page-heading">
            {collection.creatorSlug
              ? <CreatorLink slug={collection.creatorSlug} title={collection.creatorTitle ?? collection.authorName} avatarUrl={collection.creatorAvatarUrl}/>
              : <div className="collection-author">{collection.authorName}</div>}
            <div className="collection-meta">{[words.count(total), collection.years, addedByLabel(collection.addedBy)].filter(Boolean).join(' • ')}</div>
          </div>

          <div className="collection-page-actions">
            {collection.sharingUrl && openOnName && (
              <SiteLink className="collection-open-link" url={collection.sharingUrl} siteName={openOnName} site={collection.site}/>
            )}
            {can('library', 'manage') && (
              <>
            <Link className="btn" title="Edit show" to={`/edit-collection/${id}`}>
              <FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')} aria-hidden="true"/>
              <span>Edit</span>
            </Link>
            <ActionMenu items={actionItems}/>
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

          <RunningActions
            className="collection-page-running-actions"
            actions={[
              {
                label: 'Indexing',
                icon: faIcon('fass', 'list'),
                operation: indexingOperation,
                status: indexingOperation ? presentIndexingStatus(indexingOperation) ?? undefined : undefined,
              },
              {
                label: `Changing ${words.episode.singular} identification`,
                icon: faIcon('fass', 'list-ol'),
                operation: identificationOperation,
                controls: operationControls(identificationOperation, `${words.episode.singular} identification change`, false),
              },
              {
                label: 'Sync',
                icon: faIcon('fass', 'arrows-rotate'),
                operation: syncOperation,
                starting: syncStarting,
                status: syncOperation ? presentScanningStatus(syncOperation) ?? undefined : undefined,
              },
              ...actionItems,
            ]}
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
                        to={`/download-profile/${profile.id}`}
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
                      const impl = profile.streamProfileImpl
                      const feedUrl = impl.type === 'rss' ? impl.feedUrl : publicAddress(
                        impl.type === 'iptv' ? impl.playlistPath : impl.sharePath,
                      )
                      const what = {rss: 'RSS URL', iptv: 'playlist URL', webdav: 'share URL'}[impl.type]
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
                          {feedUrl && (
                            <button
                              type="button"
                              className="collection-profile-copy"
                              onClick={() => copyFeedUrl(profile.id, feedUrl)}
                              aria-label={copied ? `${what} copied` : `Copy ${what}`}
                              title={copied ? 'Copied!' : `Copy ${what}`}
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

        {/* A collection with one season, such as one made from an album, is that season: there is nothing to choose. */}
        {isSeasonal && seasons.length > 1 && (
          <div className="collection-season-filter" aria-label={`${words.season.Singular} selection`}>
            <label htmlFor="collection-season">{words.season.Singular}</label>
            <SimpleSelect
              inputId="collection-season"
              className="collection-season-select"
              registry={seasonReg}
              value={selectedSeasonId === null ? null : String(selectedSeasonId)}
              onChange={(value) => {
                const season = seasons.find((item) => item.id === Number(value))
                setSelectedSeasonId(Number(value))
                // The address names the season, so going back to the page, or to it from an episode, opens it again.
                if (season) setSearchParams((current) => {
                  const next = new URLSearchParams(current)
                  next.set('season', season.slug)
                  return next
                }, {replace: true})
              }}
              placeholder={`Select ${words.season.a}`}
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
            <LockedEpisodesFilter lockedTotal={lockedTotal} shown={showLocked} onChange={setShowLocked} noun={words.episode}/>
            {(typeFiltered || lockedHidden) && (!isSeasonal || seasons.length === 1) && displayedTotal !== undefined && (
              <span className="collection-type-count">
                {displayedTotal} {displayedTotal === 1 ? countNouns.singular : countNouns.plural}
              </span>
            )}
          </div>
        )}

        {indexingOperation && (isSeasonal
          ? !seasonViewLoading && seasons.length === 0
          : !episodesViewLoading && episodePagesData !== undefined && visibleItems.length === 0 && !typeFiltered && !lockedHidden) ? (
          // Nothing to show yet because the collection is still being listed for the first time.
          <div className="collection-season-empty" role="status">{nameInText(collection.title)} is still indexing. Please come back later.</div>
        ) : isSeasonal && !seasonViewLoading && seasons.length === 0 ? (
          <div className="collection-season-empty" role="status">No {words.season.plural} are available for {nameInText(collection.title)}.</div>
        ) : episodesViewLoading ? (
          <div className="episodes-grid" role="status" aria-label={`Loading ${words.episode.plural}`} aria-busy="true">
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
              ? `No ${lockedHidden ? 'unlocked ' : ''}${words.episode.plural} of the selected types${isSeasonal ? ` in this ${words.season.singular}` : ''}.`
              : `Every ${words.episode.singular}${isSeasonal ? ` in this ${words.season.singular}` : ''} is locked. Turn on Locked to show them.`}
          </div>
        ) : (
          <div className="episodes-grid" role="list" aria-label={`${nameInText(collection.title)} ${words.episode.plural}`}>
            {visibleItems.map((ep: any) => (
              <EpisodeCard
                key={ep.id} ep={ep} collectionSlug={id} downloads={downloadsBySlug.get(ep.slug)}
                moved={movedEpisodes?.has(ep.slug)}
                seasonName={seasonNames?.get(ep.seasonId)}
                words={words}
              />
            ))}
          </div>
        )}

        {!episodesViewLoading && (episodesFailed ? (
          <div className="episodes-load-more episodes-load-failed" role="alert">
            <span>
              {isFetchNextPageError || visibleItems.length > 0
                ? `Could not load the rest of the ${words.episode.plural}, ${visibleItems.length} of ${total} are shown.`
                : `Could not load the ${words.episode.plural}.`}
            </span>
            <button type="button" className="btn" onClick={retryEpisodes}>
              <FontAwesomeIcon icon={faIcon('fass', 'rotate-right')} aria-hidden="true"/> Try again
            </button>
          </div>
        ) : episodesFromCache && visibleItems.length > 0 ? (
          <div className="episodes-load-more" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Loading {words.episode.plural}…
          </div>
        ) : sentinelShown ? (
          <div ref={sentinelRef} className="episodes-load-more" role="status">
            <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Loading more {words.episode.plural}…
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
          collectionType={collection.type as CollectionLocalMediaProfileContext}
          siteKey={collection.site?.key}
          seasons={seasons}
          words={fileWords}
          localMediaProfiles={localMediaProfiles ?? []}
          onDismiss={() => setDownloadAllConfirm(false)}
          onStartingChange={onStartingChange('collection.download_all')}
        />
      )}

      <AddToCreatorDialog
        open={creatorDialog === 'add'}
        collectionSlug={collection.slug}
        collectionTitle={collection.title}
        creatorNames={creatorNames}
        onDismiss={() => setCreatorDialog(null)}
      />
      <RemoveFromCreatorDialog
        open={creatorDialog === 'remove'}
        collectionSlug={collection.slug}
        collectionTitle={collection.title}
        creatorNames={creatorNames}
        creatorTitle={collection.creatorTitle}
        onDismiss={() => setCreatorDialog(null)}
      />

      <ActionConfirmDialogue
        open={metadataRefreshConfirm}
        operationDefinition={frontendOperationDefinitions['collection.refresh_metadata']}
        onStartingChange={onStartingChange('collection.refresh_metadata')}
        requestPath={`/collections/${encodeURIComponent(id)}/refresh-metadata`}
        resourceLabel={collection.title}
        title={`Refresh info from ${openOnName}`}
        onDismiss={() => setMetadataRefreshConfirm(false)}
        icon={faIcon('fass', 'arrows-rotate')}
        confirmLabel="Refresh info"
        disabled={metadataRefreshBusy}
      >
        <p>
          Look every {words.episode.singular} in "{collection.title}" up at {openOnName} again, so changed titles,
          descriptions and thumbnails reach VODLoft. This can take a while and is usually not needed. Downloaded files
          keep their tags: use Write info into files for those.
        </p>
      </ActionConfirmDialogue>

      <ReconcileDialog
        open={reconciling}
        path={`/collections/${encodeURIComponent(id)}`}
        what={`the ${fileWords.episode.plural} of ${nameInText(collection.title)}`}
        onDismiss={() => setReconciling(false)}
      />

      <ActionConfirmDialogue
        open={fileRenameConfirm}
        operationDefinition={frontendOperationDefinitions['collection.rename_files']}
        onStartingChange={onStartingChange('collection.rename_files')}
        requestPath={`/collections/${encodeURIComponent(id)}/rename-files`}
        resourceLabel={collection.title}
        title={`Rename existing ${fileWords.episode.singular} files`}
        onDismiss={() => { setFileRenameConfirm(false); setFileRenameProfileId(undefined) }}
        icon={faIcon('fass', 'file-pen')}
        confirmLabel="Rename files"
        disabled={fileRenameBusy}
        scope_by_local_media_profile
        localMediaProfiles={actionLocalMediaProfiles}
        initialLocalMediaProfileId={fileRenameProfileId}
        extraBody={{seasonFolders: renameSeasonFolders}}
      >
        <p>
          Rename existing {fileWords.episode.singular} files in "{collection.title}" so their paths match the current Local Media Profile output templates.
        </p>
        <label className="rename-season-folders">
          <Switch
            checked={renameSeasonFolders}
            onChange={setRenameSeasonFolders}
            onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
            height={18} width={34} handleDiameter={14}
          />
          <span>
            <b>Rename {words.season.singular} folders too</b>
            <span className="help">
              {fileWords.episode.Plural} move into the folders of the {words.season.plural} they are in now, with their
              {' '}{words.season.singular}'s number, also after {words.season.plural} were reordered.{' '}
              {collection.type === 'music'
                ? `In a collection of the artist's albums, downloaded ${fileWords.episode.plural} also move to the album they belong in now.`
                : `In a collection whose ${words.season.plural} come from the site's lists, downloaded ${fileWords.episode.plural} also move to the ${words.season.singular} of the list they belong in now.`}
            </span>
          </span>
        </label>
      </ActionConfirmDialogue>

      <ActionConfirmDialogue
        open={metadataRewriteConfirm}
        operationDefinition={frontendOperationDefinitions['collection.rewrite_metadata']}
        onStartingChange={onStartingChange('collection.rewrite_metadata')}
        requestPath={`/collections/${encodeURIComponent(id)}/rewrite-metadata`}
        resourceLabel={collection.title}
        title="Write info into files"
        onDismiss={() => setMetadataRewriteConfirm(false)}
        icon={faIcon('fass', 'file-lines')}
        confirmLabel="Write into files"
        disabled={metadataRewriteOperation !== undefined}
        scope_by_local_media_profile
        localMediaProfiles={actionLocalMediaProfiles}
      >
        <p>
          Write the titles, descriptions, numbers and other details VODLoft has now into the downloaded files of
          "{collection.title}" and their NFO files, as the Local Media Profile keeps them. Nothing is looked up at
          {' '}{openOnName} and nothing is downloaded again:
          each file is copied once with its new details, so this needs free space for the largest file.
        </p>
      </ActionConfirmDialogue>

      <ActionConfirmDialogue
        open={deleteDownloadsConfirm}
        operationDefinition={frontendOperationDefinitions[redownloadAfterDelete ? 'collection.redownload_episodes' : 'collection.delete_downloads']}
        onStartingChange={onStartingChange(redownloadAfterDelete ? 'collection.redownload_episodes' : 'collection.delete_downloads')}
        requestPath={`/collections/${encodeURIComponent(id)}/${redownloadAfterDelete ? 'redownload-episodes' : 'delete-downloads'}`}
        resourceLabel={collection.title}
        title="Bulk delete downloads"
        onDismiss={() => setDeleteDownloadsConfirm(false)}
        icon={faIcon('fass', 'trash')}
        iconTone="danger"
        confirmLabel={redownloadAfterDelete ? 'Delete and re-download' : 'Bulk delete downloads'}
        disabled={deleteDownloadsBusy || redownloadBusy}
        scope_by_local_media_profile
        showDeleteOlderThan
        localMediaProfiles={actionLocalMediaProfiles}
      >
        <p>
          Delete downloaded {fileWords.episode.singular} files in "{collection.title}".
        </p>
        <RedownloadSwitch
          label={`Re-download the deleted ${fileWords.episode.plural}`}
          checked={redownloadAfterDelete}
          onChange={setRedownloadAfterDelete}
          help={redownloadAfterDelete ? (
            <>
              VODLoft downloads each deleted {fileWords.episode.singular} again right away.
              This can take a long time, use significant bandwidth, and is usually not needed.
            </>
          ) : (
            <>
              When you delete everything, VODLoft first disables any Download Profiles attached to the selected Local Media Profile or Profiles. Re-enable a disabled Download Profile whenever you want VODLoft to download its eligible {fileWords.episode.plural} again.
              Deleting only older {fileWords.episode.plural} leaves Download Profiles on, so they may download those {fileWords.episode.plural} again.
            </>
          )}
        />
      </ActionConfirmDialogue>

    </section>
  )
}
