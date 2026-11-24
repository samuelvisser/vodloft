import type {ReactNode} from 'react'
import Switch from 'react-switch'
import './DialogSwitch.css'

/** A choice in a dialog, such as a confirmation's: a small switch beside a bold label and what it does. */
export default function DialogSwitch({checked, onChange, label, help, disabled}: {
    checked: boolean
    onChange: (checked: boolean) => void
    label: ReactNode
    help?: ReactNode
    disabled?: boolean
}) {
    return (
        <label className="dialog-switch">
            <Switch
                checked={checked}
                onChange={onChange}
                disabled={disabled}
                onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                height={18} width={34} handleDiameter={14}
            />
            <span>
                <b>{label}</b>
                {help && <span className="help">{help}</span>}
            </span>
        </label>
    )
}
