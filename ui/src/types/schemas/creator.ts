import {z} from 'zod'
import {DwMembershipLevelReg} from '../dailywire_user_info'
import {CollectionTypeReg, EpisodeIdentifierReg} from '../collection'
import {ApiDateTimeSchema} from './datetime'
import {EpisodeReadViewSchema} from './episode'
import {NamesSchema, SectionTypeSchema} from './source'

export const SectionTargetValues = ['main', 'main_loose', 'own', 'exclude'] as const
export const CreatorPresetValues = ['one_show', 'per_list', 'pick'] as const

export const CreatorSectionReadSchema = z.object({
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    kind: z.enum(['feed', 'list', 'show', 'item']),
    role: z.string(),
    /** The key of the Site's section type the section is, such as album. */
    type: z.string(),
    /** What the Site calls the section's type, or VODLoft's own word for its kind where the Site names none. */
    names: NamesSchema,
    /** VODLoft's own word for the section's kind, such as feed, which names several types of feed together. */
    kindNames: NamesSchema,
    itemCount: z.number().nullable(),
    imageUrl: z.string().nullable(),
    description: z.string().nullable(),
    access: z.string().nullable(),
    year: z.string().nullable().optional(),
    collectionSlug: z.string().nullable(),
    /** For a list in the creator's own collection: whether it is a season of its own, rather than having its videos
     *  where the ones in no list go. */
    asSeason: z.boolean().nullable().optional(),
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
    /** With main or main_loose: another of the creator's collections it goes into instead of their own. */
    collectionSlug: z.string().optional(),
})
export type SectionPlan = z.infer<typeof SectionPlanSchema>

export const NewSectionActionValues = ['ask', 'season', 'loose', 'own', 'ignore'] as const
export type NewSectionAction = typeof NewSectionActionValues[number]

/** One kind of list a creator's Sites have, such as a SoundCloud artist's albums, with what happens with a new one. */
export const CreatorNewListSchema = z.object({
    /** The Site the kind is on: each of a creator's Sites has settings of its own. */
    siteKey: z.string(),
    siteName: z.string(),
    key: z.string(),
    names: NamesSchema,
    /** The lists can be seasons of the creator's own collection. */
    seasons: z.boolean(),
    /** The kind best describes an artist's albums. */
    albums: z.boolean().default(false),
    action: z.enum(NewSectionActionValues),
})
export type CreatorNewList = z.infer<typeof CreatorNewListSchema>

/** What happens with a new list, by Site and the key of its kind, as a form keeps it. */
export const NewListsSchema = z.record(z.string(), z.record(z.string(), z.enum(NewSectionActionValues)))
export type NewLists = z.infer<typeof NewListsSchema>

/** A form's settings for new lists, from what the server says of each kind. */
export function newListsValues(settings: readonly CreatorNewList[]): NewLists {
    const values: NewLists = {}
    for (const setting of settings) values[setting.siteKey] = {...values[setting.siteKey], [setting.key]: setting.action}
    return values
}

/** The settings with one kind's changed. */
export function withNewList(values: NewLists, kind: {siteKey?: string, key: string}, action: NewSectionAction): NewLists {
    const site = kind.siteKey ?? ''
    return {...values, [site]: {...values[site], [kind.key]: action}}
}

export const CreatorLookupReadSchema = z.object({
    /** Adding the creator with it uses what this lookup found, instead of asking the Site again. */
    lookupId: z.string().nullable().optional(),
    sourceKey: z.string(),
    siteKey: z.string(),
    siteName: z.string(),
    creatorNames: NamesSchema,
    /** Every type of section the Site's creators have, such as shows and movies on The Daily Wire. */
    sectionTypes: z.array(SectionTypeSchema),
    /** The Site has sound only, such as Bandcamp, so what its lists hold are tracks. */
    audioOnly: z.boolean().default(false),
    /** What the Site calls one of its videos: a video, or a track on a Site with sound only. */
    mediaNames: NamesSchema,
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
    /** The kinds of list named together, such as albums and playlists. */
    newListNames: NamesSchema,
    /** What the Site calls the lists and shows its creators add, such as playlists, or shows on The Daily Wire. */
    sectionGrowingNames: NamesSchema,
})
export type CreatorLookupRead = z.infer<typeof CreatorLookupReadSchema>

const SiteSchema = z.object({
    key: z.string(), name: z.string(), creatorNames: NamesSchema, linkSeasons: z.boolean().default(false),
    /** The Site has sound only, such as Bandcamp. */
    audioOnly: z.boolean().default(false),
    /** What the Site calls one of its videos: a video, or a track on a Site with sound only. */
    mediaNames: NamesSchema,
    /** Every type of section the Site's creators have, such as feeds and playlists on YouTube. */
    sectionTypes: z.array(SectionTypeSchema),
    /** What the Site calls the lists and shows its creators add, such as playlists, or shows on The Daily Wire. */
    sectionGrowingNames: NamesSchema,
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
    /** What the creator does with a new list, for each kind of list of their Sites. */
    newLists: z.array(CreatorNewListSchema),
    /** Those kinds of list named together, such as albums and playlists, or lists when there are none. */
    newListNames: NamesSchema,
    /** What the creator's page calls their seasons and episodes, such as albums and tracks for an artist. */
    words: z.object({season: NamesSchema, episode: NamesSchema}),
    genre: z.string().nullable(),
    contentRating: z.string().nullable(),
})
export type CreatorRead = z.infer<typeof CreatorReadSchema>

