import type {CollectionDetailsRead} from '../../types/schemas/source'
import {CollectionTypeReg, EpisodeIdentifierReg, type CollectionTypeValue, type EpisodeIdentifierValue} from '../../types/collection'

/** The type and episode identification VODLoft suggests for a collection to add. Empty when it has no suggestion. */
export type CollectionDefaults = {
    type: CollectionTypeValue | ''
    episodeIdentifier: EpisodeIdentifierValue | ''
}

/**
 * At a Source that lists its episodes: the type the backend guessed, from the name or because it is music. Music is
 * always by album, its albums being the seasons; a collection of one album is that one season, in the album's order.
 * Another collection of one list, such as a playlist, has the list as its one season, so it is numbered in the list's
 * order, unless its Site gives it seasons of its own. A series is numbered by the Source's own seasons when it has
 * them. On a Site that numbers its episodes itself, such as The Daily Wire, the rest is numbered by those numbers, and
 * elsewhere a podcast or a series without seasons by date.
 */
export function listedCollectionDefaults(details: CollectionDetailsRead): CollectionDefaults {
    const type = CollectionTypeReg.normalize(details.probableCollectionType) ?? CollectionTypeReg.Enum.series
    const oneList = details.kind === 'list' && !details.seasons.length
    return {
        type,
        episodeIdentifier: type === CollectionTypeReg.Enum.music ? EpisodeIdentifierReg.Enum.seasonal
            : oneList ? EpisodeIdentifierReg.Enum.numbered
            : type === CollectionTypeReg.Enum.series && details.seasons.length ? EpisodeIdentifierReg.Enum.seasonal
            : details.showNumbers ? EpisodeIdentifierReg.Enum.numbered
            : EpisodeIdentifierReg.Enum.date_based,
    }
}
