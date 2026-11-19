import {z} from 'zod'
import {DwMembershipLevelReg} from '../dailywire_user_info'
import {CollectionTypeReg, EpisodeIdentifierReg} from '../collection'
import {ApiDateTimeSchema} from './datetime'
import {EpisodeReadViewSchema} from './episode'
import {CreatorSectionNamesSchema} from './source'

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
    /** The movie in the Library that this single item is, when it is one. */
    movieSlug: z.string().nullable().default(null),
    movieTitle: z.string().nullable().default(null),
    /** The movie is one of this creator's already. */
    movieJoined: z.boolean().default(false),
    status: z.enum(['known', 'new', 'ignored']).default('known'),
})
export type CreatorSectionRead = z.infer<typeof CreatorSectionReadSchema>

export const SectionPlanSchema = z.object({
    ref: z.string(),
    target: z.enum(SectionTargetValues),
})
export type SectionPlan = z.infer<typeof SectionPlanSchema>

export const NewSectionActionValues = ['ask', 'season', 'own', 'ignore'] as const
export type NewSectionAction = typeof NewSectionActionValues[number]

/** One kind of list a creator's Sites have, such as a SoundCloud artist's albums, with what happens with a new one. */
export const CreatorNewListSchema = z.object({
    key: z.string(),
    one: z.string(),
    many: z.string(),
    /** The lists can be seasons of the creator's own collection. */
    seasons: z.boolean(),
    /** The kind best describes an artist's albums. */
    albums: z.boolean().default(false),
    action: z.enum(NewSectionActionValues),
})
export type CreatorNewList = z.infer<typeof CreatorNewListSchema>

/** What happens with a new list, by the key of its kind, as a form keeps it. */
export const NewListsSchema = z.record(z.string(), z.enum(NewSectionActionValues))

/** A form's settings for new lists, from what the server says of each kind. */
export function newListsValues(settings: readonly CreatorNewList[]): Record<string, CreatorNewList['action']> {
    return Object.fromEntries(settings.map((setting) => [setting.key, setting.action]))
}

export const CreatorLookupReadSchema = z.object({
    /** Adding the creator with it uses what this lookup found, instead of asking the Site again. */
    lookupId: z.string().nullable().optional(),
    sourceKey: z.string(),
    siteKey: z.string(),
    siteName: z.string(),
    creatorLabel: z.string(),
    /** What the Site calls the creator when they are added as a music artist. */
    musicCreatorLabel: z.string(),
    /** What the Site calls the things its creators add, such as shows on The Daily Wire. */
    creatorSections: CreatorSectionNamesSchema,
    /** The creator's lists can be seasons of its own collection. */
    linkSeasons: z.boolean().default(false),
    /** The creator's single items are movies, which VODLoft adds to the Library and joins to the creator. */
    movies: z.boolean().default(false),
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
    /** What each preset does with the sections; ``musicPlan`` when the creator is added as a music artist. */
    presets: z.array(z.object({key: z.enum(CreatorPresetValues), plan: z.array(SectionPlanSchema), musicPlan: z.array(SectionPlanSchema)})),
    creatorSlug: z.string().nullable(),
    /** A music artist, whose collections are Music collections. Unless ``musicKnown``, a guess the user can change. */
    music: z.boolean().default(false),
    /** The Site is sure whether the creator is a music artist, such as Bandcamp, whose creators always are. */
    musicKnown: z.boolean().default(false),
    /** Why the lookup took the creator for a music artist, when it guessed so. */
    musicReason: z.string().nullable().optional(),
    /** What the creator does with a new list of each kind until you choose otherwise. */
    newLists: z.array(CreatorNewListSchema),
    /** The same for a music artist: their albums are added, and other kinds of list are skipped. */
    musicNewLists: z.array(CreatorNewListSchema),
})
export type CreatorLookupRead = z.infer<typeof CreatorLookupReadSchema>

const SiteSchema = z.object({
    key: z.string(), name: z.string(), creatorLabel: z.string().default('creator'), linkSeasons: z.boolean().default(false),
    /** The Site has sound only, such as Bandcamp. */
    audio: z.boolean().default(false),
    /** What the Site calls the things its creators add, such as playlists on YouTube. */
    creatorSections: CreatorSectionNamesSchema,
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
    /** The word of their one Site, such as host, or artist for a music artist. */
    creatorLabel: z.string(),
    /** A music artist: they have a Music collection. */
    music: z.boolean(),
    /** What VODLoft looks for: what their one Site calls it, such as playlists, or playlists and shows. */
    sectionNames: CreatorSectionNamesSchema,
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
    /** What the creator does with a new list, for each kind of list of their Sites. */
    newLists: z.array(CreatorNewListSchema),
    genre: z.string().nullable(),
    contentRating: z.string().nullable(),
})
export type CreatorRead = z.infer<typeof CreatorReadSchema>

export const CreatorPageAccountReadSchema = CreatorAccountReadSchema.extend({
    sections: z.array(CreatorSectionReadSchema),
    /** The account's single items are movies, which VODLoft adds to the Library and joins to the creator. */
    movies: z.boolean().default(false),
})
export type CreatorPageAccountRead = z.infer<typeof CreatorPageAccountReadSchema>

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
        links: z.array(z.string()),
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
    newLists: NewListsSchema.default({}),
    /** A creator in the Library who is the same person or group: the account joins them. Empty for a new creator. */
    into: z.string().default(''),
    /** What the creator's collections are: Music for a music artist. */
    type: z.enum(['series', 'music']).default('series'),
}).refine((value) => value.sections.some((section) => section.target !== 'skip'), {
    message: 'Pick at least one section to keep',
    path: ['sections'],
})
export type CreatorCreateIn = z.input<typeof CreatorCreateSchema>
export type CreatorCreateOut = z.output<typeof CreatorCreateSchema>

/** The form that changes how VODLoft follows a creator. */
export const CreatorUpdateSchema = z.object({
    title: z.string().trim().min(1, 'Give them a name').max(255).default(''),
    newLists: NewListsSchema.default({}),
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
    /** What the creator's Site calls the things the creator adds, such as playlists on YouTube. */
    sectionNames: CreatorSectionNamesSchema,
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

/** The type and episode identification of a section of a creator that becomes a collection of its own. */
export const CreatorCollectionFormSchema = z.object({
    type: z.union([z.enum(CollectionTypeReg.values), z.literal('')]).default('')
        .pipe(z.enum(CollectionTypeReg.values, {error: 'Choose a collection type'})),
    episodeIdentifier: z.union([z.enum(EpisodeIdentifierReg.values), z.literal('')]).default('')
        .pipe(z.enum(EpisodeIdentifierReg.values, {error: 'Choose how its episodes are identified'})),
})
export type CreatorCollectionFormIn = z.input<typeof CreatorCollectionFormSchema>
export type CreatorCollectionFormOut = z.output<typeof CreatorCollectionFormSchema>
