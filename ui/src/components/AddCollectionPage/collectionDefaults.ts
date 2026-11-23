import type {CollectionDetailsRead} from '../../types/schemas/source'
import type {DailywireShowRead} from '../../types/schemas/dailywire_show'
import {CollectionTypeReg, EpisodeIdentifierReg, type CollectionTypeValue, type EpisodeIdentifierValue} from '../../types/collection'

/** The type and episode identification VODLoft suggests for a collection to add. Empty when it has no suggestion. */
export type CollectionDefaults = {
    type: CollectionTypeValue | ''
    episodeIdentifier: EpisodeIdentifierValue | ''
}

/**
 * At a Source that lists its episodes: the type the backend guessed, from the name or because it is music. One list of
 * a creator's, such as a playlist or an album, is the collection's one season, so it is numbered in the list's order.
 * Otherwise music is seasonal, its albums being the seasons. A series is numbered by the Source's own seasons when it
 * has them, and a podcast or a series without seasons by date.
 */
export function listedCollectionDefaults(details: CollectionDetailsRead, list = false): CollectionDefaults {
    const type = CollectionTypeReg.normalize(details.probableCollectionType) ?? CollectionTypeReg.Enum.series
    return {
        type,
        episodeIdentifier: list ? EpisodeIdentifierReg.Enum.numbered
            : type === CollectionTypeReg.Enum.music || (type === CollectionTypeReg.Enum.series && details.seasons.length)
            ? EpisodeIdentifierReg.Enum.seasonal
            : EpisodeIdentifierReg.Enum.date_based,
    }
}

/** A show VODLoft walks itself: what the show's own details suggest, and a series always by its seasons. */
export function dailywireShowDefaults(show: DailywireShowRead): CollectionDefaults {
    const type = CollectionTypeReg.normalize(show.probableCollectionType) ?? ''
    return {
        type,
        episodeIdentifier: type === CollectionTypeReg.Enum.series
            ? EpisodeIdentifierReg.Enum.seasonal
            : (EpisodeIdentifierReg.normalize(show.probableEpisodeIdentification) ?? ''),
    }
}
