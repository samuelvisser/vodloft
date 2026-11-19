import {useState} from 'react'
import {Link} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import {putOffApiKeyNotes, useApiKeyNotes} from '../../lib/queries'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {sourceComponents} from '../Source/sourceComponents'
import './ApiKeyNote.css'

/** Asks for a free API key while collections or creators in the Library would be quicker with one, such as YouTube
 *  channels without a YouTube Data API key. It can be put off for a week or turned off. */
export default function ApiKeyNote() {
    const queryClient = useQueryClient()
    const {data: notes} = useApiKeyNotes()
    const [busy, setBusy] = useState(false)
    const [confirming, setConfirming] = useState(false)
    const note = notes?.[0]
    if (!note) return null
    const benefits = sourceComponents(note.sourceKey).apiKeyBenefits

    const putOff = async (action: 'later' | 'never') => {
        setBusy(true)
        try {
            await putOffApiKeyNotes(action)
            setConfirming(false)
            await queryClient.invalidateQueries({queryKey: ['apiKeyNotes']})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(false)
        }
    }

    return (
        <section className="api-key-note" aria-labelledby="api-key-note-title">
            <FontAwesomeIcon icon={faIcon('fass', 'key')} className="api-key-note-icon"/>
            <div className="api-key-note-copy">
                <h2 id="api-key-note-title">Add a free {note.siteName} API key</h2>
                <p>
                    Your library has {note.siteName} collections or creators, but VODLoft has no {note.siteName} API key.
                    {benefits ? ` ${benefits}` : ''}
                </p>
                <div className="api-key-note-actions">
                    <Link className="btn btn-primary" to="/settings?tab=sources">Add a key</Link>
                    <button type="button" className="btn" disabled={busy} onClick={() => void putOff('later')}>Remind me later</button>
                    <button type="button" className="btn btn-link" disabled={busy} onClick={() => setConfirming(true)}>Don't show again</button>
                </div>
            </div>
            <ConfirmDialog
                open={confirming}
                title="Don't ask for an API key again?"
                icon={faIcon('fass', 'triangle-exclamation')}
                onDismiss={() => setConfirming(false)}
                confirmButton={{label: "Don't show again", onClick: () => putOff('never'), disabled: busy}}
                cancelButton={{label: 'Keep the note'}}
            >
                <p>
                    A {note.siteName} API key is free and makes VODLoft a lot quicker on {note.siteName}: without one,
                    the first look at a large channel can take hours instead of a minute.
                </p>
                <p>You can still add a key later under Settings › Sources.</p>
            </ConfirmDialog>
        </section>
    )
}
