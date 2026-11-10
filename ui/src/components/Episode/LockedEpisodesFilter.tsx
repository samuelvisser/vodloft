import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'

type LockedEpisodesFilterProps = {
    /** The episodes the list could leave out: those that need an access VODLoft does not have. */
    lockedTotal: number
    shown: boolean
    onChange: (shown: boolean) => void
}

/** One filter chip that shows or hides the episodes VODLoft has no access to, such as members-only videos.
 * Hidden while the collection has none. Episodes the signed-in account can watch are never hidden. */
export default function LockedEpisodesFilter({lockedTotal, shown, onChange}: LockedEpisodesFilterProps) {
    if (lockedTotal === 0) return null
    const what = `${lockedTotal} ${lockedTotal === 1 ? 'episode' : 'episodes'} VODLoft has no access to, such as members-only ones`
    return (
        <div className="filter-chip-group" role="group" aria-label="Filter locked episodes">
            <button
                type="button"
                className="filter-chip filter-chip-locked"
                aria-pressed={shown}
                title={shown ? `Hide the ${what}` : `Show the ${what}`}
                onClick={() => onChange(!shown)}
            >
                <FontAwesomeIcon icon={faIcon('fass', 'lock')} aria-hidden="true"/> Locked
            </button>
        </div>
    )
}
