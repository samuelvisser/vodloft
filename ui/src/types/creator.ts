import {createSelectRegistry} from '../utils/selectRegistry'

/** A Site's word for a creator, such as host, at the start of a sentence or a label. */
export function capitalized(label: string): string {
    return label.slice(0, 1).toUpperCase() + label.slice(1)
}

/** A Site's word for one thing with its article, such as "an album" or "a playlist". */
export function withArticle(word: string): string {
    return `${/^[aeiou]/i.test(word) ? 'an' : 'a'} ${word}`
}

type Names = {one: string, many: string}

function joined(words: string[], conjunction: string): string {
    const unique = [...new Set(words)]
    return unique.length < 2 ? unique[0] ?? '' : `${unique.slice(0, -1).join(', ')} ${conjunction} ${unique[unique.length - 1]}`
}

/** One name for several section types, such as "album or playlist" and "albums and playlists" for SoundCloud's
 * lists, or "album, playlist or list" for three. */
export function joinedNames(names: Names[]): Names {
    return {one: joined(names.map((name) => name.one), 'or'), many: joined(names.map((name) => name.many), 'and')}
}

/** The Site's section type a section is: the one it names, or else the Site's first of its kind. */
export function sectionTypeOf<T extends {key: string, kind: string}>(types: T[], section: {type?: string | null, kind: string}): T | undefined {
    return types.find((type) => type.key === section.type) ?? types.find((type) => type.kind === section.kind)
}

/** What the Site calls its lists, all its types of list together, such as "albums and playlists" on SoundCloud. */
export function listNames(types: {kind: string, one: string, many: string}[]): Names {
    return joinedNames(types.filter((type) => type.kind === 'list'))
}

/** What the Site calls the lists and shows its creators add, which VODLoft looks for every day, such as "playlists"
 * on YouTube or "shows" on The Daily Wire. */
export function growingNames(types: {kind: string, one: string, many: string}[]): Names {
    return joinedNames(types.filter((type) => type.kind === 'list' || type.kind === 'show'))
}

/** What the Site calls a section, by its type, such as album; VODLoft's own word for its kind where the Site names
 * none. */
export function sectionName(types: {key: string, kind: string, one: string, many: string}[], section: {type?: string | null, kind: string}): Names {
    return sectionTypeOf(types, section) ?? (section.kind === 'item' ? {one: 'video', many: 'videos'} : {one: section.kind, many: `${section.kind}s`})
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
export type ListKind = {key: string, one: string, many: string, seasons: boolean}

const newListActionRegs = new Map<string, ReturnType<typeof makeNewListActionReg>>()

function makeNewListActionReg(label: string, kind: ListKind, music: boolean) {
    // An artist's lists are albums of their own collection.
    const season = music ? 'album' : 'season'
    return createSelectRegistry(`NewListAction-${label}-${music}-${kind.key}-${kind.many}-${kind.seasons}`, {
        ask: {label: 'Ask me', help: `Sends a message, and shows the new one on the ${label}'s Edit page with the choices.`},
        // Only where the kind's lists can be seasons, unlike The Daily Wire's shows.
        ...(kind.seasons ? {season: {
            label: music ? 'Add it as an album' : 'Add it as a season',
            help: `New ${kind.many} become ${season}s of the ${label}'s own collection.`,
        }} : {}),
        own: {label: 'Add it as a collection', help: `Each new one becomes a collection of its own.`},
        ignore: {label: 'Always skip it', help: `It is only listed on the ${label}'s Edit page.`},
    } as Record<'ask' | 'season' | 'own' | 'ignore', {label: string, help: string}>)
}

/** What to do when a creator adds a list of one kind, such as a playlist, show or album. "Add it as a season" is only
 * there when the kind's lists can be seasons; for a ``music`` artist it is "Add it as an album". */
export function newListActionReg(label: string, kind: ListKind, music = false) {
    const key = `${label}\n${music}\n${kind.key}\n${kind.many}\n${kind.seasons}`
    let registry = newListActionRegs.get(key)
    if (!registry) {
        registry = makeNewListActionReg(label, kind, music)
        newListActionRegs.set(key, registry)
    }
    return registry
}
