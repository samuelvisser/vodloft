import {z} from 'zod'
import {NamesSchema, SectionTypeSchema} from './source'
import {CollectionWordsSchema} from './collection_contract'

export const NewLinkSeasonValues = ['ask', 'add', 'contents', 'ignore'] as const
export type NewLinkSeason = typeof NewLinkSeasonValues[number]
/** How the collection groups its own videos: for a channel collection, every video of its feeds in one season, the
 *  ones in no list that is a season in one season, or a season per year; for a collection made from one list, the
 *  list's one season or a season per year. */
export const LooseVideosValues = ['everything', 'one_season', 'by_year'] as const
export type LooseVideos = typeof LooseVideosValues[number]
export const OutsideVideosValues = ['leave_out', 'add', 'only'] as const
export const RepeatVideosValues = ['one_season', 'each_season'] as const

export const CollectionSeasonReadSchema = z.object({
    id: z.number(),
    slug: z.string(),
    name: z.string(),
    seasonNumber: z.number(),
    index: z.number(),
    seasonType: z.string(),
    /** Holds the videos in none of the link seasons. */
    loose: z.boolean(),
    episodeCount: z.number(),
    /** The playlists or albums the season holds, when it is a season of lists, in the order their videos go. */
    listTitles: z.array(z.string()).default([]),
    /** VODLoft or the user made the season, so it can be deleted; the settings make it again where they put videos. */
    removable: z.boolean().default(false),
    /** The year the season holds, when VODLoft made it for the videos of one year. */
    year: z.number().nullable().default(null),
})
export type CollectionSeasonRead = z.infer<typeof CollectionSeasonReadSchema>

/** The seasons saving the Seasons dialog would leave, in their order. */
export const SeasonsPreviewReadSchema = z.object({seasons: z.array(CollectionSeasonReadSchema)})
export type SeasonsPreviewRead = z.infer<typeof SeasonsPreviewReadSchema>

export const CollectionListReadSchema = z.object({
    id: z.number(),
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    imageUrl: z.string().nullable(),
    itemCount: z.number().nullable(),
    /** The key of the list's type on its Site, such as album or playlist; null for a link you added. */
    typeKey: z.string().nullable().default(null),
    enabled: z.boolean(),
    status: z.enum(['known', 'new']),
    /** Whether the list is a season of its own when it is on; one that is not adds its videos to the other seasons. */
    asSeason: z.boolean().default(true),
    /** The list's season, which other lists may share. */
    seasonId: z.number().nullable().default(null),
    seasonName: z.string().nullable(),
    firstVideoAt: z.string().nullable(),
    /** Videos from outside the collection's own link that only this one lists, which leave with it, files and all. */
    leavingCount: z.number(),
    leavingWithFiles: z.number(),
    /** A link the user added, which they can remove again, rather than one of the playlists of the creator. */
    addedByUser: z.boolean().default(false),
    /** For a collection without a link of its own: its default link, such as the one its picture comes from. Such a
     * collection always has one: its first link, until the user picks another. */
    isDefault: z.boolean().default(false),
})
export type CollectionListRead = z.infer<typeof CollectionListReadSchema>

export const CollectionSeasonsReadSchema = z.object({
    seasons: z.array(CollectionSeasonReadSchema),
    customSeasonOrder: z.boolean(),
    linkSeasonsOffered: z.boolean(),
    /** The collection has a link of its own; one that holds only what its playlists have may go without. */
    hasOwnLink: z.boolean().default(true),
    /** The collection's own link is a whole channel, whose playlists VODLoft lists. */
    listsPlaylists: z.boolean().default(false),
    /** The collection can hold only what its playlists have, with links you add from any site. */
    linksOnlyOffered: z.boolean().default(false),
    /** What the collection's own link is: a channel, one list, or none, for a custom collection. */
    kind: z.enum(['channel', 'list', 'custom']),
    /** The collection is made from one list: the list is its one season, or its videos go in a season per year. */
    madeFromList: z.boolean().default(false),
    /** For a channel collection: the feeds of its channel, whether it takes each, and whether each is a season of its
     *  own, with that season once it has one. */
    feeds: z.array(z.object({
        ref: z.string(), names: NamesSchema, on: z.boolean(), asSeason: z.boolean().default(false),
        seasonId: z.number().nullable().default(null),
    })),
    /** The videos of the channel's feeds can be in one season of their own, rather than a season per year. */
    channelSeasonOffered: z.boolean().default(false),
    /** What that season is called by how the collection groups its videos, such as Channel while it holds everything
     *  and Videos while it holds what is in no list. */
    channelSeasonNames: z.record(z.string(), z.string()),
    /** What the collection's Site calls a channel, such as channel, or account on SoundCloud. */
    channelNames: NamesSchema,
    linkSeasons: z.enum(['off', 'on']),
    /** What happens with a list the channel adds, for each kind of list of the collection's Site. */
    newLists: z.array(z.object({
        key: z.string(), names: NamesSchema, albums: z.boolean().default(false),
        action: z.enum(NewLinkSeasonValues),
    })),
    looseVideos: z.enum(LooseVideosValues),
    /** Whether a video that belongs in several seasons has an episode in the first of them, or in each. */
    repeatVideos: z.enum(RepeatVideosValues),
    /** The episodes of videos the collection has in another season already, which leave when it keeps one season. */
    repeatedCount: z.number(),
    outsideVideos: z.enum(OutsideVideosValues),
    outsideCount: z.number(),
    outsideWithFiles: z.number(),
    /** The videos no playlist that is a season has now, which leave once the collection holds only what they have. */
    onlyLeavingCount: z.number().default(0),
    onlyLeavingWithFiles: z.number().default(0),
    /** The types of list of the collection's Site, which its link seasons come from. */
    listTypes: z.array(SectionTypeSchema),
    /** Those types of list named together, such as albums and playlists. */
    sectionListNames: NamesSchema,
    /** The same lists as the creator's, such as creator playlists or artist albums, so they read apart from the
     * collection's own seasons, which a YouTube channel collection also calls playlists. A collection without a link
     * of its own calls them links: the ones the user gave it. */
    creatorListNames: NamesSchema,
    /** The season of the videos in none of the lists, such as Videos, Singles or Tracks. */
    looseSeason: z.string(),
    /** What the collection's Site calls the creator behind it, such as artist in a Music collection. */
    creatorNames: NamesSchema,
    /** What the collection's Site calls its media: videos, or tracks on a Site with sound only. */
    mediaNames: NamesSchema,
    /** The link seasons keep the order the Site gives the lists, as an artist's albums do, instead of by date. */
    siteOrder: z.boolean().default(false),
    /** What the collection calls its seasons and episodes. */
    words: CollectionWordsSchema,
    playlists: z.array(CollectionListReadSchema),
})
export type CollectionSeasonsRead = z.infer<typeof CollectionSeasonsReadSchema>

