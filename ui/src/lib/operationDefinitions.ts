import {partialMatchKey, type QueryClient, type QueryKey} from '@tanstack/react-query'

import {type TaskOperationRead} from '../types/schemas/operation'
import {collectionWords, type Noun} from './collectionWords'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from './cache'
import {episodeQueryKeys} from './collectionQueryOptions'
import {quickDownloadFileUrl, quickDownloadToastId} from './quickDownloads'
import {nameInText} from './nameInText'

export type OperationMessageResolver = (operation: TaskOperationRead) => string

export type OperationNotificationAction = {
  label: string
  href: string
  download?: string
  /** Names the toast, so another operation's `dismissesToast` can close it. */
  toastId?: string
}

export type OperationNotificationDefinition = {
  label: string
  success?: OperationMessageResolver
  /** A link the success notification offers, such as the file a quick download made. */
  successAction?: (operation: TaskOperationRead) => OperationNotificationAction | undefined
  /** The toast this operation makes obsolete, such as the offer of a file that has now been downloaded. */
  dismissesToast?: (operation: TaskOperationRead) => string | undefined
  partial?: OperationMessageResolver
  canceled?: OperationMessageResolver
  failed?: OperationMessageResolver
}

export type OperationNotificationDefinitions = Readonly<
  Record<string, OperationNotificationDefinition>
>

/** The query keys an operation's outcome makes stale; each matches its key and every longer one. */
type InvalidationCollector = QueryKey[]
type OperationInvalidation = (
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) => void

export type FrontendOperationDefinition = OperationNotificationDefinition & {
  kind: string
  resourceType: string
  invalidate?: OperationInvalidation
}

function contextString(operation: TaskOperationRead, key: string): string | undefined {
  const value = operation.context?.[key]
  return typeof value === 'string' && value ? value : undefined
}

