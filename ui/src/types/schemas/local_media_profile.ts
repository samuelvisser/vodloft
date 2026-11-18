import {z} from 'zod'

import {createServerErrorMapper} from '../../utils/serverMessageMap'
import {
    CollectionLocalMediaProfileCreateSchema,
    CollectionLocalMediaProfileReadSchema,
    CollectionLocalMediaProfileUpdateSchema,
} from './collection_local_media_profile'
import {
    VideoLocalMediaProfileCreateSchema,
    VideoLocalMediaProfileReadSchema,
    VideoLocalMediaProfileUpdateSchema,
} from './video_local_media_profile'

export * from './local_media_profile_base'
export * from './collection_local_media_profile'
export * from './video_local_media_profile'


export const LocalMediaProfileServerErrors = createServerErrorMapper({
    name: {unique_violation: 'Name is already taken.'},
    slug: {unique_violation: 'Name is already taken.'},
})


const DATE_OUTPUT_TEMPLATE_FIELDS = [
    'date', 'time', 'datetime', 'year', 'month', 'day', 'hour', 'minute', 'second', 'day_of_year', 'day_of_year_reversed',
] as const

export const COLLECTION_OUTPUT_TEMPLATE_FIELDS = [
    'collection', 'collection_title', 'season', 'season_name', 'season_index', 'season_type', 'season_number',
    'episode', 'episode_title', 'title', 'dw_episode_number', 'episode_type', 'episode_extra_type',
    'episode_number', 'episode_sub_number', 'episode_label', 'episode_identifier', 'episode_published_date',
    'episode_published_time', 'episode_published_datetime', 'episode_index',
    'collection_author', 'collection_site_id', 'episode_site_id', 'episode_uploader', 'duration_seconds',
    'channel_title', 'channel_handle', 'channel_kind', 'section_title', 'section_kind',
    'artist', 'album', 'track_number', 'track_number_padded',
    ...DATE_OUTPUT_TEMPLATE_FIELDS,
] as const

// A Video profile keeps single videos, and movies with their extras. The movie_ values are empty for a single video.
export const VIDEO_OUTPUT_TEMPLATE_FIELDS = [
    'movie_slug', 'movie_title', 'movie_extended_title', 'movie_author',
    'movie_mature_rating', 'movie_duration_seconds',
    'movie_date', 'movie_time', 'movie_datetime', 'movie_year', 'movie_month', 'movie_day',
    'movie_hour', 'movie_minute', 'movie_second', 'movie_day_of_year', 'movie_day_of_year_reversed',
    'slug', 'title', 'extended_title', 'author', 'mature_rating', 'rating',
    'duration_seconds', 'media_type', 'source',
    ...DATE_OUTPUT_TEMPLATE_FIELDS,
] as const


// ---------- Strict request (create/update) ----------
export const LocalMediaProfileCreateSchema = z.discriminatedUnion('type', [
    CollectionLocalMediaProfileCreateSchema,
    VideoLocalMediaProfileCreateSchema,
])
export type LocalMediaProfileCreateIn = z.input<typeof LocalMediaProfileCreateSchema>
export type LocalMediaProfileCreateOut = z.output<typeof LocalMediaProfileCreateSchema>

export const LocalMediaProfileUpdateSchema = z.discriminatedUnion('type', [
    CollectionLocalMediaProfileUpdateSchema,
    VideoLocalMediaProfileUpdateSchema,
])
export type LocalMediaProfileUpdateIn = z.input<typeof LocalMediaProfileUpdateSchema>
export type LocalMediaProfileUpdateOut = z.output<typeof LocalMediaProfileUpdateSchema>


// ------------ Lenient response (read) ------------
export const LocalMediaProfileReadSchema = z.discriminatedUnion('type', [
    CollectionLocalMediaProfileReadSchema,
    VideoLocalMediaProfileReadSchema,
])
export type LocalMediaProfileRead = z.infer<typeof LocalMediaProfileReadSchema>


export const LocalMediaProfileStatisticsReadSchema = z.object({
    managedMediaCount: z.int().nonnegative(),
    downloadedMediaCount: z.int().nonnegative(),
    storageSizeBytes: z.number().int().nonnegative(),
    downloadProfileCount: z.int().nonnegative(),
})
export type LocalMediaProfileStatisticsRead = z.infer<typeof LocalMediaProfileStatisticsReadSchema>

export const LocalMediaProfilesStorageReadSchema = z.object({
    storageSizeBytes: z.number().int().nonnegative(),
})
export type LocalMediaProfilesStorageRead = z.infer<typeof LocalMediaProfilesStorageReadSchema>

export const LocalMediaProfileViewReadSchema = z.object({
    profile: LocalMediaProfileReadSchema,
    statistics: LocalMediaProfileStatisticsReadSchema,
})
export type LocalMediaProfileViewRead = z.infer<typeof LocalMediaProfileViewReadSchema>
