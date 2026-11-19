/** What a collection calls its seasons and episodes, by its type: a Music collection has albums, and tracks or music
 *  videos. The words come from the backend's collection contracts, so every page, and any other app, names them the
 *  same way; every page about a collection, its episodes or their files takes its words from here. */
import {type CollectionContracts, CollectionContractsSchema} from '../types/schemas/collection_contract'


/** One word in the forms a sentence needs. */
export interface Noun {
    /** Lower case, such as album. */
    one: string
    /** Lower case plural, such as albums. */
    many: string
    /** For the start of a sentence, a title or a label, such as Album. */
    One: string
    Many: string
    /** With its article, such as an album. */
    a: string
}

export interface CollectionWords {
    season: Noun
    episode: Noun
    /** A number with the word it counts, such as 1 track or 12 tracks. */
    count: (count: number, noun?: Noun) => string
}

/** Whether what is meant is sound only, such as the files of a profile for Music tracks or the tracks on Bandcamp,
 *  or video, such as the videos of a YouTube channel. */
export type MediaKind = 'audio' | 'video'

type BackendNames = {one: string, many: string, a: string}

function noun({one, many, a}: BackendNames): Noun {
    const upper = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)
    return {one, many, One: upper(one), Many: upper(many), a}
}

function words(names: {season: BackendNames, episode: BackendNames}): CollectionWords {
    const episode = noun(names.episode)
    return {
        season: noun(names.season), episode,
        count: (count, counted = episode) => `${count.toLocaleString()} ${count === 1 ? counted.one : counted.many}`,
    }
}

const STORAGE_KEY = 'vodloft.collectionContracts'
let contracts: {fallback: CollectionWords, types: Map<string, Record<MediaKind, CollectionWords>>} | undefined

/** Keep the collection contracts the backend gave, which every function here names things from. */
export function setCollectionContracts(loaded: CollectionContracts) {
    contracts = {
        fallback: words(loaded.words),
        types: new Map(loaded.types.map((type) => [type.type, {video: words(type.words), audio: words(type.audioWords)}])),
    }
}

/** Keep what each collection type calls its seasons and episodes, from the public config, before anything renders.
 *  Without it, when the backend could not be reached, the words it gave last time are used. */
export function loadCollectionContracts(loaded: CollectionContracts | undefined) {
    if (loaded) {
        setCollectionContracts(loaded)
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(loaded)) } catch { /* only a convenience */ }
        return
    }
    let stored: string | null = null
    try { stored = localStorage.getItem(STORAGE_KEY) } catch { /* nothing kept */ }
    if (stored) setCollectionContracts(CollectionContractsSchema.parse(JSON.parse(stored)))
}

/** The words for a collection type, from its contract. A Music collection's episodes are tracks when they are sound,
 *  and music videos when they are video; without a type, VODLoft's own words. */
export function collectionWords(type: string | null | undefined, kind: MediaKind = 'video'): CollectionWords {
    if (!contracts) throw new Error('The collection contracts are not loaded yet')
    return (type ? contracts.types.get(type)?.[kind] : undefined) ?? contracts.fallback
}

interface WordedCollection {
    type?: string | null
    site?: { audioOnly?: boolean } | null
}

/** The words for the files of a collection, kept by the Local Media Profiles it is offered, each by what it is
 *  available for: tracks when only profiles for Music tracks, which keep sound, are, and otherwise what the
 *  collection holds. */
export function fileWordsFor(collection: WordedCollection | null | undefined, profileScopes: readonly string[] | undefined): CollectionWords {
    const audio = !!profileScopes?.length && profileScopes.every((scope) => scope === 'music_tracks')
    return wordsFor(collection, audio ? 'audio' : undefined)
}

/** The words for a collection, as its Site has it: the episodes of a Music collection on a Site with sound only,
 *  such as Bandcamp, are tracks. Pass ``audio`` where the files are meant, which a profile for Music tracks
 *  keeps as sound. */
export function wordsFor(collection: WordedCollection | null | undefined, kind?: MediaKind): CollectionWords {
    return collectionWords(collection?.type, kind ?? (collection?.site?.audioOnly ? 'audio' : 'video'))
}
