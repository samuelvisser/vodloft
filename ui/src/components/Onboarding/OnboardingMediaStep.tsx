import {useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'

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
    const queryClient = useQueryClient()
    const importers = useImporters()
    const [chosen, setChosen] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)
    const importer = importers.data?.find((item) => item.key === chosen)

    async function startFresh() {
        setBusy(true)
        setError(null)
        try {
            const response = await fetch(`${(window as any).appConfig.API_URL}/onboarding/start-fresh`, {
                method: 'POST',
                credentials: 'include',
            })
            if (!response.ok) throw new Error(`HTTP ${response.status}`)
            await queryClient.invalidateQueries({queryKey: ['localMediaProfiles']})
            onStartFresh()
        } catch {
            setError('VODLoft could not set up the default profiles. Please try again.')
        } finally {
            setBusy(false)
        }
    }

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
                    <button className="btn" type="button" disabled={busy} onClick={() => void startFresh()}>
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
                <button className="onboarding-media-choice" type="button" disabled={busy} onClick={() => void startFresh()}>
                    <FontAwesomeIcon icon={faIcon('fass', 'plus')}/>
                    <strong>Start fresh</strong>
                    <small>Add your first collection or movie.</small>
                </button>
                {(importers.data ?? []).map((item) => (
                    <button
                        key={item.key}
                        className="onboarding-media-choice"
                        type="button"
                        disabled={busy}
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
            {error && <p className="form-error-card" role="alert">{error}</p>}
            <div className="onboarding-stage-actions">
                <button className="btn" type="button" onClick={onBack}>Back</button>
            </div>
        </>
    )
}
