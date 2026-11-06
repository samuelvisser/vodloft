import {createSelectRegistry, SelectRegistry} from "../utils/selectRegistry";
import {CollectionRead} from "./schemas/collection";
import {useMemo} from "react";

// ShowType
export const CollectionTypeReg = createSelectRegistry("CollectionType", {
    podcast: {label: "Podcast", help: "Episodes identified by date or number"},
    series: {label: "Series", help: "Episodic series without podcast semantics"},
});
export type CollectionTypeValue = (typeof CollectionTypeReg)["values"][number];


// EpisodeIdentifier: how a collection identifies its episodes
export const EpisodeIdentifierReg = createSelectRegistry("EpisodeIdentifier", {
    numbered: {label: "Numbered", help: "Parse 'Ep. N' from the title"},
    date_based: {label: "Date-based", help: "Use release date as identity"},
    seasonal: {label: "Seasonal", help: "Parse 'S01E01' from the order of episodes within the season"},
});
export type EpisodeIdentifierValue = (typeof EpisodeIdentifierReg)["values"][number];

// EpisodeOrder: which way a collection lists its episodes, within each season for a seasonal collection
export const EpisodeOrderReg = createSelectRegistry("EpisodeOrder", {
    newest_first: {label: "Newest first"},
    oldest_first: {label: "Oldest first"},
});
export type EpisodeOrderValue = (typeof EpisodeOrderReg)["values"][number];

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
