import {z} from 'zod'
import {createServerErrorMapper} from '../../utils/serverMessageMap'
import {ApiDateTimeSchema} from './datetime'


const CryptoFileSettingsSchema = z.object({
    secretKeyFile: z.string().nullable(),
    defaultSecretFile: z.string(),
})

const SessionSettingsSchema = z.object({
    ttlSeconds: z.number(),
})

const DailyWireAPISettingsSchema = z.object({
    middlewareApi: z.string(),
    streamApi: z.string(),
})

const MovieMetadataSettingsSchema = z.object({
    tmdbReadAccessToken: z.string(),
    tmdbReadAccessTokenConfigured: z.boolean(),
    tmdbApiBaseUrl: z.string(),
    language: z.string(),
    requestTimeoutSeconds: z.number(),
    maxRetries: z.number(),
})

const OAuthSettingsSchema = z.object({
    issuer: z.string(),
    audience: z.string(),
    clientId: z.string(),
    scope: z.string(),
})

const TimeoutSettingsSchema = z.object({
    minFastRequestMs: z.number(),
    maxFastRequests: z.number(),
    minSlowRequestMs: z.number(),
})

const SchedulerSettingsSchema = z.object({
    enabled: z.boolean(),
    maxWorkers: z.number(),
    stalledTaskTimeoutMinutes: z.number(),
    defaultMaxRetries: z.number(),
    retryBackoffSeconds: z.number(),
})

const TrackNewEpisodeScheduleSchema = z.object({
    findEpisodesCronEnabled: z.boolean(),
    findEpisodesCron: z.string(),
    quickCheckCronEnabled: z.boolean(),
    quickCheckCron: z.string(),
    fullRescanCronEnabled: z.boolean(),
    fullRescanCron: z.string(),
    monitorPendingEpisodeCronEnabled: z.boolean(),
    monitorPendingEpisodeCron: z.string(),
    monitorNoUsableMediaEpisodeCronEnabled: z.boolean(),
    monitorNoUsableMediaEpisodeCron: z.string(),
    metadataRefreshIntervals: z.string(),
})

const EpisodeStatusTimingSchema = z.object({
    publishedFinalAfterMinutes: z.number(),
    dwProcessingMaxMinutes: z.number(),
    noUsableMediaDeleteAfterMinutes: z.number(),
})

export const FilenameRestrictionModeSchema = z.enum(['unrestricted', 'windows', 'restricted'])
export type FilenameRestrictionMode = z.infer<typeof FilenameRestrictionModeSchema>
export const DownloadModeSchema = z.enum(['direct', 'temporary'])
export type DownloadMode = z.infer<typeof DownloadModeSchema>
export const ThumbnailModeSchema = z.enum(['no_thumbnail', 'embed', 'sidecar', 'embed_and_sidecar'])
export type ThumbnailMode = z.infer<typeof ThumbnailModeSchema>
export const MetadataModeSchema = z.enum(['no_metadata', 'embed', 'nfo', 'embed_and_nfo'])
export type MetadataMode = z.infer<typeof MetadataModeSchema>
export const ShowArtworkFallbackFormatSchema = z.enum(['jpg', 'png'])
export type ShowArtworkFallbackFormat = z.infer<typeof ShowArtworkFallbackFormatSchema>

const DownloadSettingsSchema = z.object({
    verifyDownloadsCronEnabled: z.boolean(),
    verifyDownloadsCron: z.string(),
    maxConcurrentDownloads: z.number(),
    maxDownloadAttempts: z.number(),
    episodeDownloadDelayMinutes: z.number(),
    ensureSafeDelay: z.boolean(),
    downloadTimeoutSeconds: z.number(),
    downloadRoot: z.string(),
    downloadMode: DownloadModeSchema,
    thumbnailMode: ThumbnailModeSchema,
    metadataMode: MetadataModeSchema,
    downloadShowAssets: z.boolean(),
    showArtworkFallbackFormat: ShowArtworkFallbackFormatSchema,
    temporaryDownloadRoot: z.string(),
    rssCacheRoot: z.string(),
    rssCacheRetentionSeconds: z.number(),
    filenameRestrictionMode: FilenameRestrictionModeSchema,
    remuxVideoToMp4: z.boolean(),
    ffmpegPath: z.string(),
})

export const FilesystemStorageKindSchema = z.enum(['local', 'remote', 'shared_or_virtual', 'unknown'])
export type FilesystemStorageKind = z.infer<typeof FilesystemStorageKindSchema>

const FilesystemInspectionSchema = z.object({
    path: z.string(),
    mountPoint: z.string().nullable(),
    filesystemType: z.string().nullable(),
    storageKind: FilesystemStorageKindSchema,
})

