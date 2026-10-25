import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {updateSourceProgram, useSourceProgram} from '../../lib/queries'
import type {SourceRead} from '../../types/schemas/source'

function formatDate(value?: string | null): string | null {
    if (!value) return null
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date.toLocaleString()
}

/** The program a Source runs, such as yt-dlp, with an Update now button. */
export default function SourceProgramCard({source}: {source: SourceRead}) {
    const queryClient = useQueryClient()
    const {data: program, isPending, error} = useSourceProgram(source.id)
    const [updating, setUpdating] = useState(false)
    const [updateError, setUpdateError] = useState<string | null>(null)

    const update = async () => {
        setUpdating(true)
        setUpdateError(null)
        try {
            const status = await updateSourceProgram(source.id)
            queryClient.setQueryData(['sourceProgram', source.id], status)
        } catch (exc) {
            setUpdateError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setUpdating(false)
        }
    }

    const lastUpdate = formatDate(program?.lastUpdateAt)
    const name = program?.name ?? source.name
    return (
        <div className="source-setting">
            <div className="source-setting-copy">
                <h4>Updates</h4>
                {error ? (
                    <p role="alert">Could not check {name}: {error.message}</p>
                ) : isPending ? (
                    <p>Checking the installed version…</p>
                ) : (
                    <p>
                        {program?.version ? `${name} ${program.version}.` : `${name} does not run.`}{' '}
                        {lastUpdate ? `Last updated ${lastUpdate}.` : 'Not updated yet.'}{' '}
                        VODLoft updates it once a week, because sites change often.
                    </p>
                )}
                {program?.lastUpdateError && !updateError && (
                    <p className="source-setting-error" role="alert">The last update failed: {program.lastUpdateError}</p>
                )}
                {updateError && <p className="source-setting-error" role="alert">{updateError}</p>}
            </div>
            <button className="btn" type="button" onClick={() => void update()} disabled={updating}>
                {updating ? 'Updating…' : 'Update now'}
            </button>
        </div>
    )
}
