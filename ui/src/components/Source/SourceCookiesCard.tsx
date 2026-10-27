import {ChangeEvent, useRef, useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {saveSourceCookies, useSourceCookies} from '../../lib/queries'
import type {SourceRead} from '../../types/schemas/source'

/** An optional cookies.txt file, for videos that need a signed-in browser. */
export default function SourceCookiesCard({source}: {source: SourceRead}) {
    const queryClient = useQueryClient()
    const {data: cookies} = useSourceCookies(source.id)
    const inputRef = useRef<HTMLInputElement | null>(null)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const save = async (content: string | null) => {
        setSaving(true)
        setError(null)
        try {
            queryClient.setQueryData(['sourceCookies', source.id], await saveSourceCookies(source.id, content))
            // Signing in or out can change what the Source's subscription allows.
            await queryClient.invalidateQueries({queryKey: ['sources']})
        } catch (exc) {
            setError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSaving(false)
        }
    }

    const choose = async (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0]
        event.target.value = ''
        if (file) await save(await file.text())
    }

    return (
        <div className="source-setting">
            <div className="source-setting-copy">
                <h4>Cookies file</h4>
                <p>
                    {source.cookiesHelp ?? (
                        <>
                            Optional. Some videos are only available when you are signed in, such as age-restricted or
                            members-only videos. Export a cookies.txt file from a browser where you are signed in, and
                            {' '}{source.name} uses it for every lookup and download.
                        </>
                    )}
                    {' '}{cookies?.hasCookies ? 'A cookies file is in use.' : 'No cookies file is in use.'}
                </p>
                {error && <p className="source-setting-error" role="alert">{error}</p>}
            </div>
            <div className="source-setting-actions">
                <input
                    ref={inputRef}
                    className="sr-only"
                    type="file"
                    accept=".txt,text/plain"
                    aria-label="Cookies file"
                    onChange={(event) => void choose(event)}
                />
                <button className="btn" type="button" onClick={() => inputRef.current?.click()} disabled={saving}>
                    {cookies?.hasCookies ? 'Replace file' : 'Choose file'}
                </button>
                {cookies?.hasCookies && (
                    <button className="btn" type="button" onClick={() => void save(null)} disabled={saving}>
                        Remove
                    </button>
                )}
            </div>
        </div>
    )
}
