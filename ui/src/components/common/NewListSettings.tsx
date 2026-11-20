import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import SimpleSelect from './SimpleSelect'
import {faIcon} from '../../icons/faIcon'
import type {ListKind} from '../../types/creator'
import type {SelectRegistry} from '../../utils/selectRegistry'
import './NewListSettings.css'

type Props = {
    /** The kinds of list, in the order their Sites give them, such as an artist's albums and their playlists. */
    kinds: readonly ListKind[]
    /** What happens with a new list, by the key of its kind. */
    values: Record<string, string | undefined>
    onChange: (key: string, value: string) => void
    /** The choices for one kind. */
    registryFor: (kind: ListKind) => SelectRegistry<any>
    /** The value a kind shows until it has one. */
    fallback: string
    idPrefix: string
}

/** The kinds' names together, such as "albums and playlists". */
export function listKindNames(kinds: readonly ListKind[]): string {
    const names = kinds.map((kind) => kind.names.plural)
    return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** What happens with each kind of list a creator adds later, one row each, next to each other in a column: a Site
 * that tells an artist's albums from their playlists has a row for each. */
export default function NewListSettings({kinds, values, onChange, registryFor, fallback, idPrefix}: Props) {
    const labels = kinds.flatMap((kind) => registryFor(kind).options.map((option) => option.label))
    return (
        <div className="new-list-settings" role="list">
            {kinds.map((kind) => {
                const registry = registryFor(kind)
                const value = values[kind.key] ?? fallback
                return (
                    <div key={kind.key} className="new-list-setting" role="listitem">
                        <span className="new-list-setting-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'list')}/></span>
                        <div className="new-list-setting-copy">
                            <label htmlFor={`${idPrefix}-${kind.key}`}><b>New {kind.names.plural}</b></label>
                            <span>{registry.getHelp(value)}</span>
                        </div>
                        <div className="new-list-setting-choice">
                            <SimpleSelect
                                inputId={`${idPrefix}-${kind.key}`} registry={registry} value={value} fitLabels={labels}
                                onChange={(chosen) => onChange(kind.key, String(chosen))}
                            />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
