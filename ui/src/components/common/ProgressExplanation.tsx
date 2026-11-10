import {useCallback, useId, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import AnchoredNote from './AnchoredNote'
import './ProgressVisual.css'
import {faIcon} from '../../icons/faIcon'

export default function ProgressExplanation({detail, buttonClassName = 'icon-btn'}: {
    detail: string
    buttonClassName?: string
}) {
    const [open, setOpen] = useState(false)
    const id = useId()
    const triggerRef = useRef<HTMLButtonElement>(null)
    const close = useCallback(() => setOpen(false), [])

    return <span className="vl-progress-explanation">
        <button
            ref={triggerRef}
            type="button"
            className={buttonClassName}
            aria-label="Progress details"
            aria-expanded={open}
            aria-controls={id}
            onClick={event => {
                event.stopPropagation()
                setOpen(value => !value)
            }}
        >
            <FontAwesomeIcon icon={faIcon('fass', 'circle-info')}/>
        </button>
        {open && <AnchoredNote id={id} anchorRef={triggerRef} onClose={close}>{detail}</AnchoredNote>}
    </span>
}
