import type {EpisodeTagRead} from "./source";
import {z} from 'zod'
import {EpisodeIdentifierReg, EpisodeIdentifierValue} from "../collection";
import {ApiDateTimeSchema} from "./datetime";
import {SeasonDetachedSchema, SeasonReadSchema} from "./season";
import {createSelectRegistry} from "../../utils/selectRegistry";
import {DEFAULT_SPONSORBLOCK_SEGMENTS} from '../sponsorblock'


// ---------- Which episodes: your own rules ----------
export const EpisodeRuleActionReg = createSelectRegistry('EpisodeRuleAction', {
    skip: {label: 'Skip'},
    only: {label: 'Only download'},
    keep: {label: 'Keep'},
})
export type EpisodeRuleAction = (typeof EpisodeRuleActionReg)['values'][number]

export const EpisodeRuleFieldReg = createSelectRegistry('EpisodeRuleField', {
    title: {label: 'title'},
    description: {label: 'description'},
    duration: {label: 'duration'},
})
export type EpisodeRuleField = (typeof EpisodeRuleFieldReg)['values'][number]

export const DurationOperatorReg = createSelectRegistry('DurationOperator', {
    shorter: {label: 'is shorter than'},
    longer: {label: 'is longer than'},
})
export type DurationOperator = (typeof DurationOperatorReg)['values'][number]

export const EpisodeRuleSchema = z.object({
    action: z.enum(['skip', 'only', 'keep']).default('only'),
    field: z.enum(['title', 'description', 'duration']).default('title'),
    pattern: z.string().nullable().default(null),
    ignoreCase: z.boolean().default(false),
    durationOperator: z.enum(['shorter', 'longer']).nullable().default(null),
    durationSeconds: z.int().min(1).nullable().default(null),
}).superRefine((rule, ctx) => {
    if (rule.field === 'duration') {
        if (!rule.durationOperator || !rule.durationSeconds) {
            ctx.addIssue({code: 'custom', path: ['durationSeconds'], message: 'Choose a duration'})
        }
    } else if (!rule.pattern) {
        ctx.addIssue({code: 'custom', path: ['pattern'], message: 'Type what to look for'})
    }
})
export type EpisodeRuleIn = z.input<typeof EpisodeRuleSchema>
export type EpisodeRule = z.output<typeof EpisodeRuleSchema>

/** A new filter line: skip titles containing a whole word, in any capitalisation. */
export function newEpisodeRule(): EpisodeRule {
    return {action: 'only', field: 'title', pattern: '', ignoreCase: true, durationOperator: null, durationSeconds: null}
}


// ---------- Strict request (create/update) ----------
// The season fields only apply to a collection identified by season, the other
// filters apply to every collection.
export const DownloadProfileSchemaRequest = z.object({
    enableProfile: z.boolean().default(true),
    epIdTypeList: z.array(z.string()).default([]),
    downloadWithCountdown: z.boolean().default(false),
    redownloadFinal: z.boolean().default(true),
    downloadDaysInPast: z.int().min(0).default(0),
    downloadEpisodeCount: z.int().min(0).default(0),
    downloadStartingFrom: z.iso.date().nullable().default(null),
    deleteOlderEpisodes: z.boolean().default(true),
    retentionFrom: z.enum(['published', 'downloaded']).default('published'),
    autoSubtitles: z.enum(['never', 'fallback', 'always']).default('fallback'),
    sponsorblockEnabled: z.boolean().default(true),
    sponsorblockSegments: z.record(z.string(), z.enum(['keep', 'chapter', 'cut'])).default(() => ({...DEFAULT_SPONSORBLOCK_SEGMENTS})),
    seasons: z.array(SeasonDetachedSchema).default([]),
    includeUpcomingSeasons: z.boolean().default(true),
    rules: z.array(EpisodeRuleSchema).default([]),
})

type DownloadLimitFields = {
    downloadDaysInPast: number
    downloadEpisodeCount: number
    downloadStartingFrom: string | null
}

export function refineDownloadLimit(value: DownloadLimitFields, ctx: z.RefinementCtx) {
    if (value.downloadDaysInPast > 0 && value.downloadEpisodeCount > 0) {
        ctx.addIssue({
            code: 'custom',
            path: ['downloadDaysInPast'],
            message: 'Choose either a date limit or an episode-count limit, not both',
        })
    }
    if (value.downloadStartingFrom !== null && (value.downloadDaysInPast > 0 || value.downloadEpisodeCount > 0)) {
        ctx.addIssue({
            code: 'custom',
            path: ['downloadStartingFrom'],
            message: 'Download starting from can only be used when Limit by is set to No limits',
        })
    }
}

