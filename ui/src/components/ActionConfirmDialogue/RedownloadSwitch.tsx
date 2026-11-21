import {useId, type ReactNode} from 'react'
import Switch from 'react-switch'

import './RedownloadSwitch.css'

type RedownloadSwitchProps = {
    label: ReactNode
    checked: boolean
    onChange: (checked: boolean) => void
    /** What happens with the switch in its current position. */
    help: ReactNode
}

/** The switch of a delete-downloads dialogue that downloads the deleted files again. */
export default function RedownloadSwitch({label, checked, onChange, help}: RedownloadSwitchProps) {
    const id = useId()
    return (
        <div className="form-row">
            <div className="redownload-switch">
                <label htmlFor={id}>{label}</label>
                <Switch
                    id={id}
                    checked={checked}
                    onChange={onChange}
                    onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                />
            </div>
            <div className="help">{help}</div>
        </div>
    )
}