/** The Seasons dialog: the seasons in their order with their names, and how the link seasons work. */
export const CollectionSeasonsFormSchema = z.object({
    seasons: z.array(z.object({
        id: z.number(),
        name: z.string().trim().min(1, 'Give the season a name').max(200),
    })).default([]),
    customSeasonOrder: z.boolean().default(false),
    /** For a channel collection: the refs of the feeds it takes. */
    feeds: z.array(z.string()).default([]),
    /** The feeds that are a season of their own, by ref, each with the season it is in: its own (null), or that of a
     *  list or another feed, which it shares. */
    feedSeasons: z.record(z.string(), z.number().nullable()).default({}),
    linkSeasonsOn: z.boolean().default(false),
    /** What happens with a new list, by the key of its kind. */
    newLists: z.record(z.string(), z.enum(NewLinkSeasonValues)).default({}),
    looseVideos: z.enum(LooseVideosValues).default('one_season'),
    repeatVideos: z.enum(RepeatVideosValues).default('one_season'),
    outsideVideos: z.enum(OutsideVideosValues).default('leave_out'),
    /** Each list, whether it is a season, and the season it is in: its own, or another list's that it shares. */
    playlists: z.array(z.object({
        id: z.number(), enabled: z.boolean(), asSeason: z.boolean().default(true), seasonId: z.number().nullable(),
        isDefault: z.boolean().default(false),
    })).default([]),
    /** Links you added that go when you save. */
    removedLinks: z.array(z.number()).default([]),
    /** Links you add, which are saved, and listed, when you save. */
    addedLinks: z.array(z.object({url: z.string(), title: z.string(), imageUrl: z.string().nullable()})).default([]),
    /** Seasons that are deleted when you save. */
    removedSeasons: z.array(z.number()).default([]),
})

/** A link you add to a collection. */
export const LinkSeasonAddFormSchema = z.object({
    url: z.string().trim().min(1, 'Paste a link').regex(/^https?:\/\//, 'Paste a link starting with https://').default(''),
})
/** A link you add, as VODLoft found it; nothing is saved until the Seasons dialog is. */
export const AddedLinkReadSchema = z.object({url: z.string(), title: z.string(), imageUrl: z.string().nullable()})
export type AddedLinkRead = z.infer<typeof AddedLinkReadSchema>
export type LinkSeasonAddFormIn = z.input<typeof LinkSeasonAddFormSchema>
export type LinkSeasonAddFormOut = z.output<typeof LinkSeasonAddFormSchema>
export type CollectionSeasonsFormIn = z.input<typeof CollectionSeasonsFormSchema>
export type CollectionSeasonsFormOut = z.output<typeof CollectionSeasonsFormSchema>

export function seasonsFormValues(view: CollectionSeasonsRead): CollectionSeasonsFormOut {
    return {
        seasons: view.seasons.map((season) => ({id: season.id, name: season.name})),
        customSeasonOrder: view.customSeasonOrder,
        feeds: view.feeds.filter((feed) => feed.on).map((feed) => feed.ref),
        feedSeasons: Object.fromEntries(view.feeds.filter((feed) => feed.asSeason).map((feed) => [feed.ref, feed.seasonId])),
        linkSeasonsOn: view.linkSeasons !== 'off',
        newLists: Object.fromEntries(view.newLists.map((setting) => [setting.key, setting.action])),
        looseVideos: view.looseVideos,
        repeatVideos: view.repeatVideos,
        outsideVideos: view.outsideVideos,
        playlists: view.playlists.map((playlist) => ({
            id: playlist.id, enabled: playlist.enabled, asSeason: playlist.asSeason, seasonId: playlist.seasonId,
            isDefault: playlist.isDefault,
        })),
        removedLinks: [],
        addedLinks: [],
        removedSeasons: [],
    }
}