type SeasonFields = {
    seasons: readonly unknown[]
    includeUpcomingSeasons: boolean
}

function refineSeasonChoice(value: SeasonFields, ctx: z.RefinementCtx) {
    if (!value.includeUpcomingSeasons && value.seasons.length === 0) {
        ctx.addIssue({
            code: 'custom',
            path: ['seasons'],
            message: 'Choose at least one season or enable "Include upcoming seasons".',
        })
    }
}

/** A seasonal collection needs a season to download; other collections ignore the season fields. */
export function forEpisodeIdentifier<Schema extends z.ZodType<SeasonFields>>(
    schema: Schema,
    episodeIdentifier: EpisodeIdentifierValue | string | undefined,
): Schema {
    return episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
        ? schema.superRefine(refineSeasonChoice) as Schema
        : schema
}

/** Starting values that fit how a collection identifies its episodes and the tags its Source gives them. */
export function downloadProfileDefaultsFor(
    episodeIdentifier: EpisodeIdentifierValue | string | undefined,
    tags: readonly EpisodeTagRead[] | undefined,
) {
    // A seasonal collection downloads the chosen seasons whole, without its bonus content;
    // other collections a recent window.
    const seasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
    const epIdTypeList = (tags ?? [])
        .filter((tag) => tag.selectedByDefault && (!seasonal || tag.rssEpisodeType === 'full'))
        .map((tag) => tag.key)
    return {epIdTypeList: epIdTypeList.length ? epIdTypeList : ['ep'], downloadDaysInPast: seasonal ? 0 : 180}
}

export const DownloadProfileCreateSchema = DownloadProfileSchemaRequest.extend({
    collectionId: z.int(),
    localMediaProfileId: z.int(),
}).superRefine(refineDownloadLimit)
export type DownloadProfileCreateIn = z.input<typeof DownloadProfileCreateSchema>
export type DownloadProfileCreateOut = z.output<typeof DownloadProfileCreateSchema>

export const DownloadProfileUpdateSchema = DownloadProfileSchemaRequest.extend({
    localMediaProfileId: z.int(),
}).superRefine(refineDownloadLimit)
export type DownloadProfileUpdateIn = z.input<typeof DownloadProfileUpdateSchema>
export type DownloadProfileUpdateOut = z.output<typeof DownloadProfileUpdateSchema>


// ------------ Lenient response (read) ------------
export const DownloadProfileReadSchema = z.looseObject({
    id: z.int(),
    collectionId: z.int(),
    localMediaProfileId: z.int(),
    enableProfile: z.boolean(),
    epIdTypeList: z.array(z.string()),
    downloadWithCountdown: z.boolean(),
    redownloadFinal: z.boolean(),
    downloadDaysInPast: z.int(),
    downloadEpisodeCount: z.int(),
    downloadStartingFrom: z.iso.date().nullable(),
    deleteOlderEpisodes: z.boolean(),
    retentionFrom: z.string(),
    autoSubtitles: z.string().default('fallback'),
    sponsorblockEnabled: z.boolean().default(false),
    sponsorblockSegments: z.record(z.string(), z.enum(['keep', 'chapter', 'cut'])).default(() => ({...DEFAULT_SPONSORBLOCK_SEGMENTS})),
    seasons: z.array(SeasonReadSchema),
    includeUpcomingSeasons: z.boolean(),
    rules: z.array(z.looseObject({
        id: z.int(),
        action: z.string(),
        field: z.string(),
        pattern: z.string().nullable(),
        ignoreCase: z.boolean(),
        durationOperator: z.string().nullable(),
        durationSeconds: z.int().nullable(),
    })),
    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
export type DownloadProfileRead = z.infer<typeof DownloadProfileReadSchema>


// ------------ Which episodes counts ------------
export const WhichEpisodesSchema = z.object({
    total: z.int(),
    unavailable: z.int(),
    types: z.int(),
    seasons: z.int(),
    dates: z.int(),
    rules: z.array(z.int()),
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
    rule: EpisodeRuleSchema,
})
export type SkippedByFilter = z.infer<typeof SkippedByFilterSchema>

export const AutoSubtitlesUseSchema = z.object({
    downloadProfileId: z.number(),
    collectionId: z.number(),
    collectionTitle: z.string(),
    episodeTypes: z.array(z.string()),
    autoSubtitles: z.string(),
})
export type AutoSubtitlesUse = z.infer<typeof AutoSubtitlesUseSchema>

export const SiteOptionsSchema = z.object({autoSubtitles: z.boolean(), sponsorblock: z.boolean()})
