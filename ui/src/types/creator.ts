/** A word the backend gives in lower case, such as host, at the start of a sentence or a label. */
export function capitalized(label: string): string {
    return label.slice(0, 1).toUpperCase() + label.slice(1)
}

import type {Names} from './schemas/source'

function joined(words: string[], conjunction: string): string {
    const unique = [...new Set(words)]
    return unique.length < 2 ? unique[0] ?? '' : `${unique.slice(0, -1).join(', ')} ${conjunction} ${unique[unique.length - 1]}`
}

/** One name for several section types, such as "album or playlist" and "albums and playlists" for SoundCloud's
 * lists, or "album, playlist or list" for three. */
export function joinedNames(names: Names[]): Names {
    const singular = joined(names.map((name) => name.singular), 'or')
    // "an album or playlist" takes the first one's article.
    const article = names[0] ? names[0].a.slice(0, names[0].a.length - names[0].singular.length) : ''
    return {singular, plural: joined(names.map((name) => name.plural), 'and'), a: `${article}${singular}`}
}

/** What a creator is, for a label: "YouTube creator" on one Site, "Creator on YouTube and The Daily Wire" on several. */
export function creatorKindText(creator: {kind: string, accounts: {site: {name: string}}[]}): string {
    const names = [...new Set(creator.accounts.map((account) => account.site.name))]
    // Without one Site before it, the kind starts the label, such as "Artist" for one on several Sites.
    if (names.length < 2) return capitalized(creator.kind)
    return `${capitalized(creator.kind)} on ${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** One kind of list a channel's Site has, such as a SoundCloud account's albums or its playlists, which has a setting
 * of its own for what happens with a new one. */
export type ListKind = {key: string, names: Names}
