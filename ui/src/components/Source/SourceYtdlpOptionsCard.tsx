import {useEffect, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {saveSourceYtdlpOptions, useSourceYtdlpOptions} from '../../lib/queries'
import type {SourceRead} from '../../types/schemas/source'
import OptionsEditor from '../common/OptionsEditor/OptionsEditor'
import ReadMore from '../../utils/ReadMore'

/** Your own yt-dlp options, for every download of the Source. */
export default function SourceYtdlpOptionsCard({source}: {source: SourceRead}) {
    const queryClient = useQueryClient()
    const {data: saved} = useSourceYtdlpOptions(source.id)
    const [text, setText] = useState('')
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [savedNote, setSavedNote] = useState(false)

    useEffect(() => {
        if (saved !== undefined) setText(saved)
    }, [saved])

    const save = async () => {
        setSaving(true)
        setError(null)
        try {
            const stored = await saveSourceYtdlpOptions(source.id, text)
            queryClient.setQueryData(['sourceYtdlpOptions', source.id], stored)
            setText(stored)
            setSavedNote(true)
            window.setTimeout(() => setSavedNote(false), 2000)
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSaving(false)
        }
    }

    const id = `source-${source.id}-ytdlp-options`
    return (
        <div className="source-setting source-setting--stacked">
            <div className="source-setting-copy">
                <h4><label htmlFor={id}>Your own yt-dlp options</label></h4>
                <div className="help">
                <ReadMore summary={`Extra options for every download of the ${source.name} Source. Most people leave this empty.`}>
                    <p>Write options the way yt-dlp’s own option files have them: one or more per line, and lines starting with # are notes.
                        Each line is checked with yt-dlp’s own parser as you type.</p>
                    <p>A few options are <strong>blocked</strong>, with the reason: the ones that would change where files go or what they are called
                        (such as <code>-o</code> and <code>-P</code>), pick the format past a Local Media Profile’s Quality (<code>-f</code>), or run other programs (<code>--exec</code>).
                        Options VODLoft already has a setting for point to that setting instead.</p>
                    <p>A Collection can add its own options on top of these, on its Edit page.</p>
                </ReadMore>
                </div>
            </div>
            <OptionsEditor
                id={id}
                value={text}
                onChange={(value) => {
                    setError(null)
                    setText(value)
                }}
                invalid={!!error}
                describedBy={error ? `${id}-error` : undefined}
            />
            {error && <p id={`${id}-error`} className="source-setting-error" role="alert">{error}</p>}
            <div className="source-setting-actions">
                {savedNote && <span className="source-setting-saved" aria-live="polite">Saved</span>}
                <button className="btn" type="button" onClick={() => void save()} disabled={saving || saved === undefined || text === saved}>
                    Save options
                </button>
            </div>
        </div>
    )
}
