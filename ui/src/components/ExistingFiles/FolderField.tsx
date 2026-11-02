import {useId, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import type {FolderList} from '../../types/schemas/existing_files'
import {listFolders} from './api'

type Props = {
    label: string
    value: string
    onChange: (folder: string) => void
    help?: string
    disabled?: boolean
}

/** A /downloads/ folder, typed or picked from the folders VODLoft can see. */
export default function FolderField({label, value, onChange, help, disabled}: Props) {
    const id = useId()
    const [listing, setListing] = useState<FolderList | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)

    async function open(folder: string) {
        setLoading(true)
        setError(null)
        try {
            setListing(await listFolders(folder || '/downloads'))
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : 'VODLoft could not read that folder')
            if (folder !== '/downloads') setListing(await listFolders('/downloads').catch(() => null))
        } finally {
            setLoading(false)
        }
    }

    function pick(folder: string) {
        onChange(folder.replace(/\/$/, '') || '/downloads')
    }

    return (
        <div className="form-row existing-files-folder">
            <label htmlFor={id}>{label}</label>
            <div className="existing-files-folder-input">
                <input
                    id={id}
                    className="input"
                    value={value}
                    disabled={disabled}
                    onChange={(event) => onChange(event.target.value)}
                    spellCheck={false}
                />
                <button type="button" className="btn" disabled={disabled || loading}
                        onClick={() => listing ? setListing(null) : void open(value)}>
                    <FontAwesomeIcon icon={faIcon('fass', 'folder-open')} aria-hidden="true"/>
                    <span>{listing ? 'Close' : 'Browse'}</span>
                </button>
            </div>
            {help && <div className="help">{help}</div>}
            {error && <div className="error" role="alert">{error}</div>}
            {listing && (
                <div className="existing-files-folder-list" role="listbox" aria-label="Folders">
                    <div className="existing-files-folder-current">
                        <span>{listing.folder}</span>
                        <button type="button" className="btn btn-small" onClick={() => {
                            pick(listing.folder)
                            setListing(null)
                        }}>Use this folder</button>
                    </div>
                    {listing.parent && (
                        <button type="button" className="existing-files-folder-item" onClick={() => void open(listing.parent!)}>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrow-up')} aria-hidden="true"/>
                            <span>Up</span>
                        </button>
                    )}
                    {listing.folders.map((name) => {
                        const folder = `${listing.folder.replace(/\/$/, '')}/${name}`
                        return (
                            <button key={name} type="button" className="existing-files-folder-item" role="option"
                                    aria-selected={false}
                                    onClick={() => {
                                        pick(folder)
                                        void open(folder)
                                    }}>
                                <FontAwesomeIcon icon={faIcon('fass', 'folder')} aria-hidden="true"/>
                                <span>{name}</span>
                            </button>
                        )
                    })}
                    {listing.folders.length === 0 && <div className="help">No folders in here.</div>}
                </div>
            )}
        </div>
    )
}