function contextNumber(operation: TaskOperationRead, key: string): number | undefined {
  const value = operation.context?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function resultString(operation: TaskOperationRead, key: string): string | undefined {
  const value = operation.result?.data?.[key]
  return typeof value === 'string' && value ? value : undefined
}

function resultNumber(operation: TaskOperationRead, key: string): number | undefined {
  const value = operation.result?.data?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function completedCount(operation: TaskOperationRead): number {
  return resultNumber(operation, 'completed') ?? operation.progressCurrent
}

function httpErrorMessage(error: string | null | undefined): string | undefined {
  if (!error) return undefined

  const match = error.match(/^HTTP error \d+:\s*([\s\S]+)$/)
  if (!match) return undefined

  try {
    const parsed = JSON.parse(match[1])
    if (parsed && typeof parsed === 'object' && typeof parsed.error === 'string' && parsed.error.trim()) {
      return parsed.error
    }
  } catch {
    // Fall back to the ordinary operation failure message for non-JSON HTTP errors.
  }

  return undefined
}

function plural(value: number, singular: string, pluralForm: string) {
  return value === 1 ? singular : pluralForm
}

/** What the operation's collection calls its episodes, such as tracks, from its type. */
function episodeWords(operation: TaskOperationRead): Noun {
  return collectionWords(contextString(operation, 'collection_type') || null).episode
}

/** A number of the operation's collection's episodes, such as 12 tracks. */
function episodeCount(operation: TaskOperationRead, count: number): string {
  return collectionWords(contextString(operation, 'collection_type') || null).count(count)
}

function fileRenameSuccessMessage(operation: TaskOperationRead, title: string): string {
  const renamed = (resultNumber(operation, 'files_renamed') ?? 0)
    + (resultNumber(operation, 'files_recovered') ?? 0)
  const unchanged = resultNumber(operation, 'files_unchanged') ?? 0
  const considered = resultNumber(operation, 'files_considered') ?? (renamed + unchanged)
  if (considered === 0) return `No existing files needed renaming for ${nameInText(title)}`
  const unchangedDetail = unchanged > 0 ? `; ${unchanged} already matched` : ''
  return `File Rename finished for ${nameInText(title)}: ${renamed} ${plural(renamed, 'file', 'files')} renamed${unchangedDetail}`
}

function invalidateCollectionEpisodeQueries(
  collectionSlug: string,
  invalidations: InvalidationCollector,
) {
  removeEpisodePreviewFromStorage(collectionSlug)
  invalidations.push(
    episodeQueryKeys.forCollection(collectionSlug),
  )
}

function invalidateCollectionEpisodeData(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  const collectionSlug = contextString(operation, 'collection_slug')
  invalidations.push(
    ['collections'],
    ['collectionsView'],
  )
  if (collectionSlug) {
    invalidations.push(['collection', collectionSlug])
    invalidateCollectionEpisodeQueries(collectionSlug, invalidations)
  }
}

function invalidateCollectionStructure(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateCollectionEpisodeData(operation, invalidations)
  invalidations.push(
    ['recentlyIndexedEpisodes'],
  )
  const collectionSlug = contextString(operation, 'collection_slug')
  if (!collectionSlug) return

  removeSeasonsFromStorage(collectionSlug)
  invalidations.push(
    ['seasons', collectionSlug],
    // The Seasons dialog, where a link gets its season once its videos are listed.
    ['collection', collectionSlug, 'seasonSettings'],
  )
}

function invalidateCollectionFiles(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  const collectionSlug = contextString(operation, 'collection_slug')
  invalidations.push(
    ['mediaDownloads'],
    ['mediaDownloadsView'],
  )
  if (collectionSlug) {
    invalidations.push(['collectionDownloads', collectionSlug])
  }
}

function invalidateCollectionDownloadDeletion(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateCollectionFiles(operation, invalidations)
  invalidations.push(['downloadProfilesView'])
}

function invalidateEpisode(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  const episodeSlug = contextString(operation, 'episode_slug')
  const resultEpisodeSlug = resultString(operation, 'episode_slug')
  const collectionSlug = contextString(operation, 'collection_slug')
  if (episodeSlug) {
    invalidations.push(['episode', episodeSlug])
  }
  if (resultEpisodeSlug && resultEpisodeSlug !== episodeSlug) {
    invalidations.push(['episode', resultEpisodeSlug])
  }
  if (collectionSlug) {
    invalidateCollectionEpisodeQueries(collectionSlug, invalidations)
  }
}

function invalidateMovie(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  const movieSlug = contextString(operation, 'movie_slug')
  invalidations.push(['movies'])
  if (movieSlug) {
    invalidations.push(
      ['dailywireMovie', movieSlug],
    )
  }
}

function invalidateMovieFiles(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateMovie(operation, invalidations)
  const movieSlug = contextString(operation, 'movie_slug')
  invalidations.push(
    ['mediaDownloads'],
    ['mediaDownloadsView'],
  )
  if (movieSlug) {
    invalidations.push(['movieDownloads', movieSlug])
  }
}

function invalidateLocalMediaProfileFiles(
  _operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidations.push(
    ['mediaDownloads'],
    ['mediaDownloadsView'],
    ['episodeDownloads'],
    ['movieDownloads'],
    ['collectionDownloads'],
    ['localMediaProfiles'],
    ['localMediaProfile'],
    ['localMediaProfileView'],
  )
}

function invalidateLocalMediaProfileDownloadDeletion(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateLocalMediaProfileFiles(operation, invalidations)
  invalidations.push(
    ['downloadProfilesView'],
    ['downloadProfilesByCollectionSlug'],
  )
}

function invalidateDownloadProfileOutOfScope(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateLocalMediaProfileDownloadDeletion(operation, invalidations)
  invalidations.push(
    ['downloadProfileView'],
    ['downloadProfileStatistics'],
    ['downloadProfileOutOfScope'],
  )
}

function invalidateMediaDownload(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  const episodeSlug = contextString(operation, 'episode_slug')
  const collectionSlug = contextString(operation, 'collection_slug')
  const movieSlug = contextString(operation, 'movie_slug')

  invalidations.push(
    ['mediaDownloads'],
    ['mediaDownloadsView'],
  )
  if (operation.resourceId != null) {
    invalidations.push(
      ['mediaDownloadHistory', operation.resourceId],
    )
  }
  if (episodeSlug) {
    invalidations.push(
      ['episodeDownloads', episodeSlug],
    )
  }
  if (collectionSlug) {
    invalidations.push(
      ['collectionDownloads', collectionSlug],
    )
  }
  if (movieSlug) {
    invalidations.push(
      ['movieDownloads', movieSlug],
      ['movies'],
    )
  }
}

function invalidateQuickDownloads(
  _operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidations.push(['quickDownloads'])
}

function quickDownloadId(operation: TaskOperationRead): string | undefined {
  return resultString(operation, 'quick_download_id') ?? contextString(operation, 'quick_download_id')
}

function quickDownloadFile(operation: TaskOperationRead): OperationNotificationAction | undefined {
  const quickId = quickDownloadId(operation)
  if (!quickId) return undefined
  return {
    label: 'Download',
    href: quickDownloadFileUrl(quickId),
    download: resultString(operation, 'file_name'),
    toastId: quickDownloadToastId(quickId),
  }
}

/** A file that went out, from wherever it was downloaded, no longer needs its offer. */
function quickDownloadDeliveredToast(operation: TaskOperationRead): string | undefined {
  const quickId = quickDownloadId(operation)
  return quickId ? quickDownloadToastId(quickId) : undefined
}

function invalidateMediaDownloadCollection(
  _operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidations.push(
    ['mediaDownloads'],
    ['mediaDownloadsView'],
    ['episodeDownloads'],
    ['movieDownloads'],
    ['collectionDownloads'],
    ['movies'],
  )
}

function invalidateTaskLedgerDefinition(
  definitionKey: string,
  invalidations: InvalidationCollector,
) {
  invalidations.push(
    ['taskLedger', definitionKey],
    ['taskLedger', 'list', definitionKey],
  )
}

function invalidateEpisodeCronJob(
  _operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidations.push(
    ['collections'],
    ['collectionsView'],
    ['episodes'],
    ['recentlyIndexedEpisodes'],
  )
}

function invalidateDownloadCronJob(
  _operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidations.push(
    ['mediaDownloads'],
    ['mediaDownloadsView'],
  )
}

function invalidateFindEpisodesCron(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateEpisodeCronJob(operation, invalidations)
  invalidateTaskLedgerDefinition('fetch_new_episodes', invalidations)
}

function invalidateQuickCheckCron(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateEpisodeCronJob(operation, invalidations)
  invalidateTaskLedgerDefinition('quick_check_new_videos', invalidations)
}

function invalidateFullRescanCron(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateEpisodeCronJob(operation, invalidations)
  invalidateTaskLedgerDefinition('rescan_quick_checked_collections', invalidations)
}

function invalidateVerifyDownloadsCron(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateDownloadCronJob(operation, invalidations)
  invalidateTaskLedgerDefinition('download_profile_worker', invalidations)
}

function invalidateFileWatcherCron(
  operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidateDownloadCronJob(operation, invalidations)
  invalidateTaskLedgerDefinition('file_watcher', invalidations)
}

function invalidateCollectionHealthCron(
  _operation: TaskOperationRead,
  invalidations: InvalidationCollector,
) {
  invalidations.push(
    ['collectionHealth'],
    ['collections'],
    ['collectionsView'],
  )
  invalidateTaskLedgerDefinition('check_collection_health', invalidations)
}

export const frontendOperationDefinitions = {
  'system.cron.find_episodes': {
    kind: 'system.cron.find_episodes',
    resourceType: 'system',
    label: 'Find new episodes',
    invalidate: invalidateFindEpisodesCron,
  },
  'system.cron.quick_check': {
    kind: 'system.cron.quick_check',
    resourceType: 'system',
    label: 'Quick check for new videos',
    invalidate: invalidateQuickCheckCron,
  },
  'system.cron.full_rescan': {
    kind: 'system.cron.full_rescan',
    resourceType: 'system',
    label: 'Re-scan collections with quick checks',
    invalidate: invalidateFullRescanCron,
  },
  'system.cron.verify_downloads': {
    kind: 'system.cron.verify_downloads',
    resourceType: 'system',
    label: 'Verify downloads',
    invalidate: invalidateVerifyDownloadsCron,
  },
  'system.cron.file_watcher': {
    kind: 'system.cron.file_watcher',
    resourceType: 'system',
    label: 'File watcher',
    invalidate: invalidateFileWatcherCron,
  },
  'system.cron.collection_health': {
    kind: 'system.cron.collection_health',
    resourceType: 'system',
    label: 'Check collection health',
    invalidate: invalidateCollectionHealthCron,
  },
  'collection.index': {
    kind: 'collection.index',
    resourceType: 'collection',
    label: 'Collection indexing',
    invalidate: invalidateCollectionStructure,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const count = resultNumber(operation, 'episodes_found')
      return count === undefined
        ? `Indexing finished for ${collectionTitle}`
        : `Indexed ${collectionTitle}: ${episodeCount(operation, count)} found`
    },
  },
  'collection.sync': {
    kind: 'collection.sync',
    resourceType: 'collection',
    label: 'Sync',
    invalidate: invalidateCollectionStructure,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const count = resultNumber(operation, 'episodes_found') ?? 0
      return `Sync finished for ${collectionTitle}: ${count} new ${plural(count, episodeWords(operation).singular, episodeWords(operation).plural)} found`
    },
  },
  'collection.refresh_metadata': {
    kind: 'collection.refresh_metadata',
    resourceType: 'collection',
    label: 'Info refresh',
    invalidate: invalidateCollectionEpisodeData,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const count = operation.progressTotal
      return count === 0
        ? `No ${episodeWords(operation).plural} to refresh in ${collectionTitle}`
        : `Info refresh completed for ${episodeCount(operation, count)} in ${collectionTitle}`
    },
  },
  'episode.refresh_metadata': {
    kind: 'episode.refresh_metadata',
    resourceType: 'episode',
    label: 'Info refresh',
    invalidate: invalidateEpisode,
    success: (operation) => {
      const episodeTitle = contextString(operation, 'episode_title') || operation.title
      return `Info refresh completed for ${episodeTitle}`
    },
  },
  'collection.rename_files': {
    kind: 'collection.rename_files',
    resourceType: 'collection',
    label: 'File Rename',
    invalidate: invalidateCollectionFiles,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      return fileRenameSuccessMessage(operation, collectionTitle)
    },
  },
  'collection.rewrite_metadata': {
    kind: 'collection.rewrite_metadata',
    resourceType: 'collection',
    label: 'Writing metadata into files',
    invalidate: invalidateCollectionFiles,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const retagged = resultNumber(operation, 'files_retagged') ?? 0
      const nfos = resultNumber(operation, 'nfos_written') ?? 0
      const failed = resultNumber(operation, 'files_failed') ?? 0
      if (retagged + nfos === 0 && failed === 0) return `No downloaded files of ${collectionTitle} needed new metadata`
      const parts = [
        retagged > 0 ? `updated the tags of ${retagged} ${plural(retagged, 'file', 'files')}` : '',
        nfos > 0 ? `wrote ${nfos} NFO ${plural(nfos, 'file', 'files')}` : '',
      ].filter(Boolean)
      const failedDetail = failed > 0 ? `; ${failed} ${plural(failed, 'file', 'files')} kept their old metadata` : ''
      return `Writing metadata into files finished for ${collectionTitle}: ${parts.join(' and ') || 'nothing changed'}${failedDetail}`
    },
  },
  'collection.change_identification': {
    kind: 'collection.change_identification',
    resourceType: 'collection',
    label: 'Episode identification change',
    invalidate: (operation, invalidations) => {
      invalidateCollectionStructure(operation, invalidations)
      invalidateCollectionFiles(operation, invalidations)
    },
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      return operation.result?.summary
        ? `${collectionTitle}: ${operation.result.summary}`
        : `${collectionTitle} numbers its episodes the new way`
    },
  },
  'collection.renumber': {
    kind: 'collection.renumber',
    resourceType: 'collection',
    label: 'Numbering again',
    invalidate: (operation, invalidations) => {
      invalidateCollectionStructure(operation, invalidations)
      invalidateCollectionFiles(operation, invalidations)
    },
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      return operation.result?.summary
        ? `${collectionTitle}: ${operation.result.summary}`
        : `${collectionTitle} has its moved episodes in place`
    },
  },
  'collection.remove_left_episodes': {
    kind: 'collection.remove_left_episodes',
    resourceType: 'collection',
    label: 'Removing what left',
    invalidate: (operation, invalidations) => {
      invalidateCollectionStructure(operation, invalidations)
      invalidateCollectionFiles(operation, invalidations)
    },
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      return operation.result?.summary ? `${collectionTitle}: ${operation.result.summary}` : `${collectionTitle} let go of what left it`
    },
  },
  'collection.scan_existing_files': {
    kind: 'collection.scan_existing_files',
    resourceType: 'collection',
    label: 'Existing files scan',
    invalidate: (operation, invalidations) => {
      const collectionSlug = contextString(operation, 'collection_slug')
      invalidations.push(
        ['existingFiles', collectionSlug],
        ['existingFilesScans', collectionSlug],
      )
    },
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      return `Existing files for ${collectionTitle} are ready to review`
    },
  },
  'local_media_profile.manage_custom_indexes': {
    kind: 'local_media_profile.manage_custom_indexes',
    resourceType: 'local_media_profile',
    label: 'Custom indexing',
    invalidate: invalidateLocalMediaProfileFiles,
    success: (operation) => {
      const profileName = contextString(operation, 'local_media_profile_name') || operation.title
      return `Custom indexing updated for ${profileName}`
    },
  },
  'local_media_profile.rename_files': {
    kind: 'local_media_profile.rename_files',
    resourceType: 'local_media_profile',
    label: 'File Rename',
    invalidate: invalidateLocalMediaProfileFiles,
    success: (operation) => {
      const profileName = contextString(operation, 'local_media_profile_name') || operation.title
      return fileRenameSuccessMessage(operation, profileName)
    },
  },
  'local_media_profile.move_episodes': {
    kind: 'local_media_profile.move_episodes',
    resourceType: 'local_media_profile',
    label: 'Move episodes',
    invalidate: (operation, invalidations) => {
      invalidateLocalMediaProfileFiles(operation, invalidations)
      invalidations.push(
        ['localMediaProfileMovePreview'],
        ['downloadProfilesView'],
        ['localMediaProfilesView'],
      )
    },
    success: (operation) => {
      const target = contextString(operation, 'target_local_media_profile_name') || 'the other profile'
      const moved = resultNumber(operation, 'episodes_moved') ?? 0
      const skipped = resultNumber(operation, 'episodes_skipped') ?? 0
      const stayed = skipped > 0 ? `; ${episodeCount(operation, skipped)} stayed` : ''
      return `Moved ${episodeCount(operation, moved)} to ${target}${stayed}`
    },
  },
  'local_media_profile.redownload_media': {
    kind: 'local_media_profile.redownload_media',
    resourceType: 'local_media_profile',
    label: 'Re-download media',
    invalidate: invalidateLocalMediaProfileFiles,
    success: (operation) => {
      const profileName = contextString(operation, 'local_media_profile_name') || operation.title
      const count = resultNumber(operation, 'downloads_completed')
        ?? resultNumber(operation, 'completed')
        ?? contextNumber(operation, 'downloads_requested')
        ?? 0
      return `Re-download finished for ${profileName}: ${count} ${plural(count, 'file', 'files')} re-downloaded`
    },
  },
  'local_media_profile.delete_downloads': {
    kind: 'local_media_profile.delete_downloads',
    resourceType: 'local_media_profile',
    label: 'Delete downloads',
    invalidate: invalidateLocalMediaProfileDownloadDeletion,
    success: (operation) => {
      const profileName = contextString(operation, 'local_media_profile_name') || operation.title
      const files = resultNumber(operation, 'files_deleted') ?? operation.progressTotal
      const disabledProfiles = contextNumber(operation, 'download_profiles_disabled') ?? 0
      const disabledDetail = disabledProfiles > 0
        ? `; ${disabledProfiles} ${plural(disabledProfiles, 'Download Profile', 'Download Profiles')} disabled`
        : ''
      return `Deleted downloads for ${profileName}: ${files} ${plural(files, 'file', 'files')} removed${disabledDetail}`
    },
  },
  'download_profile.delete_out_of_scope': {
    kind: 'download_profile.delete_out_of_scope',
    resourceType: 'download_profile',
    label: 'Delete downloads outside its filters',
    invalidate: invalidateDownloadProfileOutOfScope,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const deleted = resultNumber(operation, 'downloads_deleted') ?? operation.progressTotal
      return `Deleted ${deleted} ${plural(deleted, 'download', 'downloads')} outside the filters of ${collectionTitle}`
    },
  },
  'collection.delete_downloads': {
    kind: 'collection.delete_downloads',
    resourceType: 'collection',
    label: 'Bulk delete downloads',
    invalidate: invalidateCollectionDownloadDeletion,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const files = resultNumber(operation, 'episode_files')
        ?? resultNumber(operation, 'completed')
        ?? 0
      const profiles = resultNumber(operation, 'local_media_profiles')
        ?? contextNumber(operation, 'local_media_profiles_requested')
      const disabledProfiles = resultNumber(operation, 'download_profiles_disabled') ?? 0
      const profileDetail = profiles === undefined
        ? ''
        : ` using ${profiles} ${plural(profiles, 'Local Media Profile', 'Local Media Profiles')}`
      const disabledDetail = disabledProfiles > 0
        ? `; ${disabledProfiles} ${plural(disabledProfiles, 'Download Profile', 'Download Profiles')} disabled`
        : ''
      return `Deleted downloads for ${collectionTitle}: ${files} ${episodeWords(operation).singular} ${plural(files, 'file', 'files')} deleted${profileDetail}${disabledDetail}`
    },
  },
  'collection.download_all': {
    kind: 'collection.download_all',
    resourceType: 'collection',
    label: 'Bulk download',
    invalidate: invalidateCollectionFiles,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const completed = resultNumber(operation, 'downloads_completed')
        ?? resultNumber(operation, 'completed')
        ?? contextNumber(operation, 'downloads_requested')
        ?? 0
      return `Bulk download finished for ${collectionTitle}: ${episodeCount(operation, completed)} downloaded`
    },
  },
  'collection.redownload_episodes': {
    kind: 'collection.redownload_episodes',
    resourceType: 'collection',
    label: 'Bulk delete and re-download',
    invalidate: invalidateCollectionFiles,
    success: (operation) => {
      const collectionTitle = nameInText(contextString(operation, 'collection_title') || operation.title)
      const files = resultNumber(operation, 'episode_files')
        ?? resultNumber(operation, 'completed')
        ?? contextNumber(operation, 'downloads_requested')
        ?? 0
      const profiles = resultNumber(operation, 'local_media_profiles')
        ?? contextNumber(operation, 'local_media_profiles_requested')
      const profileDetail = profiles === undefined
        ? ''
        : ` using ${profiles} ${plural(profiles, 'Local Media Profile', 'Local Media Profiles')}`
      return `Bulk delete and re-download finished for ${collectionTitle}: ${files} ${episodeWords(operation).singular} ${plural(files, 'file', 'files')} re-downloaded${profileDetail}`
    },
  },
  'movie.refresh_extras': {
    kind: 'movie.refresh_extras',
    resourceType: 'movie',
    label: 'Movie extra refresh',
    invalidate: invalidateMovie,
  },
  'movie.delete_downloads': {
    kind: 'movie.delete_downloads',
    resourceType: 'movie',
    label: 'Delete downloads',
    invalidate: invalidateMovieFiles,
    success: (operation) => {
      const movieTitle = contextString(operation, 'movie_title') || operation.title
      const files = resultNumber(operation, 'files_deleted') ?? operation.progressTotal
      return `Deleted downloads for ${movieTitle}: ${files} ${plural(files, 'file', 'files')} removed`
    },
  },
  'movie.redownload_media': {
    kind: 'movie.redownload_media',
    resourceType: 'movie',
    label: 'Re-download media',
    invalidate: invalidateMovieFiles,
    success: (operation) => {
      const movieTitle = contextString(operation, 'movie_title') || operation.title
      const count = resultNumber(operation, 'downloads_completed')
        ?? resultNumber(operation, 'completed')
        ?? contextNumber(operation, 'downloads_requested')
        ?? 0
      return `Re-download finished for ${movieTitle}: ${count} ${plural(count, 'file', 'files')} re-downloaded`
    },
  },
  'media_download.bulk_retry': {
    kind: 'media_download.bulk_retry',
    resourceType: 'media_download',
    label: 'Retry downloads',
    invalidate: invalidateMediaDownloadCollection,
    success: (operation) => {
      const count = resultNumber(operation, 'downloads_completed')
        ?? resultNumber(operation, 'completed')
        ?? contextNumber(operation, 'downloads_requested')
        ?? 0
      return `Retry finished for ${count} ${plural(count, 'download', 'downloads')}`
    },
    canceled: (operation) => {
      const count = contextNumber(operation, 'downloads_requested') ?? 0
      return `Retry all canceled before all ${count} ${plural(count, 'download', 'downloads')} finished`
    },
    failed: (operation) => operation.error
      ? `Retry all failed: ${operation.error}`
      : 'Retry all failed',
  },
  'media_download.bulk_cancel': {
    kind: 'media_download.bulk_cancel',
    resourceType: 'media_download',
    label: 'Cancel downloads',
    invalidate: invalidateMediaDownloadCollection,
    success: (operation) => {
      const count = operation.progressTotal
      return `Canceled ${count} ${plural(count, 'download', 'downloads')}`
    },
    partial: (operation) => (
      `Canceled ${completedCount(operation)} of ${operation.progressTotal} downloads`
    ),
    canceled: (operation) => (
      `Cancel all stopped after ${completedCount(operation)} of ${operation.progressTotal} downloads`
    ),
  },
  'media_download.bulk_delete_unavailable': {
    kind: 'media_download.bulk_delete_unavailable',
    resourceType: 'media_download',
    label: 'Delete unavailable download records',
    invalidate: invalidateMediaDownloadCollection,
    success: (operation) => {
      const count = resultNumber(operation, 'downloads_deleted') ?? operation.progressTotal
      return `Deleted ${count} ${plural(count, 'download record', 'download records')}`
    },
    partial: (operation) => {
      const count = resultNumber(operation, 'downloads_deleted') ?? completedCount(operation)
      return `Deleted ${count} of ${operation.progressTotal} unavailable download records`
    },
    canceled: (operation) => {
      const count = resultNumber(operation, 'downloads_deleted') ?? completedCount(operation)
      return `Delete unavailable stopped after ${count} of ${operation.progressTotal} records`
    },
    failed: (operation) => operation.error
      ? `Delete unavailable failed: ${operation.error}`
      : 'Delete unavailable failed',
  },
  'media.download': {
    kind: 'media.download',
    resourceType: 'media_download',
    label: 'Download',
    invalidate: invalidateMediaDownload,
    success: (operation) => operation.result?.summary || `Downloaded ${nameInText(operation.title)}`,
    failed: (operation) => httpErrorMessage(operation.error)
      ?? `Download failed for ${nameInText(operation.title)}${operation.error ? `: ${operation.error}` : ''}`,
  },
  'quick.download': {
    kind: 'quick.download',
    resourceType: 'quick_download',
    label: 'Quick download',
    invalidate: invalidateQuickDownloads,
    success: (operation) => `${nameInText(operation.title)} is ready to download`,
    successAction: quickDownloadFile,
    canceled: (operation) => operation.message && operation.message !== 'Canceled by user'
      ? `Quick download of ${nameInText(operation.title)} stopped: ${operation.message}`
      : `Quick download of ${nameInText(operation.title)} was canceled`,
    failed: (operation) => operation.result?.summary
      ?? `Quick download failed for ${nameInText(operation.title)}${operation.error ? `: ${operation.error}` : ''}`,
  },
  'quick.delivered': {
    kind: 'quick.delivered',
    resourceType: 'quick_download',
    label: 'Quick download delivered',
    invalidate: invalidateQuickDownloads,
    success: (operation) => `${nameInText(operation.title)} was downloaded`,
    dismissesToast: quickDownloadDeliveredToast,
  },
} satisfies Readonly<Record<string, FrontendOperationDefinition>>

