import {createSelectRegistry} from '../utils/selectRegistry'

export const NewSectionActionReg = createSelectRegistry('NewSectionAction', {
    ask: {label: 'Ask me', help: 'Sends a message, and shows the new playlist or show on the channel page with the choices.'},
    main: {label: 'Add it as a season', help: 'A new playlist becomes a season of the channel\'s own collection. A show with its own seasons gets a collection of its own.'},
    own: {label: 'Add it as a collection', help: 'Each new playlist or show becomes a collection of its own.'},
    ignore: {label: 'Ignore it', help: 'It is only listed on the channel page.'},
})
