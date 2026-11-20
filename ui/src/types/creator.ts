import {createSelectRegistry} from '../utils/selectRegistry'
import {collectionWords} from '../lib/collectionWords'
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

/** The name a section goes by among ``sections``: its type's, but where several types of feed are shown together,
 * the feeds' kind, "feeds", as each feed is named after its type already. Lists keep their Site's words. */
export function groupNames<S extends {kind: string, type: string, names: Names, kindNames: Names}>(section: S, sections: readonly S[]): Names {
    if (section.kind !== 'feed') return section.names
    const feedTypes = new Set(sections.filter((other) => other.kind === 'feed').map((other) => other.type))
    return feedTypes.size > 1 ? section.kindNames : section.names
}

/** What a creator is, for a label: "YouTube creator" on one Site, "Creator on YouTube and The Daily Wire" on several. */
export function creatorKindText(creator: {kind: string, accounts: {site: {name: string}}[]}): string {
    const names = [...new Set(creator.accounts.map((account) => account.site.name))]
    if (names.length < 2) return creator.kind
    return `${capitalized(creator.kind)} on ${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** One kind of list a creator's Sites have, such as a SoundCloud artist's albums or their playlists, which has a
 * setting of its own for what happens with a new one: what the Sites call it, and whether it can be a season of the
 * creator's own collection. */
export type ListKind = {key: string, names: Names, seasons: boolean, siteKey?: string, siteName?: string}

const newListActionRegs = new Map<string, ReturnType<typeof makeNewListActionReg>>()

function makeNewListActionReg(label: string, kind: ListKind, music: boolean) {
    // An artist's lists are albums of their own collection.
    const {season, episode} = collectionWords(music ? 'music' : null)
    return createSelectRegistry(`NewListAction-${label}-${music}-${kind.key}-${kind.names.plural}-${kind.seasons}`, {
        ask: {label: 'Ask me', help: `Sends a message and shows the new ${kind.names.singular} on the ${label}'s Edit page with the choices.`},
        // Only where the kind's lists can be seasons, unlike The Daily Wire's shows.
        ...(kind.seasons ? {season: {
            label: `Add it as ${season.a}`,
            help: `New ${kind.names.plural} become ${season.plural} of the ${label}'s own collection.`,
        }, loose: {
            label: 'Add its contents',
            help: `The ${episode.plural} of new ${kind.names.plural} join the ${label}'s own collection, where its ${episode.plural} in no ${kind.names.singular} go.`,
        }} : {}),
        own: {label: 'Add it as a collection', help: `Each new ${kind.names.singular} becomes a collection of its own.`},
        ignore: {
            label: 'Exclude it from library',
            help: `The new ${kind.names.singular} is only listed on the ${label}'s Edit page, and keeps its ${episode.plural} out of the ${label}'s collections.`,
        },
    } as Record<'ask' | 'season' | 'loose' | 'own' | 'ignore', {label: string, help: string}>)
}

/** What to do when a creator adds a list of one kind, such as a playlist, show or album. "Add it as a season" is only
 * there when the kind's lists can be seasons; for a ``music`` artist it is "Add it as an album". */
export function newListActionReg(label: string, kind: ListKind, music = false) {
    const key = `${label}\n${music}\n${kind.key}\n${kind.names.plural}\n${kind.seasons}`
    let registry = newListActionRegs.get(key)
    if (!registry) {
        registry = makeNewListActionReg(label, kind, music)
        newListActionRegs.set(key, registry)
    }
    return registry
}
