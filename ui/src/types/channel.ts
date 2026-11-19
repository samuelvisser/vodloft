import {createSelectRegistry} from '../utils/selectRegistry'

/** A Site's word for a channel, such as host, at the start of a sentence or a label. */
export function capitalized(label: string): string {
    return label.slice(0, 1).toUpperCase() + label.slice(1)
}

const newSectionActionRegs = new Map<string, ReturnType<typeof makeNewSectionActionReg>>()

function makeNewSectionActionReg(label: string) {
    return createSelectRegistry(`NewSectionAction-${label}`, {
        ask: {label: 'Ask me', help: `Sends a message, and shows the new one on the ${label}'s page with the choices.`},
        main: {label: 'Add it as a season', help: `It becomes a season of the ${label}'s own collection. A show with seasons of its own gets a collection of its own.`},
        own: {label: 'Add it as a collection', help: 'Each new one becomes a collection of its own.'},
        ignore: {label: 'Ignore it', help: `It is only listed on the ${label}'s page.`},
    })
}

/** What to do when a channel adds a playlist, show or album, in the words of its Site, such as host on The Daily Wire. */
export function newSectionActionReg(label: string) {
    let registry = newSectionActionRegs.get(label)
    if (!registry) {
        registry = makeNewSectionActionReg(label)
        newSectionActionRegs.set(label, registry)
    }
    return registry
}