const DownloadStorageInspectionSchema = z.object({
    downloadRoot: FilesystemInspectionSchema,
    temporaryDownloadRoot: FilesystemInspectionSchema,
    sameFilesystem: z.boolean().nullable(),
})

const YouTubeApiSettingsSchema = z.object({
    dailyQuota: z.number(),
    checksQuota: z.number(),
    searchQuota: z.number(),
    minCheckIntervalMinutes: z.number(),
})

const FileWatcherSettingsSchema = z.object({
    enabled: z.boolean(),
    scanCronEnabled: z.boolean(),
    scanCron: z.string(),
    verifyFileSize: z.boolean(),
})

const QuickDownloadSettingsSchema = z.object({
    defaultKind: z.enum(['video', 'audio']),
    defaultQuality: z.enum(['best', '2160p', '1440p', '1080p', '720p', '480p']),
    defaultContainer: z.enum(['mp4', 'mkv']),
    defaultCodec: z.enum(['auto', 'h264', 'h265', 'vp9', 'av1']),
    defaultAudioFormat: z.enum(['m4a', 'mp3']),
    defaultMp3Bitrate: z.number(),
    embedMetadata: z.boolean(),
    embedArtwork: z.boolean(),
    keepDownloadedMinutes: z.number(),
    keepUnclaimedHours: z.number(),
    keepFreeGigabytes: z.number(),
})
export type QuickDownloadSettings = z.infer<typeof QuickDownloadSettingsSchema>

