import {createSelectRegistry, SelectRegistry} from "../utils/selectRegistry";
import {CollectionRead} from "./schemas/collection";
import {useMemo} from "react";

// ShowType
export const CollectionTypeReg = createSelectRegistry("CollectionType", {
    podcast: {label: "Podcast", help: "Episodes identified by date or number"},
    series: {label: "Series", help: "Episodic series without podcast semantics"},
    music: {label: "Music", help: "An artist's music: albums of tracks or music videos"},
});
export type CollectionTypeValue = (typeof CollectionTypeReg)["values"][number];


// EpisodeIdentifier: how a collection identifies its episodes
export const EpisodeIdentifierReg = createSelectRegistry("EpisodeIdentifier", {
    numbered: {label: "Numbered", help: "Parse 'Ep. N' from the title"},
    date_based: {label: "Date-based", help: "Use release date as identity"},
    seasonal: {label: "Seasonal", help: "Parse 'S01E01' from the order of episodes within the season"},
});
export type EpisodeIdentifierValue = (typeof EpisodeIdentifierReg)["values"][number];

/** The same choices for a Music collection, whose seasons are its albums. */
const MusicEpisodeIdentifierReg = createSelectRegistry("MusicEpisodeIdentifier", {
    numbered: {label: "Numbered", help: "Parse 'Ep. N' from the title"},
    date_based: {label: "Date-based", help: "Use release date as identity"},
    seasonal: {label: "By album", help: "Groups the tracks by album, numbered in the album's order"},
});

/** The episode identifications, in the words of a collection of the type: "By album" for Music. */
export function episodeIdentifierRegFor(type: string | null | undefined): typeof EpisodeIdentifierReg {
    return type === CollectionTypeReg.Enum.music ? MusicEpisodeIdentifierReg as typeof EpisodeIdentifierReg : EpisodeIdentifierReg;
}

/**
 * Advice for a Music collection that isn't identified by album, which suits music of several albums better. A
 * collection that is one album, such as one made from an album or a playlist, has nothing to group: ``oneAlbum``.
 */
export function musicIdentificationAdvice(
    type: string | null | undefined, identifier: string | null | undefined, oneAlbum = false,
): string | null {
    return type === CollectionTypeReg.Enum.music && !oneAlbum && identifier && identifier !== EpisodeIdentifierReg.Enum.seasonal
        ? "For a Music collection, By album is always the better choice: the tracks are grouped by album, in the album's order."
        : null;
}

// EpisodeOrder: which way a collection lists its episodes, within each season for a seasonal collection
export const EpisodeOrderReg = createSelectRegistry("EpisodeOrder", {
    newest_first: {label: "Newest first"},
    oldest_first: {label: "Oldest first"},
});
export type EpisodeOrderValue = (typeof EpisodeOrderReg)["values"][number];

/** How the Library lists its Collections. */
export const LibraryCollectionSortReg = createSelectRegistry("LibraryCollectionSort", {
    recently_used: {label: "Recently used"},
    often_used: {label: "Often used"},
    name: {label: "Name"},
    release_date: {label: "Release date"},
    added_at: {label: "Added at"},
});
export type LibraryCollectionSortValue = (typeof LibraryCollectionSortReg)["values"][number];

/** Build a select registry for Collections from an array (no memoization). */
export function buildCollectionSelectRegistry(collections: readonly CollectionRead[] | undefined | null): SelectRegistry {
    const spec: Record<string, { label: string }> = {}
    const values: string[] = []
    if (Array.isArray(collections)) {
        for (const s of collections) {
            const id = String(s.id)
            const name = s.title
            spec[id] = {label: String(name)}
            values.push(id)
        }
    }
    return createSelectRegistry('Collection', spec, values)
}

/** React hook: memoized select registry for Collections */
export function useCollectionSelectRegistry(collections: readonly CollectionRead[] | undefined | null): SelectRegistry {
    return useMemo((): SelectRegistry => buildCollectionSelectRegistry(collections), [collections])
}
