import type {EpisodeTagRead} from "./source";
import {z} from 'zod'
import {EpisodeIdentifierReg, EpisodeIdentifierValue} from "../collection";
import {ApiDateTimeSchema} from "./datetime";
import {createSelectRegistry} from "../../utils/selectRegistry";
import {DEFAULT_SPONSORBLOCK_SEGMENTS} from '../sponsorblock'
import {DATE_FIELDS, isDateLine, joinIgnoreCase, splitIgnoreCase} from '../../components/DownloadProfile/episodeFilters'


// ---------- Which episodes: one ordered list of filters ----------
export const EpisodeFilterActionReg = createSelectRegistry('EpisodeFilterAction', {
    skip: {label: 'Skip'},
    only: {label: 'Only download'},
    keep: {label: 'Keep'},
})
export type EpisodeFilterAction = (typeof EpisodeFilterActionReg)['values'][number]

export const EpisodeFilterFieldReg = createSelectRegistry('EpisodeFilterField', {
    title: {label: 'title'},
    description: {label: 'description'},
    duration: {label: 'duration'},
    types: {label: 'episode type'},
    seasons: {label: 'season'},
    published: {label: 'published'},
    downloaded: {label: 'downloaded'},
})
export type EpisodeFilterField = (typeof EpisodeFilterFieldReg)['values'][number]

export const DurationOperatorReg = createSelectRegistry('DurationOperator', {
    shorter: {label: 'is shorter than'},
    longer: {label: 'is longer than'},
})
export type DurationOperator = (typeof DurationOperatorReg)['values'][number]

export const EpisodeFilterSchema = z.object({
    action: z.enum(EpisodeFilterActionReg.values).default('only'),
    field: z.enum(EpisodeFilterFieldReg.values).default('title'),
    /** A title or description filter's regular expression; a leading (?i) ignores case. */
    pattern: z.string().nullable().default(null),
    durationOperator: z.enum(DurationOperatorReg.values).nullable().default(null),
    durationSeconds: z.int().min(1).nullable().default(null),
    episodeTypes: z.array(z.string()).nullable().default(null),
    seasonSlugs: z.array(z.string()).nullable().default(null),
    includeUpcoming: z.boolean().default(false),
    days: z.int('Enter a number of days').min(1, 'Use at least 1 day').nullable().default(null),
    count: z.int('Enter a number of episodes').min(1, 'Use at least 1 episode').nullable().default(null),
    startingFrom: z.iso.date().nullable().default(null),
}).superRefine((filter, ctx) => {
    if (isDateLine(filter)) {
        if (filter.action === 'skip') ctx.addIssue({code: 'custom', path: ['action'], message: 'A date line can only download or keep episodes'})
        if (filter.field === 'downloaded') {
            if (!filter.days) ctx.addIssue({code: 'custom', path: ['days'], message: 'Choose a number of days'})
        } else if ([filter.days, filter.count, filter.startingFrom].filter((value) => value !== null).length !== 1) {
            ctx.addIssue({code: 'custom', path: ['days'], message: 'Choose a number of days, a number of episodes or a date'})
        }
    } else if (filter.field === 'types') {
        if (!filter.episodeTypes?.length) ctx.addIssue({code: 'custom', path: ['episodeTypes'], message: 'Choose at least one episode type'})
    } else if (filter.field === 'seasons') {
        if (!filter.seasonSlugs?.length && !filter.includeUpcoming) {
            ctx.addIssue({code: 'custom', path: ['seasonSlugs'], message: 'Choose at least one season, or upcoming seasons'})
        }
    } else if (filter.field === 'duration') {
        if (!filter.durationOperator || !filter.durationSeconds) {
            ctx.addIssue({code: 'custom', path: ['durationSeconds'], message: 'Choose a duration'})
        }
    } else if (!splitIgnoreCase(filter.pattern).pattern) {
        ctx.addIssue({code: 'custom', path: ['pattern'], message: 'Type what to look for'})
    }
})
export type EpisodeFilterIn = z.input<typeof EpisodeFilterSchema>
export type EpisodeFilter = z.output<typeof EpisodeFilterSchema>

