import {useId} from 'react'
import Switch from 'react-switch'
import ExistingFilesSetup, {type ExistingFilesSetupValue} from '../ExistingFiles/ExistingFilesSetup'
import '../ExistingFiles/ExistingFiles.css'

export type ExistingFilesChoice = ExistingFilesSetupValue & {enabled: boolean}

type Props = {
    value: ExistingFilesChoice
    onChange: (value: ExistingFilesChoice) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
}

/** The deepest folder of an output template that has no variable in it, like the server's default. */
export function defaultExistingFilesFolder(outputTemplate: string | undefined): string {
    const template = outputTemplate ?? ''
    const cut = Math.min(...['{{', '{%', '{#'].map((marker) => {
        const index = template.indexOf(marker)
        return index < 0 ? template.length : index
    }))
    const fixed = template.slice(0, cut)
    const folder = fixed.includes('/') ? fixed.slice(0, fixed.lastIndexOf('/')) : ''
    return folder.startsWith('/downloads') ? folder : '/downloads'
}

export default function ExistingFilesStep({value, onChange, onBack, onContinue, onCancel}: Props) {
    const toggleId = useId()
    return (
        <form onSubmit={(event) => { event.preventDefault(); onContinue() }}>
            <div className="form-row">
                <label htmlFor={toggleId}>I already have files for this collection</label>
                <Switch
                    id={toggleId}
                    checked={value.enabled}
                    onChange={(checked) => onChange({...value, enabled: checked})}
                    onColor="#0ea5e9"
                    offColor="#d1d5db"
                    uncheckedIcon={false}
                    checkedIcon={false}
                    aria-describedby={`${toggleId}-help`}
                />
                <div className="help" id={`${toggleId}-help`}>
                    VODLoft can adopt files you downloaded before, with another program or an older template. Once the
                    episodes are indexed it looks for them and asks you to review what it found. The Download Profile
                    waits until you are done, then only downloads the episodes without a file.
                </div>
            </div>
            {value.enabled && (
                <ExistingFilesSetup value={value} onChange={(setup) => onChange({...value, ...setup})}/>
            )}
            <div className="actions">
                <button type="button" className="btn" onClick={onBack}>Back</button>
                <input type="submit" className="btn btn-primary" value="Continue" disabled={value.enabled && !value.folder.trim()}/>
                <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            </div>
        </form>
    )
}
