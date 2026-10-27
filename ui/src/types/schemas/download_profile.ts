import type {EpisodeTagRead} from "./source";
import {z} from 'zod'
import {EpisodeIdentifierReg, EpisodeIdentifierValue} from "../show";
import {ApiDateTimeSchema} from "./datetime";
import {SeasonDetachedSchema, SeasonReadSchema} from "./season";


// ---------- Strict request (create/update) ----------
// The season fields only apply to a show identified by season, the other
// filters apply to every show.
export const DownloadProfileSchemaRequest = z.object({
    enableProfile: z.boolean().default(true),
    epIdTypeList: z.array(z.string()).default([]),
    downloadWithCountdown: z.boolean().default(false),
    redownloadFinal: z.boolean().default(true),
    downloadDaysInPast: z.int().min(0).default(0),
    downloadEpisodeCount: z.int().min(0).default(0),
    downloadStartingFrom: z.iso.date().nullable().default(null),
    deleteOlderEpisodes: z.boolean().default(true),
    seasons: z.array(SeasonDetachedSchema).default([]),
    includeUpcomingSeasons: z.boolean().default(true),
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

/** A seasonal show needs a season to download; other shows ignore the season fields. */
export function forEpisodeIdentifier<Schema extends z.ZodType<SeasonFields>>(
    schema: Schema,
    episodeIdentifier: EpisodeIdentifierValue | string | undefined,
): Schema {
    return episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
        ? schema.superRefine(refineSeasonChoice) as Schema
        : schema
}

/** Starting values that fit how a show identifies its episodes and the tags its Source gives them. */
export function downloadProfileDefaultsFor(
    episodeIdentifier: EpisodeIdentifierValue | string | undefined,
    tags: readonly EpisodeTagRead[] | undefined,
) {
    // A seasonal show downloads the chosen seasons whole, without its bonus content;
    // other shows a recent window.
    const seasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
    const epIdTypeList = (tags ?? [])
        .filter((tag) => tag.selectedByDefault && (!seasonal || tag.rssEpisodeType === 'full'))
        .map((tag) => tag.key)
    return {epIdTypeList: epIdTypeList.length ? epIdTypeList : ['ep'], downloadDaysInPast: seasonal ? 0 : 180}
}

export const DownloadProfileCreateSchema = DownloadProfileSchemaRequest.extend({
    showId: z.int(),
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
    showId: z.int(),
    localMediaProfileId: z.int(),
    enableProfile: z.boolean(),
    epIdTypeList: z.array(z.string()),
    downloadWithCountdown: z.boolean(),
    redownloadFinal: z.boolean(),
    downloadDaysInPast: z.int(),
    downloadEpisodeCount: z.int(),
    downloadStartingFrom: z.iso.date().nullable(),
    deleteOlderEpisodes: z.boolean(),
    seasons: z.array(SeasonReadSchema),
    includeUpcomingSeasons: z.boolean(),
    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
export type DownloadProfileRead = z.infer<typeof DownloadProfileReadSchema>