const EMPTY_FILTER: Omit<EpisodeFilter, 'action' | 'field'> = {
    pattern: null, durationOperator: null, durationSeconds: null, episodeTypes: null,
    seasonSlugs: null, includeUpcoming: false, days: null, count: null, startingFrom: null,
}

/** A new filter of a field, with the values its editor starts from. A date line cannot skip. */
export function newEpisodeFilter(field: EpisodeFilterField = 'title', action: EpisodeFilterAction = 'only'): EpisodeFilter {
    const filter: EpisodeFilter = {...EMPTY_FILTER, action: isDateLine({field}) && action === 'skip' ? 'only' : action, field}
    if (field === 'title' || field === 'description') return {...filter, pattern: joinIgnoreCase({pattern: '', ignoreCase: true})}
    if (field === 'duration') return {...filter, durationOperator: 'shorter', durationSeconds: 120}
    if (field === 'types') return {...filter, episodeTypes: []}
    if (field === 'seasons') return {...filter, seasonSlugs: []}
    if (field === 'published') return {...filter, count: 25}
    if (field === 'downloaded') return {...filter, days: 180}
    return filter
}

/** The episode types a new profile starts with: the Source's defaults, without bonus content for a seasonal collection. */
export function defaultEpisodeTypes(
    episodeIdentifier: EpisodeIdentifierValue | string | undefined,
    tags: readonly EpisodeTagRead[] | undefined,
): string[] {
    const seasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
    const types = (tags ?? [])
        .filter((tag) => tag.selectedByDefault && (!seasonal || tag.rssEpisodeType === 'full'))
        .map((tag) => tag.key)
    return types.length ? types : ['ep']
}

/**
 * The filters a new profile starts with: for a seasonal collection its latest season and the
 * upcoming ones, then the Source's default episode types, then the latest 25 episodes.
 */
export function defaultEpisodeFilters(
    episodeIdentifier: EpisodeIdentifierValue | string | undefined,
    tags: readonly EpisodeTagRead[] | undefined,
    latestSeasonSlug?: string,
): EpisodeFilter[] {
    const filters: EpisodeFilter[] = []
    if (episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal) {
        filters.push({...newEpisodeFilter('seasons'), seasonSlugs: latestSeasonSlug ? [latestSeasonSlug] : [], includeUpcoming: true})
    }
    filters.push({...newEpisodeFilter('types'), episodeTypes: defaultEpisodeTypes(episodeIdentifier, tags)})
    filters.push(newEpisodeFilter('published'))
    return filters
}

function refineOneLinePerDate(filters: readonly {field: string}[], ctx: z.RefinementCtx) {
    for (const field of DATE_FIELDS) {
        if (filters.filter((filter) => filter.field === field).length > 1) {
            ctx.addIssue({code: 'custom', message: `Use one ${field} line at most`})
        }
    }
}


// ---------- Strict request (create/update) ----------
export const DownloadProfileSchemaRequest = z.object({
    enableProfile: z.boolean().default(true),
    downloadWithCountdown: z.boolean().default(false),
    redownloadFinal: z.boolean().default(true),
    /** Whether an Only date line deletes the downloads it leaves out. */
    deleteOlderEpisodes: z.boolean().default(true),
    autoSubtitles: z.enum(['never', 'fallback', 'always']).default('fallback'),
    sponsorblockEnabled: z.boolean().default(true),
    sponsorblockSegments: z.record(z.string(), z.enum(['keep', 'chapter', 'cut'])).default(() => ({...DEFAULT_SPONSORBLOCK_SEGMENTS})),
    upgradeCheck: z.boolean().default(true),
    upgradeAfterDays: z.int('Enter a number of days').min(1, 'Check after at least 1 day').max(365, 'Check within a year').default(7),
    upgradeRepeat: z.enum(['once', 'twice', 'every']).default('once'),
    upgradeImprovements: z.array(z.enum(['resolution', 'sponsorblock', 'subtitles', 'codec'])).default(() => ['resolution' as const, 'sponsorblock' as const]),
    filters: z.array(EpisodeFilterSchema).max(50).superRefine(refineOneLinePerDate).default([]),
})

