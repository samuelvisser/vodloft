/** What a collection calls its seasons and episodes, by its type: a Music collection has albums, and tracks or music
 *  videos. The words come from the backend's collection contracts, so every page, and any other app, names them the
 *  same way; every page about a collection, its episodes or their files takes its words from here. */
import {type CollectionContracts, CollectionContractsSchema} from '../types/schemas/collection_contract'


/** One word in the forms a sentence needs. */
export interface Noun {
    /** Lower case, such as album. */
    singular: string
    /** Lower case plural, such as albums. */
    plural: string
    /** For the start of a sentence, a title or a label, such as Album. */
    Singular: string
    Plural: string
    /** With its article, such as an album. */
    a: string
}

export interface CollectionWords {
    season: Noun
    episode: Noun
    /** The word for being in one of its seasons, such as in a season, or on an album. */
    inSeason: string
    /** An episode is named by its number in its season alone, as an album's tracks are: Track 3, not S01E03. */
    numberedInSeason: boolean
    /** A number with the word it counts, such as 1 track or 12 tracks. */
    count: (count: number, noun?: Noun) => string
}

/** Whether what is meant is sound only, such as the files of a profile for Music that downloads audio only or the tracks on Bandcamp,
 *  or video, such as the videos of a YouTube channel. */
export type MediaKind = 'audio' | 'video'

type BackendNames = {singular: string, plural: string, a: string}

function noun({singular, plural, a}: BackendNames): Noun {
    const upper = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)
    return {singular, plural, Singular: upper(singular), Plural: upper(plural), a}
}

/** A collection's words as the backend gives them, such as a creator's, in the forms a sentence needs. */
export function wordsOf(names: {season: BackendNames, episode: BackendNames, inSeason: string, numberedInSeason?: boolean}): CollectionWords {
    const episode = noun(names.episode)
    return {
        season: noun(names.season), episode, inSeason: names.inSeason, numberedInSeason: names.numberedInSeason ?? false,
        count: (count, counted = episode) => `${count.toLocaleString()} ${count === 1 ? counted.singular : counted.plural}`,
    }
}

const STORAGE_KEY = 'vodloft.collectionContracts'
type Contract = Record<MediaKind, CollectionWords> & {
    downloadsBySeason: boolean, creatorNames: BackendNames | null, profileScope: string, profileScopes: string[],
}
let contracts: {fallback: CollectionWords, types: Map<string, Contract>} | undefined

/** Keep the collection contracts the backend gave, which every function here names things from. */
export function setCollectionContracts(loaded: CollectionContracts) {
    contracts = {
        fallback: wordsOf(loaded.words),
        types: new Map(loaded.types.map((type) => [type.type, {
            video: wordsOf(type.words), audio: wordsOf(type.audioWords), downloadsBySeason: type.downloadsBySeason, creatorNames: type.creatorNames,
            profileScope: type.profileScope, profileScopes: type.profileScopes,
        }])),
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
    // A copy kept by an older VODLoft may not fit any more; then there are no words until the backend answers.
    const parsed = stored ? CollectionContractsSchema.safeParse(JSON.parse(stored)) : null
    if (parsed?.success) setCollectionContracts(parsed.data)
}

/** The words for a collection type, from its contract. A Music collection's episodes are tracks when they are sound,
 *  and music videos when they are video; without a type, VODLoft's own words. */
export function collectionWords(type: string | null | undefined, kind: MediaKind = 'video'): CollectionWords {
    if (!contracts) throw new Error('The collection contracts are not loaded yet')
    return (type ? contracts.types.get(type)?.[kind] : undefined) ?? contracts.fallback
}

/** Whether downloads of a collection type pick its seasons, as for a series or an artist's albums, rather than its
 *  newest episodes, as for a podcast. */
export function downloadsBySeason(type: string): boolean {
    return contractOf(type).downloadsBySeason
}

/** What a collection of the type calls the creator behind it: the type's word, such as artist for Music, or else what
 *  their Site calls its creators. */
export function creatorNamesFor(type: string | null | undefined, siteNames: BackendNames): BackendNames {
    return (type ? contracts?.types.get(type)?.creatorNames : null) ?? siteNames
}

function contractOf(type: string): Contract {
    const contract = contracts?.types.get(type)
    if (!contract) throw new Error(`No collection contract for ${type}`)
    return contract
}

/** What a Local Media Profile can keep to be offered for a collection of the type, such as podcast-and-series or podcast. */
export function profileScopesFor(type: string): string[] {
    return contractOf(type).profileScopes
}

/** What a new Local Media Profile for a collection of the type keeps, such as podcast. */
export function newProfileScope(type: string): string {
    return contractOf(type).profileScope
}

interface WordedCollection {
    type?: string | null
    site?: { audioOnly?: boolean } | null
    /** What the collection's Site calls its seasons, such as playlists in a YouTube channel collection. */
    seasonNames?: BackendNames | null
}

/** The words for the files of a collection, kept by the Local Media Profiles it is offered: tracks when every one of
 *  them is for Music and downloads audio only, and otherwise what the collection holds. */
export function fileWordsFor(
    collection: WordedCollection | null | undefined,
    profiles: readonly {collectionScope?: string | null, preferredFormat?: string | null}[] | undefined,
): CollectionWords {
    const audio = !!profiles?.length && profiles.every((profile) => profile.collectionScope === 'music' && profile.preferredFormat === 'format_audio_only')
    return wordsFor(collection, audio ? 'audio' : undefined)
}

/** The words for a collection, as its Site has it: the episodes of a Music collection on a Site with sound only,
 *  such as Bandcamp, are tracks, and the seasons of a YouTube channel collection are playlists. Pass ``audio`` where the files are meant, which a profile for Music that
 *  downloads audio only keeps as sound. */
export function wordsFor(collection: WordedCollection | null | undefined, kind?: MediaKind): CollectionWords {
    const words = collectionWords(collection?.type, kind ?? (collection?.site?.audioOnly ? 'audio' : 'video'))
    return collection?.seasonNames ? {...words, season: noun(collection.seasonNames)} : words
}
