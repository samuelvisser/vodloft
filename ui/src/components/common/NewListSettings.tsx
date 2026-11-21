import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import SimpleSelect from './SimpleSelect'
import {faIcon} from '../../icons/faIcon'
import type {ListKind} from '../../types/creator'
import type {SelectRegistry} from '../../utils/selectRegistry'
import './NewListSettings.css'

type Props = {
    /** The kinds of list, in the order their Sites give them, such as an artist's albums and their playlists. */
    kinds: readonly ListKind[]
    /** What happens with a new list of a kind, when it has a setting. */
    valueOf: (kind: ListKind) => string | undefined
    onChange: (kind: ListKind, value: string) => void
    /** The choices for one kind. */
    registryFor: (kind: ListKind) => SelectRegistry<any>
    /** The value a kind shows until it has one. */
    fallback: string
    idPrefix: string
}

/** What happens with each kind of list a creator adds later, one row each, next to each other in a column: a Site
 * that tells an artist's albums from their playlists has a row for each. */
export default function NewListSettings({kinds, valueOf, onChange, registryFor, fallback, idPrefix}: Props) {
    const labels = kinds.flatMap((kind) => registryFor(kind).options.map((option) => option.label))
    // A creator on several Sites has a row for each kind on each Site, named with its Site.
    const severalSites = new Set(kinds.map((kind) => kind.siteKey)).size > 1
    // A single row is named by the heading above it already, so it shows only what its choice does.
    const single = kinds.length === 1
    return (
        <div className="new-list-settings" role="list">
            {kinds.map((kind) => {
                const registry = registryFor(kind)
                const value = valueOf(kind) ?? fallback
                const id = `${idPrefix}-${kind.siteKey ? `${kind.siteKey}-` : ''}${kind.key}`
                return (
                    <div key={id} className="new-list-setting" role="listitem">
                        <span className="new-list-setting-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'list')}/></span>
                        <div className="new-list-setting-copy">
                            <label htmlFor={id} className={single ? 'sr-only' : undefined}><b>New {severalSites ? `${kind.siteName} ` : ''}{kind.names.singular}</b></label>
                            <span>{registry.getHelp(value)}</span>
                        </div>
                        <div className="new-list-setting-choice">
                            <SimpleSelect
                                inputId={id} registry={registry} value={value} fitLabels={labels}
                                onChange={(chosen) => onChange(kind, String(chosen))}
                            />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
