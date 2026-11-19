import {z} from 'zod'

export const LinkSeasonModeValues = ['all', 'selected'] as const
export const NewLinkSeasonValues = ['ask', 'add', 'ignore'] as const
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
    /** The playlist or album the season is, when it is one. */
    linkTitle: z.string().nullable(),
})
export type CollectionSeasonRead = z.infer<typeof CollectionSeasonReadSchema>

export const LinkSeasonReadSchema = z.object({
    id: z.number(),
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    imageUrl: z.string().nullable(),
    itemCount: z.number().nullable(),
    enabled: z.boolean(),
    status: z.enum(['known', 'new']),
    seasonName: z.string().nullable(),
    firstVideoAt: z.string().nullable(),
    /** Videos from outside the collection's own link that only this one lists, which leave with it, files and all. */
    leavingCount: z.number(),
    leavingWithFiles: z.number(),
    /** A link the user added, which they can remove again, rather than one of the playlists of the channel. */
    addedByUser: z.boolean().default(false),
})
export type LinkSeasonRead = z.infer<typeof LinkSeasonReadSchema>

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
    newLinkSeasons: z.enum(NewLinkSeasonValues),
    looseVideos: z.enum(LooseVideosValues),
    outsideVideos: z.enum(OutsideVideosValues),
    outsideCount: z.number(),
    outsideWithFiles: z.number(),
    /** The videos no playlist that is a season has now, which leave once the collection holds only what they have. */
    onlyLeavingCount: z.number().default(0),
    onlyLeavingWithFiles: z.number().default(0),
    /** What the collection's Site calls them: playlist and Videos, or album and Singles in a Music collection. */
    names: z.object({one: z.string(), many: z.string(), looseSeason: z.string()}),
    /** A Music collection, of an artist's tracks rather than a channel's videos. */
    music: z.boolean().default(false),
    playlists: z.array(LinkSeasonReadSchema),
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
    newLinkSeasons: z.enum(NewLinkSeasonValues).default('ask'),
    looseVideos: z.enum(LooseVideosValues).default('one_season'),
    outsideVideos: z.enum(OutsideVideosValues).default('leave_out'),
    playlists: z.array(z.object({id: z.number(), enabled: z.boolean()})).default([]),
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
        newLinkSeasons: view.newLinkSeasons,
        looseVideos: view.looseVideos,
        outsideVideos: view.outsideVideos,
        playlists: view.playlists.map((playlist) => ({id: playlist.id, enabled: playlist.enabled})),
        removedLinks: [],
    }
}