export const DownloadProfileCreateSchema = DownloadProfileSchemaRequest.extend({
    collectionId: z.int(),
    localMediaProfileId: z.int(),
})
export type DownloadProfileCreateIn = z.input<typeof DownloadProfileCreateSchema>
export type DownloadProfileCreateOut = z.output<typeof DownloadProfileCreateSchema>

export const DownloadProfileUpdateSchema = DownloadProfileSchemaRequest.extend({
    localMediaProfileId: z.int(),
})
export type DownloadProfileUpdateIn = z.input<typeof DownloadProfileUpdateSchema>
export type DownloadProfileUpdateOut = z.output<typeof DownloadProfileUpdateSchema>


// ------------ Lenient response (read) ------------
export const DownloadProfileReadSchema = z.looseObject({
    id: z.int(),
    collectionId: z.int(),
    localMediaProfileId: z.int(),
    enableProfile: z.boolean(),
    downloadWithCountdown: z.boolean(),
    redownloadFinal: z.boolean(),
    deleteOlderEpisodes: z.boolean(),
    autoSubtitles: z.string().default('fallback'),
    sponsorblockEnabled: z.boolean().default(false),
    sponsorblockSegments: z.record(z.string(), z.enum(['keep', 'chapter', 'cut'])).default(() => ({...DEFAULT_SPONSORBLOCK_SEGMENTS})),
    upgradeCheck: z.boolean(),
    upgradeAfterDays: z.int(),
    upgradeRepeat: z.enum(['once', 'twice', 'every']),
    upgradeImprovements: z.array(z.enum(['resolution', 'sponsorblock', 'subtitles', 'codec'])),
    filters: z.array(z.looseObject({
        id: z.int(),
        action: z.enum(EpisodeFilterActionReg.values),
        field: z.enum(EpisodeFilterFieldReg.values),
        pattern: z.string().nullable(),
        durationOperator: z.enum(DurationOperatorReg.values).nullable(),
        durationSeconds: z.int().nullable(),
        episodeTypes: z.array(z.string()).nullable(),
        seasonSlugs: z.array(z.string()).nullable(),
        includeUpcoming: z.boolean(),
        days: z.int().nullable(),
        count: z.int().nullable(),
        startingFrom: z.iso.date().nullable(),
    })),
    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
export type DownloadProfileRead = z.infer<typeof DownloadProfileReadSchema>


// ------------ Which episodes counts ------------
export const WhichEpisodesSchema = z.object({
    total: z.int(),
    unavailable: z.int(),
    /** How many episodes each filter sent leaves out, in the order they were sent. */
    filters: z.array(z.int()),
    downloaded: z.int(),
    episodes: z.array(z.object({
        id: z.int(),
        slug: z.string(),
        title: z.string(),
        publishedAt: z.string().nullable(),
        leftOutBy: z.string().nullable(),
    })).nullable().optional(),
})
export type WhichEpisodes = z.infer<typeof WhichEpisodesSchema>

export const SkippedByFilterSchema = z.object({
    episodeId: z.int(),
    downloadProfileId: z.int(),
    localMediaProfileId: z.int(),
    filter: EpisodeFilterSchema,
})
export type SkippedByFilter = z.infer<typeof SkippedByFilterSchema>

export const AutoSubtitlesUseSchema = z.object({
    downloadProfileId: z.number(),
    collectionId: z.number(),
    collectionTitle: z.string(),
    autoSubtitles: z.string(),
})
export type AutoSubtitlesUse = z.infer<typeof AutoSubtitlesUseSchema>

export const SiteOptionsSchema = z.object({
    siteName: z.string(),
    autoSubtitles: z.boolean(),
    sponsorblock: z.boolean(),
    upgradeChecks: z.boolean(),
    /**
     * How RSS feeds can stream the collection's episodes without downloading them: as M4A and MP4 files,
     * as HLS video, and while they are live. Empty for downloads only.
     */
    streamMethods: z.array(z.enum(['file', 'hls', 'live'])),
})
