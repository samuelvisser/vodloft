/** What a collection calls its seasons and episodes, by its type: a Music collection has albums, and tracks or music
 *  videos. Every page about a collection, its episodes or their files takes its words from here. */

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

/** Whether what is meant is sound only, such as the files of a Music Local Media Profile or the tracks on Bandcamp,
 *  or video, such as the videos of a YouTube channel. */
export type MediaKind = 'audio' | 'video'

function noun(one: string, many: string, article: 'a' | 'an' = 'a'): Noun {
    const upper = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)
    return {one, many, One: upper(one), Many: upper(many), a: `${article} ${one}`}
}

const SEASON = noun('season', 'seasons')
const EPISODE = noun('episode', 'episodes', 'an')
const ALBUM = noun('album', 'albums', 'an')
const TRACK = noun('track', 'tracks')
const MUSIC_VIDEO = noun('music video', 'music videos')

function words(season: Noun, episode: Noun): CollectionWords {
    return {
        season, episode,
        count: (count, counted = episode) => `${count.toLocaleString()} ${count === 1 ? counted.one : counted.many}`,
    }
}

const SHOW_WORDS = words(SEASON, EPISODE)
const TRACK_WORDS = words(ALBUM, TRACK)
const MUSIC_VIDEO_WORDS = words(ALBUM, MUSIC_VIDEO)

/** The words for a collection type. A Music collection's episodes are tracks when they are sound, and music videos
 *  when they are video. */
export function collectionWords(type: string | null | undefined, kind: MediaKind = 'video'): CollectionWords {
    if (type !== 'music') return SHOW_WORDS
    return kind === 'audio' ? TRACK_WORDS : MUSIC_VIDEO_WORDS
}

interface WordedCollection {
    type?: string | null
    site?: { audio?: boolean } | null
}

/** The words for the files of a collection, kept by the Local Media Profiles of these types that it is offered:
 *  tracks when only Music profiles, which keep sound, are, and otherwise what the collection holds. */
export function fileWordsFor(collection: WordedCollection | null | undefined, profileTypes: readonly string[] | undefined): CollectionWords {
    const audio = !!profileTypes?.length && profileTypes.every((type) => type === 'music')
    return wordsFor(collection, audio ? 'audio' : undefined)
}

/** The words for a collection, as its Site has it: the episodes of a Music collection on a Site with sound only,
 *  such as Bandcamp, are tracks. Pass ``audio`` where the files are meant, which a Music Local Media Profile
 *  keeps as sound. */
export function wordsFor(collection: WordedCollection | null | undefined, kind?: MediaKind): CollectionWords {
    return collectionWords(collection?.type, kind ?? (collection?.site?.audio ? 'audio' : 'video'))
}
