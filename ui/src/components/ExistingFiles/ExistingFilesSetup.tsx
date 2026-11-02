import {useId} from 'react'
import FolderField from './FolderField'

export type ExistingFilesSetupValue = {
    folder: string
    template: string
}

type Props = {
    value: ExistingFilesSetupValue
    onChange: (value: ExistingFilesSetupValue) => void
    disabled?: boolean
}

/** Where the existing files are, and optionally how they were named. */
export default function ExistingFilesSetup({value, onChange, disabled}: Props) {
    const templateId = useId()
    return (
        <>
            <FolderField
                label="Folder with the existing files"
                value={value.folder}
                disabled={disabled}
                onChange={(folder) => onChange({...value, folder})}
                help="VODLoft looks in this folder and the folders inside it. Files are not moved or changed."
            />
            <div className="form-row">
                <label htmlFor={templateId}>Files are named differently from this profile's template</label>
                <input
                    id={templateId}
                    className="input"
                    value={value.template}
                    disabled={disabled}
                    placeholder="{{ date }} {{ title }} [{{ episode_site_id }}]"
                    spellCheck={false}
                    onChange={(event) => onChange({...value, template: event.target.value})}
                />
                <div className="help">
                    Optional: the old layout, used to read dates and titles from the names. Write it like an output
                    template, from /downloads/ to .ext, or just the file name part.
                </div>
            </div>
        </>
    )
}

/** A file-name-only layout becomes a full template inside the scanned folder. */
export function layoutTemplate(folder: string, template: string): string | null {
    const trimmed = template.trim()
    if (!trimmed) return null
    if (trimmed.startsWith('/downloads')) return trimmed.endsWith('.ext') ? trimmed : `${trimmed}.ext`
    const name = trimmed.endsWith('.ext') ? trimmed : `${trimmed}.ext`
    return `${folder.replace(/\/$/, '')}/${name}`
}
