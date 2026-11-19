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

/** What a creator's Site can do with a new playlist or show: its name, whether its lists can be seasons of the
 * creator's own collection, and what it calls them. */
export type NewSectionSite = {name: string, linkSeasons: boolean, creatorSections: {many: string}}

const newSectionActionRegs = new Map<string, ReturnType<typeof makeNewSectionActionReg>>()

function makeNewSectionActionReg(label: string, sites: readonly NewSectionSite[]) {
    // A creator on several Sites, such as YouTube and The Daily Wire, says which of their new ones become seasons.
    const several = new Set(sites.map((site) => site.name)).size > 1
    const named = (list: readonly NewSectionSite[]) => [...new Set(list.map((site) => (
        several ? `${site.creatorSections.many} on ${site.name}` : site.creatorSections.many
    )))].join(' and ')
    const seasons = sites.filter((site) => site.linkSeasons)
    const others = sites.filter((site) => !site.linkSeasons)
    const seasonHelp = `New ${named(seasons)} become seasons of the ${label}'s own collection.`
        + (others.length ? ` New ${named(others)} can't be seasons, so each gets a collection of its own.` : '')
    return createSelectRegistry(`NewSectionAction-${label}-${named(seasons)}-${named(others)}`, {
        ask: {label: 'Ask me', help: `Sends a message, and shows the new one on the ${label}'s Edit page with the choices.`},
        // Only where one of the creator's Sites can make its lists seasons, unlike The Daily Wire's shows.
        ...(seasons.length ? {season: {label: 'Add it as a season', help: seasonHelp}} : {}),
        own: {label: 'Add it as a collection', help: 'Each new one becomes a collection of its own.'},
        ignore: {label: 'Ignore it', help: `It is only listed on the ${label}'s Edit page.`},
    } as Record<'ask' | 'season' | 'own' | 'ignore', {label: string, help: string}>)
}

/** What to do when a creator adds a playlist, show or album, in the words of its Sites, such as host on The Daily
 * Wire. "Add it as a season" is only there when one of ``sites`` can make its lists seasons. */
export function newSectionActionReg(label: string, sites: readonly NewSectionSite[]) {
    const key = `${label}\n${sites.map((site) => `${site.name}:${site.linkSeasons}:${site.creatorSections.many}`).join('\n')}`
    let registry = newSectionActionRegs.get(key)
    if (!registry) {
        registry = makeNewSectionActionReg(label, sites)
        newSectionActionRegs.set(key, registry)
    }
    return registry
}
