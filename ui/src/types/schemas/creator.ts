import {CollectionWordsSchema} from './collection_contract'
import {z} from 'zod'
import {ApiDateTimeSchema} from './datetime'
import {EpisodeReadViewSchema} from './episode'
import {NamesSchema, SiteReadSchema} from './source'

/** A creator's account on one Site, such as their YouTube channel. */
export const CreatorAccountReadSchema = z.object({
    id: z.number(),
    sourceKey: z.string(),
    site: SiteReadSchema,
    siteRef: z.string(),
    url: z.string().nullable(),
    handle: z.string().nullable(),
    /** The account's own picture on its Site. */
    avatarUrl: z.string().nullable().default(null),
    /** The account's Site has more of the creator's work than their channel, such as a Daily Wire host's shows and
     *  movies, which the creator's page offers to add. */
    offers: z.boolean().default(false),
})
export type CreatorAccountRead = z.infer<typeof CreatorAccountReadSchema>

export const CreatorReadSchema = z.object({
    id: z.number(),
    slug: z.string(),
    /** The word of their one Site, such as host, or artist for a music artist. */
    creatorNames: NamesSchema,
    /** A music artist: they have a Music collection. */
    music: z.boolean(),
    /** The label with their Site, when they are on one only, such as "The Daily Wire host". */
    kind: z.string(),
    accounts: z.array(CreatorAccountReadSchema),
    title: z.string(),
    description: z.string().nullable(),
    avatarUrl: z.string().nullable(),
    bannerUrl: z.string().nullable(),
    links: z.array(z.string()),
    facts: z.array(z.string()),
    createdAt: z.string(),
    collectionCount: z.number(),
    episodeCount: z.number(),
    /** How often its page and its collections' pages were opened, for the Library's Often used order. */
    openCount: z.int(),
    /** When its page or one of its collections' pages was last opened, for the Library's Recently used order. */
    lastOpenedAt: ApiDateTimeSchema.nullable(),
    /** What the creator's page calls their seasons and episodes, such as albums and tracks for an artist. */
    words: CollectionWordsSchema,
    genre: z.string().nullable(),
    contentRating: z.string().nullable(),
})
export type CreatorRead = z.infer<typeof CreatorReadSchema>

export const CreatorPageReadSchema = CreatorReadSchema.extend({
    collections: z.array(z.object({
        id: z.number(),
        slug: z.string(),
        title: z.string(),
        type: z.string(),
        sourceKey: z.string(),
        thumbnailLandscapePath: z.string().nullable(),
        thumbnailPortraitPath: z.string().nullable(),
        thumbnailSquarePath: z.string().nullable(),
        logoImagePath: z.string().nullable(),
        authorHeadshotPath: z.string().nullable(),
        episodeCount: z.number(),
        years: z.string(),
        firstPublishedDate: ApiDateTimeSchema.nullable(),
        /** The one season the videos in none of its lists share, such as Singles; null when they get one per year. */
        looseSeason: z.string().nullable().optional(),
        /** The Site the collection is on, which tells whether its music is tracks or music videos. */
        site: SiteReadSchema.nullable().default(null),
    })),
    /** The creator's movies in the Library. */
    movies: z.array(z.object({
        slug: z.string(),
        title: z.string(),
        thumbnailPortraitPath: z.string().nullable(),
        thumbnailLandscapePath: z.string().nullable(),
        backgroundImagePath: z.string().nullable(),
        logoImagePath: z.string().nullable(),
        releaseDate: z.string().nullable(),
        publishedAt: ApiDateTimeSchema.nullable(),
        drmProtected: z.boolean().default(false),
    })).default([]),
    /** When the newest episode of all of the creator's collections came out. */
    lastPublishedDate: ApiDateTimeSchema.nullable(),
})
export type CreatorPageRead = z.infer<typeof CreatorPageReadSchema>

/** A show or movie of the creator at one of their Sites, with what the Library has of it. */
export const CreatorOfferingSchema = z.object({
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    kind: z.enum(['show', 'item']),
    /** What the Site calls it, such as show or movie. */
    names: NamesSchema,
    itemCount: z.number().nullable(),
    imageUrl: z.string().nullable(),
    description: z.string().nullable(),
    access: z.string().nullable(),
    year: z.string().nullable(),
    /** For a show: its collection in the Library, and whether that is one of this creator's already. */
    collectionSlug: z.string().nullable(),
    collectionTitle: z.string().nullable(),
    collectionJoined: z.boolean(),
    /** For a movie: the movie in the Library, and whether that is one of this creator's already. */
    movieSlug: z.string().nullable(),
    movieTitle: z.string().nullable(),
    movieJoined: z.boolean(),
})
export type CreatorOffering = z.infer<typeof CreatorOfferingSchema>

export const CreatorOfferingsSchema = z.object({
    accounts: z.array(z.object({
        accountId: z.number(),
        site: SiteReadSchema,
        offerings: z.array(CreatorOfferingSchema),
    })),
})
export type CreatorOfferings = z.infer<typeof CreatorOfferingsSchema>

/** One page of the episodes of all of a creator's collections, newest first. */
export const CreatorEpisodePageReadSchema = z.object({
    items: z.array(EpisodeReadViewSchema.extend({
        collectionSlug: z.string(),
        collectionTitle: z.string(),
    })),
    nextCursor: z.string().nullable().optional(),
    hasMore: z.boolean(),
})
export type CreatorEpisode = z.infer<typeof CreatorEpisodePageReadSchema>['items'][number]

export const CreatorUpdateSchema = z.object({
    title: z.string().trim().min(1, 'Give them a name').max(255).default(''),
    genre: z.string().trim().max(200).default(''),
    contentRating: z.string().trim().max(50).default(''),
})
export type CreatorUpdateIn = z.input<typeof CreatorUpdateSchema>
export type CreatorUpdateOut = z.output<typeof CreatorUpdateSchema>

/** The creator behind a collection's link, before the collection is added to it. */
export const CollectionCreatorMatchSchema = z.object({
    /** Joining with it uses what this lookup found, instead of asking the Site again. */
    lookupId: z.string().nullable().optional(),
    siteName: z.string(),
    creatorNames: NamesSchema,
    ref: z.string(),
    url: z.string().nullable().optional(),
    title: z.string(),
    handle: z.string().nullable().optional(),
    avatarUrl: z.string().nullable().optional(),
    /** The creator, when they are in the Library already. */
    creatorSlug: z.string().nullable().optional(),
    creatorTitle: z.string().nullable().optional(),
})
export type CollectionCreatorMatch = z.infer<typeof CollectionCreatorMatchSchema>
