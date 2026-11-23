import type {CollectionDetailsRead} from '../../types/schemas/source'
import type {DailywireShowRead} from '../../types/schemas/dailywire_show'
import {CollectionTypeReg, EpisodeIdentifierReg, type CollectionTypeValue, type EpisodeIdentifierValue} from '../../types/collection'

/** The type and episode identification VODLoft suggests for a collection to add. Empty when it has no suggestion. */
export type CollectionDefaults = {
    type: CollectionTypeValue | ''
    episodeIdentifier: EpisodeIdentifierValue | ''
}

/**
 * At a Source that lists its episodes: the type the backend guessed, from the name or because it is music. A
 * collection of one list, such as a playlist or an album, has the list as its one season, so it is numbered in the
 * list's order, unless its Site gives it seasons of its own. Otherwise music is seasonal, its albums being the seasons.
 * A series is numbered by the Source's own seasons when it has them, and a podcast or a series without seasons by date.
 */
export function listedCollectionDefaults(details: CollectionDetailsRead): CollectionDefaults {
    const type = CollectionTypeReg.normalize(details.probableCollectionType) ?? CollectionTypeReg.Enum.series
    const oneList = details.kind === 'list' && !details.seasons.length
    return {
        type,
        episodeIdentifier: oneList ? EpisodeIdentifierReg.Enum.numbered
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
