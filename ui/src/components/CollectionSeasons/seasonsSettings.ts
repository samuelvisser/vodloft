import {createSelectRegistry} from '../../utils/selectRegistry'
import {capitalized, type ListKind} from '../../types/creator'
import type {Names} from '../../types/schemas/source'
import {CollectionSeasonsReadSchema, type ChannelSeason, type CollectionSeasonsRead} from '../../types/schemas/collection_seasons'
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
 * SoundCloud, as the creator's: creator playlists, so they are not taken for the collection's own seasons, which a
 * YouTube channel collection also calls playlists. And the season of the videos in none of them. */
export type ListNames = Names & {looseSeason: string}
export const namesOf = (view: CollectionSeasonsRead, looseSeason: string): ListNames => ({...view.creatorListNames, looseSeason})


export async function readSeasons(response: Response): Promise<CollectionSeasonsRead> {
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : `Could not load them (HTTP ${response.status})`)
    }
    return CollectionSeasonsReadSchema.parse(await response.json())
}


/** The registries of the dialog's selects, in the words of the collection's Site. */
export function registries(names: ListNames, words: Words, view: CollectionSeasonsRead) {
    const outside = {
        leave_out: {label: 'Only include media already in the collection', help: `${capitalized(names.a)} only takes the ${words.videos} the collection's own link has.`},
        add: {label: 'Include media that is not in the collection', help: `They join the collection in their ${names.singular}'s ${words.season.singular} in VODLoft. Switching off ${names.a} or this setting removes them again, files and all. When the ${words.creator} takes a downloaded one out, Home asks whether to keep it.`},
        only: {label: `Include only what the ${names.plural} contain`, help: `The collection holds nothing but the ${words.videos} of its ${names.plural}, also other ${words.creators}', and you can add links of your own, from any site. Its own ${words.videos} in no ${names.singular} leave.`},
    }
    return {
        mode: createSelectRegistry(`LinkSeasonMode-${names.plural}`, {
            all: {label: `Every ${names.singular}`, help: `Every ${names.singular}, also the ones to come, is ${words.season.a} in VODLoft.`},
            selected: {label: `Only the ${names.plural} I pick`, help: `Only the ${names.plural} switched on below are ${words.season.plural} in VODLoft.`},
        }),
        // One for each kind of list of the Site, such as a SoundCloud artist's albums and their playlists.
        newLinks: (kind: ListKind) => createSelectRegistry(`NewLinkSeasons-${kind.key}-${kind.names.singular}-${words.season.a}`, {
            ask: {label: 'Ask me', help: `VODLoft sends a message, and the new ${words.creator} ${kind.names.singular} waits here for you to switch it on.`},
            add: {label: `Make it ${words.season.a} in VODLoft`, help: `A new ${words.creator} ${kind.names.singular} becomes ${words.season.a} in VODLoft right away.`},
            ignore: {label: 'Always skip it', help: `A new ${words.creator} ${kind.names.singular} stays off. You can switch it on here.`},
        }),
        // What the channel's own season holds, by the name it then has.
        channel: createSelectRegistry(`ChannelSeason-${view.channelSeasonNames.everything}-${view.channelSeasonNames.unlisted}-${names.plural}`, {
            everything: {
                label: `Everything, as ${view.channelSeasonNames.everything}`,
                help: `Every ${words.video} of the feeds is in ${view.channelSeasonNames.everything}, also the ones in ${names.a} that is ${words.season.a} in VODLoft.`,
            },
            unlisted: {
                label: `What is in no ${names.singular}, as ${view.channelSeasonNames.unlisted}`,
                help: `${capitalized(words.videos)} in ${names.a} that is ${words.season.a} in VODLoft are only there.`,
            },
        } as Record<ChannelSeason, {label: string, help: string}>),
        layout: createSelectRegistry(`ListLayout-${names.plural}-${words.creator}-${words.season.a}`, {
            season_each: {label: `${capitalized(words.season.a)} per ${names.singular}`, help: `Each ${names.singular} is ${words.season.a} in VODLoft, or shares one with the ${names.plural} you put together below.`},
            by_year: {label: `Together in ${words.season.plural} by year`, help: `The ${names.plural} still decide which ${words.videos} are in, but every ${words.video} goes to the ${words.season.singular} of its year, as do the ${words.videos} in no ${names.singular}. When you save, VODLoft offers to move the downloaded ones, files and all.`},
        }),
        // A collection made from one list: the list's one season, or a season per upload year.
        listSeasons: createSelectRegistry(`ListSeasons-${words.season.singular}-${words.videos}`, {
            one_season: {
                label: `One ${words.season.singular}`,
                help: `Every ${words.video} is ${words.inSeason} one ${words.season.singular}, named after the collection, in the order of the collection's link.`,
            },
            by_year: {
                label: `${capitalized(words.season.a)} per year`,
                help: `Every ${words.video} goes to the ${words.season.singular} of its upload year. When you save, VODLoft offers to move the downloaded ones, files and all.`,
            },
        }),
        loose: createSelectRegistry(`LooseVideos-${names.looseSeason}`, {
            one_season: {label: `One ${words.season.singular}, ${names.looseSeason}`, help: `They share one ${words.season.singular}, shown before the ${names.plural}.`},
            by_year: {label: `${capitalized(words.season.a)} per year`, help: `They get ${words.season.a} per upload year, with the ${names.plural} between them by date.`},
        }),
        // Whether a list is a season of its own, or only adds its videos to the collection's other seasons.
        placement: createSelectRegistry(`ListPlacement-${words.season.singular}-${words.videos}`, {
            season: {label: `${capitalized(words.season.a)} of its own`, help: `Its ${words.videos} are ${words.season.a} named after it.`},
            contents: {label: 'Contents only', help: `Its ${words.videos} join the other ${words.season.plural}, where ${words.videos} in no ${names.singular} go.`},
        }),
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
        outside: createSelectRegistry(
            `OutsideVideos-${names.plural}-${view.listsPlaylists}-${view.linksOnlyOffered}`,
            // Holding only the playlists is offered where the Source can hold a collection of links.
            (view.linksOnlyOffered ? outside : {leave_out: outside.leave_out, add: outside.add}) as typeof outside,
        ),
    }
}

