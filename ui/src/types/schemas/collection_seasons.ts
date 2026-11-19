import {z} from 'zod'
import {SectionTypeSchema} from './source'

export const LinkSeasonModeValues = ['all', 'selected'] as const
export const NewLinkSeasonValues = ['ask', 'add', 'ignore'] as const
export type NewLinkSeason = typeof NewLinkSeasonValues[number]
export const ListLayoutValues = ['season_each', 'by_year'] as const
export const LooseVideosValues = ['one_season', 'by_year'] as const
export const OutsideVideosValues = ['leave_out', 'add', 'only'] as const

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
})
export type CollectionSeasonRead = z.infer<typeof CollectionSeasonReadSchema>

export const CollectionListReadSchema = z.object({
    id: z.number(),
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    imageUrl: z.string().nullable(),
    itemCount: z.number().nullable(),
    enabled: z.boolean(),
    status: z.enum(['known', 'new']),
    /** The list's season, which other lists may share. */
    seasonId: z.number().nullable().default(null),
    seasonName: z.string().nullable(),
    firstVideoAt: z.string().nullable(),
    /** Videos from outside the collection's own link that only this one lists, which leave with it, files and all. */
    leavingCount: z.number(),
    leavingWithFiles: z.number(),
    /** A link the user added, which they can remove again, rather than one of the playlists of the creator. */
    addedByUser: z.boolean().default(false),
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
    linkSeasons: z.enum(['off', ...LinkSeasonModeValues]),
    /** What happens with a list the creator adds, for each kind of list of the collection's Site. */
    newLists: z.array(z.object({
        key: z.string(), one: z.string(), many: z.string(), seasons: z.boolean(), albums: z.boolean().default(false),
        action: z.enum(NewLinkSeasonValues),
    })),
    listLayout: z.enum(ListLayoutValues).default('season_each'),
    looseVideos: z.enum(LooseVideosValues),
    outsideVideos: z.enum(OutsideVideosValues),
    outsideCount: z.number(),
    outsideWithFiles: z.number(),
    /** The videos no playlist that is a season has now, which leave once the collection holds only what they have. */
    onlyLeavingCount: z.number().default(0),
    onlyLeavingWithFiles: z.number().default(0),
    /** What the collection's Site calls its lists, such as playlists on YouTube, and the season of what is in none
     * of them: Videos, or Singles in a Music collection. */
    /** The types of list of the collection's Site, which its link seasons come from. */
    listTypes: z.array(SectionTypeSchema),
    /** The season of the videos in none of the lists, such as Videos, Singles or Tracks. */
    looseSeason: z.string(),
    /** What the collection's Site calls the creator behind it, such as artist in a Music collection. */
    creatorLabel: z.string(),
    /** For a creator's own collection: the creator, which finds its new playlists and decides what happens with them. */
    creatorSlug: z.string().nullable().default(null),
    creatorTitle: z.string().nullable().default(null),
    /** A Music collection, of an artist's tracks rather than a creator's videos. */
    music: z.boolean().default(false),
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
    linkSeasonsOn: z.boolean().default(false),
    linkSeasonMode: z.enum(LinkSeasonModeValues).default('all'),
    /** What happens with a new list, by the key of its kind. */
    newLists: z.record(z.string(), z.enum(NewLinkSeasonValues)).default({}),
    listLayout: z.enum(ListLayoutValues).default('season_each'),
    looseVideos: z.enum(LooseVideosValues).default('one_season'),
    outsideVideos: z.enum(OutsideVideosValues).default('leave_out'),
    /** Each list, whether it is a season, and the season it is in: its own, or another list's that it shares. */
    playlists: z.array(z.object({id: z.number(), enabled: z.boolean(), seasonId: z.number().nullable()})).default([]),
    /** Links you added that go when you save. */
    removedLinks: z.array(z.number()).default([]),
})

/** A link you add to a collection that holds only what its playlists have. */
export const LinkSeasonAddFormSchema = z.object({
    url: z.string().trim().min(1, 'Paste a link').regex(/^https?:\/\//, 'Paste a link starting with https://').default(''),
})
export type LinkSeasonAddFormIn = z.input<typeof LinkSeasonAddFormSchema>
export type LinkSeasonAddFormOut = z.output<typeof LinkSeasonAddFormSchema>
export type CollectionSeasonsFormIn = z.input<typeof CollectionSeasonsFormSchema>
export type CollectionSeasonsFormOut = z.output<typeof CollectionSeasonsFormSchema>

export function seasonsFormValues(view: CollectionSeasonsRead): CollectionSeasonsFormOut {
    return {
        seasons: view.seasons.map((season) => ({id: season.id, name: season.name})),
        customSeasonOrder: view.customSeasonOrder,
        linkSeasonsOn: view.linkSeasons !== 'off',
        linkSeasonMode: view.linkSeasons === 'off' ? 'all' : view.linkSeasons,
        newLists: Object.fromEntries(view.newLists.map((setting) => [setting.key, setting.action])),
        listLayout: view.listLayout,
        looseVideos: view.looseVideos,
        outsideVideos: view.outsideVideos,
        playlists: view.playlists.map((playlist) => ({id: playlist.id, enabled: playlist.enabled, seasonId: playlist.seasonId})),
        removedLinks: [],
    }
}