export const SettingsValuesSchema = z.object({
    logLevel: z.enum(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
    timezone: z.string(),
    crypto: CryptoFileSettingsSchema,
    loginSession: SessionSettingsSchema,
    dwApi: DailyWireAPISettingsSchema,
    movieMetadata: MovieMetadataSettingsSchema,
    dwOauth: OAuthSettingsSchema,
    dwTimeout: TimeoutSettingsSchema,
    scheduler: SchedulerSettingsSchema,
    newEpisodeSchedule: TrackNewEpisodeScheduleSchema,
    episodeStatusTiming: EpisodeStatusTimingSchema,
    downloadSettings: DownloadSettingsSchema,
    youtubeApi: YouTubeApiSettingsSchema,
    fileWatcher: FileWatcherSettingsSchema,
    quickDownload: QuickDownloadSettingsSchema,
})
export type SettingsValues = z.infer<typeof SettingsValuesSchema>

const requiredNumber = () => z.number({error: 'A value is required.'})
const cronExpression = z.string().refine((value) => {
    const fields = value.trim().split(/\s+/)
    return fields.length === 5 && fields.every((field) => field.length > 0 && !field.includes('_'))
}, 'Enter a complete five-part cron expression.')
const metadataRefreshIntervals = z.string().refine((value) => {
    const unitSeconds: Record<string, number> = {
        s: 1,
        m: 60,
        h: 60 * 60,
        d: 60 * 60 * 24,
    }
    const tokens = value.split(',').map((token) => token.trim().toLowerCase())
    if (tokens.length === 0 || tokens.some((token) => token.length === 0)) return false

    let previous = 0
    for (const token of tokens) {
        const match = /^([1-9]\d*)([smhd])$/.exec(token)
        if (!match) return false
        const seconds = Number(match[1]) * unitSeconds[match[2]]
        if (!Number.isFinite(seconds) || seconds <= previous) return false
        previous = seconds
    }
    return true
}, 'Use unique, increasing comma-separated offsets such as 5m,15m,30m,1h,3h,6h,24h.')

export const SettingsFormSchema = SettingsValuesSchema.extend({
    loginSession: SessionSettingsSchema.extend({
        ttlSeconds: requiredNumber().int().min(60, 'Must be at least 60 seconds.'),
    }),
    movieMetadata: MovieMetadataSettingsSchema.extend({
        requestTimeoutSeconds: requiredNumber().min(1, 'Must be at least 1 second.'),
        maxRetries: requiredNumber().int().min(0, 'Must be 0 or greater.').max(5, 'Must be 5 or less.'),
    }),
    dwTimeout: TimeoutSettingsSchema.extend({
        minFastRequestMs: requiredNumber().int().min(0, 'Must be 0 milliseconds or greater.'),
        maxFastRequests: requiredNumber().int().min(1, 'Must be at least 1.'),
        minSlowRequestMs: requiredNumber().int().min(0, 'Must be 0 milliseconds or greater.'),
    }),
    scheduler: SchedulerSettingsSchema.extend({
        maxWorkers: requiredNumber().int().min(1, 'Must be at least 1.'),
        stalledTaskTimeoutMinutes: requiredNumber().int().min(1, 'Must be at least 1 minute.'),
        defaultMaxRetries: requiredNumber().int().min(0, 'Must be 0 or greater.'),
        retryBackoffSeconds: requiredNumber().min(0, 'Must be 0 seconds or greater.'),
    }),
    newEpisodeSchedule: TrackNewEpisodeScheduleSchema.extend({
        findEpisodesCron: cronExpression,
        quickCheckCron: cronExpression,
        fullRescanCron: cronExpression,
        monitorPendingEpisodeCron: cronExpression,
        monitorNoUsableMediaEpisodeCron: cronExpression,
        metadataRefreshIntervals,
    }),
    episodeStatusTiming: EpisodeStatusTimingSchema.extend({
        publishedFinalAfterMinutes: requiredNumber().int().min(0, 'Must be 0 minutes or greater.'),
        dwProcessingMaxMinutes: requiredNumber().int().min(0, 'Must be 0 minutes or greater.'),
        noUsableMediaDeleteAfterMinutes: requiredNumber().int().min(0, 'Must be 0 minutes or greater.'),
    }),
    downloadSettings: DownloadSettingsSchema.extend({
        verifyDownloadsCron: cronExpression,
        maxConcurrentDownloads: requiredNumber().int().min(1, 'Must be at least 1.'),
        maxDownloadAttempts: requiredNumber().int().min(1, 'Must be at least 1.'),
        episodeDownloadDelayMinutes: requiredNumber().int().min(0, 'Must be 0 minutes or greater.'),
        downloadTimeoutSeconds: requiredNumber().int().min(1, 'Must be at least 1 second.'),
        downloadRoot: z.string().trim().min(1, 'A download root is required.'),
        temporaryDownloadRoot: z.string().trim().min(1, 'A temporary download folder is required.'),
        rssCacheRoot: z.string().trim().min(1, 'An RSS cache folder is required.'),
        rssCacheRetentionSeconds: requiredNumber().int().min(1, 'Must be at least 1 second.'),
    }),
    youtubeApi: YouTubeApiSettingsSchema.extend({
        dailyQuota: requiredNumber().int().min(1, 'Must be at least 1.'),
        checksQuota: requiredNumber().int().min(0, 'Must be 0 or greater.'),
        searchQuota: requiredNumber().int().min(0, 'Must be 0 or greater.'),
        minCheckIntervalMinutes: requiredNumber().int().min(10, 'Must be at least 10 minutes.'),
    }).refine(
        (value) => value.checksQuota + value.searchQuota <= value.dailyQuota,
        {message: 'Checks and search together cannot be more than the daily quota.', path: ['searchQuota']},
    ),
    fileWatcher: FileWatcherSettingsSchema.extend({
        scanCron: cronExpression,
    }),
    quickDownload: QuickDownloadSettingsSchema.extend({
        keepDownloadedMinutes: requiredNumber().int().min(0, 'Must be 0 minutes or greater.'),
        keepUnclaimedHours: requiredNumber().int().min(1, 'Must be at least 1 hour.'),
        keepFreeGigabytes: requiredNumber().min(0, 'Must be 0 GB or greater.'),
    }),
})

const WORKER_CRON_MINIMUM_MESSAGE = 'This worker runs more often than the configured slow-request delay. Increase this cron interval, or lower the minimum slow-request delay under Sources → Request pacing.'
const INVALID_CRON_MESSAGE = 'Enter a valid five-part cron expression.'

const CRON_SERVER_ERRORS = {
    cron_expression_invalid: INVALID_CRON_MESSAGE,
    worker_cron_interval_too_short: WORKER_CRON_MINIMUM_MESSAGE,
}

export const SettingsServerErrors = createServerErrorMapper({
    'values.newEpisodeSchedule.findEpisodesCron': CRON_SERVER_ERRORS,
    'values.newEpisodeSchedule.quickCheckCron': CRON_SERVER_ERRORS,
    'values.newEpisodeSchedule.fullRescanCron': CRON_SERVER_ERRORS,
    'values.newEpisodeSchedule.monitorPendingEpisodeCron': CRON_SERVER_ERRORS,
    'values.newEpisodeSchedule.monitorNoUsableMediaEpisodeCron': CRON_SERVER_ERRORS,
    'values.downloadSettings.verifyDownloadsCron': CRON_SERVER_ERRORS,
    'values.fileWatcher.scanCron': CRON_SERVER_ERRORS,
})

export const SETTINGS_FIELD_PATHS = [
    'logLevel',
    'timezone',
    'crypto.secretKeyFile',
    'crypto.defaultSecretFile',
    'loginSession.ttlSeconds',
    'dwApi.middlewareApi',
    'dwApi.streamApi',
    'movieMetadata.tmdbReadAccessToken',
    'movieMetadata.tmdbApiBaseUrl',
    'movieMetadata.language',
    'movieMetadata.requestTimeoutSeconds',
    'movieMetadata.maxRetries',
    'dwOauth.issuer',
    'dwOauth.audience',
    'dwOauth.clientId',
    'dwOauth.scope',
    'dwTimeout.minFastRequestMs',
    'dwTimeout.maxFastRequests',
    'dwTimeout.minSlowRequestMs',
    'scheduler.enabled',
    'scheduler.maxWorkers',
    'scheduler.stalledTaskTimeoutMinutes',
    'scheduler.defaultMaxRetries',
    'scheduler.retryBackoffSeconds',
    'newEpisodeSchedule.findEpisodesCronEnabled',
    'newEpisodeSchedule.findEpisodesCron',
    'newEpisodeSchedule.quickCheckCronEnabled',
    'newEpisodeSchedule.quickCheckCron',
    'newEpisodeSchedule.fullRescanCronEnabled',
    'newEpisodeSchedule.fullRescanCron',
    'newEpisodeSchedule.monitorPendingEpisodeCronEnabled',
    'newEpisodeSchedule.monitorPendingEpisodeCron',
    'newEpisodeSchedule.monitorNoUsableMediaEpisodeCronEnabled',
    'newEpisodeSchedule.monitorNoUsableMediaEpisodeCron',
    'newEpisodeSchedule.metadataRefreshIntervals',
    'episodeStatusTiming.publishedFinalAfterMinutes',
    'episodeStatusTiming.dwProcessingMaxMinutes',
    'episodeStatusTiming.noUsableMediaDeleteAfterMinutes',
    'downloadSettings.verifyDownloadsCronEnabled',
    'downloadSettings.verifyDownloadsCron',
    'downloadSettings.maxConcurrentDownloads',
    'downloadSettings.maxDownloadAttempts',
    'downloadSettings.episodeDownloadDelayMinutes',
    'downloadSettings.ensureSafeDelay',
    'downloadSettings.downloadTimeoutSeconds',
    'downloadSettings.downloadRoot',
    'downloadSettings.downloadMode',
    'downloadSettings.thumbnailMode',
    'downloadSettings.metadataMode',
    'downloadSettings.downloadShowAssets',
    'downloadSettings.showArtworkFallbackFormat',
    'downloadSettings.temporaryDownloadRoot',
    'downloadSettings.rssCacheRoot',
    'downloadSettings.rssCacheRetentionSeconds',
    'downloadSettings.filenameRestrictionMode',
    'downloadSettings.remuxVideoToMp4',
    'downloadSettings.ffmpegPath',
    'youtubeApi.dailyQuota',
    'youtubeApi.checksQuota',
    'youtubeApi.searchQuota',
    'youtubeApi.minCheckIntervalMinutes',
    'fileWatcher.enabled',
    'fileWatcher.scanCronEnabled',
    'fileWatcher.scanCron',
    'fileWatcher.verifyFileSize',
    'quickDownload.defaultKind',
    'quickDownload.defaultQuality',
    'quickDownload.defaultContainer',
    'quickDownload.defaultCodec',
    'quickDownload.defaultAudioFormat',
    'quickDownload.defaultMp3Bitrate',
    'quickDownload.embedMetadata',
    'quickDownload.embedArtwork',
    'quickDownload.keepDownloadedMinutes',
    'quickDownload.keepUnclaimedHours',
    'quickDownload.keepFreeGigabytes',
] as const

export const SettingsFieldPathSchema = z.enum(SETTINGS_FIELD_PATHS)
export type SettingsFieldPath = z.infer<typeof SettingsFieldPathSchema>

export const SettingsUpdateSchema = z.object({
    values: SettingsValuesSchema,
    changedFields: z.array(SettingsFieldPathSchema).min(1),
})
export type SettingsUpdate = z.infer<typeof SettingsUpdateSchema>

export const SettingsValidationIssueSchema = z.object({
    field: SettingsFieldPathSchema,
    code: z.enum(['cron_expression_invalid', 'worker_cron_interval_too_short']),
    message: z.string(),
    source: z.string(),
})
export type SettingsValidationIssue = z.infer<typeof SettingsValidationIssueSchema>

export const SettingsReadSchema = z.object({
    values: SettingsValuesSchema,
    configuredFields: z.array(SettingsFieldPathSchema),
    environmentOverrides: z.record(z.string(), z.string()),
    downloadStorage: DownloadStorageInspectionSchema,
    validationIssues: z.array(SettingsValidationIssueSchema),
    updatedAt: ApiDateTimeSchema.nullable(),
})
export type SettingsRead = z.infer<typeof SettingsReadSchema>