export const operationNotificationDefinitions: OperationNotificationDefinitions =
  frontendOperationDefinitions

function taskLedgerQueryMatchesOperation(
  queryKey: readonly unknown[],
  operation: TaskOperationRead,
): boolean {
  if (queryKey[0] !== 'taskLedger') return false

  const lazyCollection = queryKey[1] === 'list'
  const resourceType = lazyCollection ? queryKey[3] : queryKey[2]
  if (
    resourceType !== undefined
    && resourceType !== null
    && resourceType !== operation.resourceType
  ) {
    return false
  }

  const resourceFilter = lazyCollection ? queryKey[4] : queryKey[3]
  if (resourceFilter === undefined || resourceFilter === null || operation.resourceId == null) {
    return true
  }
  if (typeof resourceFilter === 'number') return resourceFilter === operation.resourceId
  return Array.isArray(resourceFilter) && resourceFilter.includes(operation.resourceId)
}

/**
 * Refresh what the finished operations changed, all in one go.
 *
 * Every matching query refetches once, however many of the operations touch it.
 * One invalidation per operation would refetch a shared query (the library, the
 * collections) once per operation, each time cancelling the fetch before it,
 * which the server still answers in full.
 */
export async function invalidateForOperations(
  queryClient: QueryClient,
  operations: readonly TaskOperationRead[],
) {
  if (operations.length === 0) return

  const keys: InvalidationCollector = []
  for (const operation of operations) {
    frontendOperationDefinitions[
      operation.kind as keyof typeof frontendOperationDefinitions
    ]?.invalidate?.(operation, keys)
  }

  await queryClient.invalidateQueries({
    predicate: ({queryKey}) => (
      keys.some((key) => partialMatchKey(queryKey, key))
      || operations.some((operation) => taskLedgerQueryMatchesOperation(queryKey, operation))
    ),
  })
}
