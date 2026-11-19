import {z} from 'zod'
import {DwMembershipLevelReg} from '../dailywire_user_info'
import {ApiDateTimeSchema} from './datetime'
import {EpisodeReadViewSchema} from './episode'

export const SectionTargetValues = ['main', 'own', 'skip'] as const
export const CreatorPresetValues = ['one_show', 'per_list', 'pick'] as const

export const CreatorSectionReadSchema = z.object({
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    kind: z.enum(['feed', 'list', 'show', 'item']),
    role: z.string(),
    kindLabel: z.string().nullable(),
    itemCount: z.number().nullable(),
    imageUrl: z.string().nullable(),
    description: z.string().nullable(),
    access: z.string().nullable(),
    year: z.string().nullable().optional(),
    collectionSlug: z.string().nullable(),
    collectionTitle: z.string().nullable(),
    status: z.enum(['known', 'new', 'ignored']).default('known'),
})
export type CreatorSectionRead = z.infer<typeof CreatorSectionReadSchema>

export const SectionPlanSchema = z.object({
    ref: z.string(),
    target: z.enum(SectionTargetValues),
})
export type SectionPlan = z.infer<typeof SectionPlanSchema>

export const CreatorLookupReadSchema = z.object({
    /** Adding the creator with it uses what this lookup found, instead of asking the Site again. */
    lookupId: z.string().nullable().optional(),
    sourceKey: z.string(),
    siteKey: z.string(),
    siteName: z.string(),
    creatorLabel: z.string(),
    /** The creator's lists can be seasons of its own collection. */
    linkSeasons: z.boolean().default(false),
    ref: z.string(),
    url: z.string().nullable(),
    title: z.string(),
    handle: z.string().nullable(),
    description: z.string().nullable(),
    avatarUrl: z.string().nullable(),
    bannerUrl: z.string().nullable(),
    links: z.array(z.string()),
    facts: z.array(z.string()),
    sections: z.array(CreatorSectionReadSchema),
    presets: z.array(z.object({key: z.enum(CreatorPresetValues), plan: z.array(SectionPlanSchema)})),
    creatorSlug: z.string().nullable(),
    music: z.boolean().default(false),
})
export type CreatorLookupRead = z.infer<typeof CreatorLookupReadSchema>

export const NewSectionActionValues = ['ask', 'season', 'own', 'ignore'] as const

const SiteSchema = z.object({
    key: z.string(), name: z.string(), creatorLabel: z.string().default('creator'), linkSeasons: z.boolean().default(false),
})

/** A creator's account on one Site, such as their YouTube channel. */
export const CreatorAccountReadSchema = z.object({
    id: z.number(),
    sourceKey: z.string(),
    site: SiteSchema,
    siteRef: z.string(),
    url: z.string().nullable(),
    handle: z.string().nullable(),
    checkedAt: z.string().nullable(),
    /** The collection named after the creator that takes this account's uploads. */
    mainCollectionSlug: z.string().nullable(),
})
export type CreatorAccountRead = z.infer<typeof CreatorAccountReadSchema>

export const CreatorReadSchema = z.object({
    id: z.number(),
    slug: z.string(),
    /** Artist, the word of their one Site, such as host, or creator. */
    creatorLabel: z.string(),
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
    newSections: z.enum(NewSectionActionValues),
    genre: z.string().nullable(),
    contentRating: z.string().nullable(),
})
export type CreatorRead = z.infer<typeof CreatorReadSchema>

export const CreatorPageAccountReadSchema = CreatorAccountReadSchema.extend({
    sections: z.array(CreatorSectionReadSchema),
})
export type CreatorPageAccountRead = z.infer<typeof CreatorPageAccountReadSchema>

export const CreatorPageReadSchema = CreatorReadSchema.extend({
    collections: z.array(z.object({
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
        links: z.array(z.string()),
    })),
    /** When the newest episode of all of the creator's collections came out. */
    lastPublishedDate: ApiDateTimeSchema.nullable(),
    accounts: z.array(CreatorPageAccountReadSchema),
    /** Downloaded episodes the creator places in another of its collections than the one they are in. */
    reassignedCount: z.number().default(0),
})
export type CreatorPageRead = z.infer<typeof CreatorPageReadSchema>

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

/** The form that adds a creator: where each of its sections goes. */
export const CreatorCreateSchema = z.object({
    sourceKey: z.string().min(1),
    url: z.string().nullable().default(null),
    ref: z.string().nullable().default(null),
    preset: z.enum(CreatorPresetValues).default('one_show'),
    sections: z.array(SectionPlanSchema).default([]),
    membershipLevel: z.enum(DwMembershipLevelReg.Enum).default(DwMembershipLevelReg.Enum.HIGHEST_ALLOWED),
    newSections: z.enum(NewSectionActionValues).default('ask'),
    /** A creator in the Library who is the same person or group: the account joins them. Empty for a new creator. */
    into: z.string().default(''),
}).refine((value) => value.sections.some((section) => section.target !== 'skip'), {
    message: 'Pick at least one section to keep',
    path: ['sections'],
})
export type CreatorCreateIn = z.input<typeof CreatorCreateSchema>
export type CreatorCreateOut = z.output<typeof CreatorCreateSchema>

/** The form that changes how VODLoft follows a creator. */
export const CreatorUpdateSchema = z.object({
    newSections: z.enum(NewSectionActionValues).default('ask'),
    genre: z.string().trim().max(200).default(''),
    contentRating: z.string().trim().max(50).default(''),
})
export type CreatorUpdateIn = z.input<typeof CreatorUpdateSchema>
export type CreatorUpdateOut = z.output<typeof CreatorUpdateSchema>

/** The creator behind a collection's link, before the collection is added to it. */
export const CollectionCreatorMatchSchema = z.object({
    /** Adding the collection with it uses what this lookup found, instead of asking the Site again. */
    lookupId: z.string().nullable().optional(),
    siteName: z.string(),
    creatorLabel: z.string(),
    ref: z.string(),
    url: z.string().nullable().optional(),
    title: z.string(),
    handle: z.string().nullable().optional(),
    avatarUrl: z.string().nullable().optional(),
    creatorSlug: z.string().nullable().optional(),
    /** The creator's section the collection is, when it is one. */
    sectionTitle: z.string().nullable().optional(),
    sectionKindLabel: z.string().nullable().optional(),
    /** Another of the creator's collections that keeps this section already, and can't let it go. */
    keptBy: z.string().nullable().optional(),
    /** The playlists that would be in two places once the collection joins; each stays in one, as you choose. */
    overlaps: z.array(z.object({
        ref: z.string(),
        title: z.string(),
        keptBy: z.string(),
        /** The creator's own collection keeps it and can let it go; a collection of its own keeps what it has. */
        canMoveHere: z.boolean(),
    })).default([]),
})
export type CollectionCreatorMatch = z.infer<typeof CollectionCreatorMatchSchema>

export const CollectionCreatorLeaveSchema = z.object({
    creatorTitle: z.string(),
})
export type CollectionCreatorLeave = z.infer<typeof CollectionCreatorLeaveSchema>
