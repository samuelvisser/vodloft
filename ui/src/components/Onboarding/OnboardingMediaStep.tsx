import {useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import '../Import/Import.css'
import ImportFlow from '../Import/ImportFlow'
import {useImporters} from '../../lib/imports'
import {faIcon} from '../../icons/faIcon'

type Props = {
    importing: boolean
    onBack: () => void
    onImport: () => void
    onStartFresh: () => void
    onImported: () => void
}

/** "Your media": start a library fresh, or move one over from Pinchflat or WireLoft. */
export default function OnboardingMediaStep({importing, onBack, onImport, onStartFresh, onImported}: Props) {
    const importers = useImporters()
    const [chosen, setChosen] = useState<string | null>(null)
    const importer = importers.data?.find((item) => item.key === chosen)

    if (importing && importer) {
        return (
            <>
                <div className="onboarding-section-heading">
                    <span className="onboarding-eyebrow">Your media</span>
                    <h1>Move over from {importer.name}</h1>
                    <p>
                        Upload {importer.name}'s config folder and check what comes over. Your files stay where they
                        are; VODLoft takes them over in place.
                    </p>
                </div>
                <ImportFlow importer={importer} onFinished={(run) => run.status === 'finished' && onImported()}/>
                <div className="onboarding-stage-actions">
                    <button className="btn" type="button" onClick={onBack}>Back</button>
                    <button className="btn" type="button" onClick={onStartFresh}>
                        Skip and start fresh
                    </button>
                </div>
            </>
        )
    }

    return (
        <>
            <div className="onboarding-section-heading">
                <span className="onboarding-eyebrow">Your media</span>
                <h1>Start fresh, or bring your library</h1>
                <p>
                    Coming from another program? VODLoft can take over its collections, profiles, settings and
                    downloaded files without downloading anything again.
                </p>
            </div>
            <div className="onboarding-media-choices">
                <button className="onboarding-media-choice" type="button" onClick={onStartFresh}>
                    <FontAwesomeIcon icon={faIcon('fass', 'plus')}/>
                    <strong>Start fresh</strong>
                    <small>Add your first collection or movie.</small>
                </button>
                {(importers.data ?? []).map((item) => (
                    <button
                        key={item.key}
                        className="onboarding-media-choice"
                        type="button"
                        onClick={() => {
                            setChosen(item.key)
                            onImport()
                        }}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'file-import')}/>
                        <strong>Move over from {item.name}</strong>
                        <small>Upload its config folder and choose what comes over.</small>
                    </button>
                ))}
            </div>
            {importers.isError && <p className="settings-field__help">The importers could not be loaded; you can import later in Settings › Import.</p>}
            <div className="onboarding-stage-actions">
                <button className="btn" type="button" onClick={onBack}>Back</button>
            </div>
        </>
    )
}
