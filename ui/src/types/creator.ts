import {createSelectRegistry} from '../utils/selectRegistry'

/** A Site's word for a creator, such as host, at the start of a sentence or a label. */
export function capitalized(label: string): string {
    return label.slice(0, 1).toUpperCase() + label.slice(1)
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