export const CreatorPageAccountReadSchema = CreatorAccountReadSchema.extend({
    sections: z.array(CreatorSectionReadSchema),
    /** The collections that hold several of the account's feeds and lists, its own collection first. */
    gatheringSlugs: z.array(z.string()).default([]),
    /** The collections a feed or list of the account can go into besides a collection of its own. */
    gatherableSlugs: z.array(z.string()).default([]),
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
}).refine((value) => value.sections.some((section) => section.target !== 'exclude'), {
    message: 'Pick at least one section to keep',
    path: ['sections'],
})
export type CreatorCreateIn = z.input<typeof CreatorCreateSchema>
export type CreatorCreateOut = z.output<typeof CreatorCreateSchema>

/** The form that changes how VODLoft follows a creator. */
/** Where the creator's feeds and lists go, by "<account id>:<ref>": only the ones the user changed. */
/** Where the user moved each feed or list to: a target, or main@<slug> and main_loose@<slug> for another of the
 * creator's collections. */
export const SectionPlacesSchema = z.record(z.string(), z.string())
export type SectionPlaces = z.infer<typeof SectionPlacesSchema>

export const CreatorUpdateSchema = z.object({
    title: z.string().trim().min(1, 'Give them a name').max(255).default(''),
    newLists: NewListsSchema.default({}),
    genre: z.string().trim().max(200).default(''),
    contentRating: z.string().trim().max(50).default(''),
    places: SectionPlacesSchema.default({}),
})
export type CreatorUpdateIn = z.input<typeof CreatorUpdateSchema>
export type CreatorUpdateOut = z.output<typeof CreatorUpdateSchema>

/** The creator behind a collection's link, before the collection is added to it. */
export const CollectionCreatorMatchSchema = z.object({
    /** Adding the collection with it uses what this lookup found, instead of asking the Site again. */
    lookupId: z.string().nullable().optional(),
    siteName: z.string(),
    creatorNames: NamesSchema,
    /** Every type of section the creator's Site has, such as feeds and playlists on YouTube. */
    sectionTypes: z.array(SectionTypeSchema),
    /** What the Site calls the lists and shows its creators add, such as playlists, or shows on The Daily Wire. */
    sectionGrowingNames: NamesSchema,
    ref: z.string(),
    url: z.string().nullable().optional(),
    title: z.string(),
    handle: z.string().nullable().optional(),
    avatarUrl: z.string().nullable().optional(),
    creatorSlug: z.string().nullable().optional(),
    /** The creator's section the collection is, when it is one. */
    sectionTitle: z.string().nullable().optional(),
    /** The key of the type of the section the collection is. */
    sectionType: z.string().nullable().optional(),
    /** Another of the creator's collections that keeps this section already, and can't let it go. */
    keptBy: z.string().nullable().optional(),
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

/** One feed or list of the creator that goes elsewhere. */
export type SectionMove = {accountId: number, ref: string, target: typeof SectionTargetValues[number], collectionSlug?: string}

/** The videos of one feed or list that leave a collection or join it. */
export const MovedPartSchema = z.object({
    sectionTitle: z.string(),
    sectionKind: z.enum(['feed', 'list', 'show', 'item']),
    /** What moves, in the Site's words: shorts for a feed, videos for a list. */
    names: NamesSchema,
    direction: z.enum(['out', 'in', 'leave', 'season', 'loose']),
    count: z.number(),
    otherTitle: z.string().nullable().optional(),
    examples: z.array(z.string()),
    downloadsDeleted: z.number().default(0),
    keptDeleted: z.number().default(0),
    deletingProfiles: z.array(z.string()).default([]),
    filesMoved: z.number().default(0),
})
export type MovedPart = z.infer<typeof MovedPartSchema>

/** What moving feeds and lists does to one of the creator's collections. */
export const MoveCollectionSchema = z.object({
    slug: z.string(),
    title: z.string(),
    type: z.string(),
    state: z.enum(['existing', 'new', 'deleted']),
    episodeIdentifier: z.string(),
    parts: z.array(MovedPartSchema),
    newSeasons: z.array(z.string()),
    episodes: z.number(),
    renumberOffered: z.boolean(),
    changes: z.array(z.object({title: z.string(), before: z.string(), after: z.string()})),
    profiles: z.array(z.object({name: z.string(), filesRenamed: z.number(), metadataRewritten: z.number()})),
    /** Files moved into it, so its files are renamed and their metadata rewritten also when it keeps its numbers. */
    filesFollow: z.boolean(),
    indexed: z.boolean(),
})
export type MoveCollection = z.infer<typeof MoveCollectionSchema>

export const SectionMovesPreviewSchema = z.object({collections: z.array(MoveCollectionSchema)})
export type SectionMovesPreview = z.infer<typeof SectionMovesPreviewSchema>
