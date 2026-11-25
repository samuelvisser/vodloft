import {createSelectRegistry} from '../../utils/selectRegistry'
import {capitalized, type ListKind} from '../../types/creator'
import type {Names} from '../../types/schemas/source'
import {CollectionSeasonsReadSchema, type CollectionSeasonsRead, type LooseVideos} from '../../types/schemas/collection_seasons'
import type {CollectionWords, Noun} from '../../lib/collectionWords'

/** The words and select options of a collection's Seasons dialog, which the Move dialog also names its changes in. */

/** A creator's videos, or an artist's tracks or music videos, and what the collection calls its seasons. */
export type Words = {creator: string, channel: string, video: string, videos: string, creators: string, season: Noun, episode: Noun, inSeason: string}
export const dialogWords = (collection: CollectionWords, view: CollectionSeasonsRead | undefined): Words => ({
    // What the collection calls its creator and what its lists hold, such as an artist's music videos.
    // Shown once the view is there, which brings the words.
    creator: view?.creatorNames.singular ?? '', creators: view?.creatorNames.plural ?? '', channel: view?.channelNames.singular ?? '',
    video: view?.mediaNames.singular ?? '', videos: view?.mediaNames.plural ?? '',
    season: collection.season, episode: collection.episode, inSeason: collection.inSeason,
})

/** What the collection's Site calls its lists, all its types of list together, such as "albums and playlists" on
 * SoundCloud, as the creator's: creator playlists, so they are not taken for the collection's own seasons, which the
 * dialog always calls seasons (or what the collection's type calls them, such as albums). And the season of the
 * videos in none of them. */
export type ListNames = Names & {looseSeason: string}
export const namesOf = (view: CollectionSeasonsRead, looseSeason: string): ListNames => ({...view.creatorListNames, looseSeason})


export async function readSeasons(response: Response): Promise<CollectionSeasonsRead> {
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : `Could not load them (HTTP ${response.status})`)
    }
    return CollectionSeasonsReadSchema.parse(await response.json())
}


/** What one source of a collection is, a feed or a list: a season of its own, part of the collection, or off. */
export type SourceRole = 'season' | 'part' | 'off'

/** The registries of the dialog's choices, in the words of the collection's Site. */
export function registries(names: ListNames, words: Words, view: CollectionSeasonsRead) {
    const own = `${capitalized(words.season.a)} of its own`
    return {
        // What each source is: one choice each, for a feed and a list alike.
        role: createSelectRegistry(`SourceRole-${words.season.a}`, {
            season: {label: own, help: `Its ${words.videos} are ${words.season.a} named after it.`},
            part: {label: 'Part of the collection', help: `Its ${words.videos} go where the rest of the collection goes.`},
            off: {label: 'Off', help: `The collection leaves its ${words.videos} out.`},
        } as Record<SourceRole, {label: string, help: string}>),
        // One for each kind of list of the Site, such as a SoundCloud artist's albums and their playlists.
        newLinks: (kind: ListKind) => createSelectRegistry(`NewLinkSeasons-${kind.key}-${kind.names.singular}-${words.season.a}`, {
            ask: {label: 'Ask me', help: `VODLoft sends a message, and the new ${words.creator} ${kind.names.singular} waits here for you to switch it on.`},
            add: {label: own, help: `A new ${words.creator} ${kind.names.singular} becomes ${words.season.a} of its own right away.`},
            contents: {label: 'Part of the collection', help: `The ${words.videos} of a new ${words.creator} ${kind.names.singular} join the collection right away, without ${words.season.a} of their own.`},
            ignore: {label: 'Skip it', help: `A new ${words.creator} ${kind.names.singular} stays off. You can switch it on here.`},
        }),
        // What the collection does with the videos of other creators in its lists.
        guests: createSelectRegistry(`OutsideVideos-${words.videos}-${names.plural}`, {
            add: {label: 'Include them', help: `They join the collection where the rest of their ${names.singular} goes. Switching the ${names.singular} off removes them again, files and all. When the ${words.creator} takes a downloaded one out, Home asks whether to keep it.`},
            leave_out: {label: 'Leave them out', help: `${capitalized(names.a)} only takes the ${words.videos} the collection has itself.`},
        }),
        // Where what is part of the collection goes: one season, or a season per upload year.
        rest: createSelectRegistry(`RestSeasons-${words.season.singular}`, {
            one_season: {label: `One ${words.season.singular}`, help: ''},
            by_year: {label: `${capitalized(words.season.a)} per year`, help: `Every ${words.video} goes to the ${words.season.singular} of its upload year.`},
        }),
        // How the collection groups the videos that are part of it, as a Move cause names the setting's values.
        grouping: createSelectRegistry(`LooseVideos-${words.season.singular}-${view.channelSeasonNames.everything}`, {
            everything: {label: `One ${words.season.singular}, also holding what has ${words.season.a} of its own`, help: ''},
            one_season: {label: `One ${words.season.singular}`, help: ''},
            by_year: {label: `${capitalized(words.season.a)} per year`, help: ''},
        } as Record<LooseVideos, {label: string, help: string}>),
        // What the collection does with a video in several of its seasons, such as a track on several albums.
        repeat: createSelectRegistry(`RepeatVideos-${words.season.singular}-${words.inSeason}-${words.episode.singular}`, {
            one_season: {
                label: `Include it only ${words.inSeason} the first ${words.season.singular}`,
                help: `It gets one place, ${words.inSeason} the first of those ${words.season.plural} in the order below.`,
            },
            each_season: {
                label: `Include it ${words.inSeason} each ${words.season.singular}`,
                help: `It is ${words.inSeason} each of them, with files of its own, so every ${words.season.singular} is whole.`,
            },
        }),
    }
}
