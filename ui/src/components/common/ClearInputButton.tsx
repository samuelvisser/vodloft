import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import './ClearInputButton.css'

/** An "×" inside a text or search field that empties it. Render it only while the field has text. */
export function ClearInputButton({onClear, label = 'Clear'}: {onClear: () => void; label?: string}) {
    return (
        <button type="button" className="clear-input-button" onClick={onClear} aria-label={label} title={label}>
            <FontAwesomeIcon icon={faIcon('fass', 'xmark')} aria-hidden="true"/>
        </button>
    )
}
