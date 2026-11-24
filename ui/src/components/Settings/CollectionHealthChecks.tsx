import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'

import {can} from '../../lib/access'
import {resetHealthDismissals, setHealthCheck, useHealthChecks} from '../../lib/queries'
import type {HealthChecks, HealthIssueKind} from '../../types/schemas/collection_health'
import {ToggleField} from './SettingsControls'

const HELP: Record<HealthIssueKind, string> = {
    moves: 'Downloads that your season settings put in another season, which wait for you to move them.',
    new_lists: 'Lists a channel added later, which wait for you to choose whether they are added.',
    creators: 'Finds the creator behind your collections, and suggests grouping three or more collections of one creator.',
}

/** Which checks the collection health check runs, saved at once, and a reset of the suggestions the user put away. */
export default function CollectionHealthChecks() {
    const queryClient = useQueryClient()
    const {data, error} = useHealthChecks()
    const [busy, setBusy] = useState(false)
    const [failure, setFailure] = useState<string | null>(null)
    const mayChange = can('library', 'manage')

    const save = async (work: () => Promise<HealthChecks>) => {
        setBusy(true)
        setFailure(null)
        try {
            queryClient.setQueryData(['collectionHealth', 'checks'], await work())
            await queryClient.invalidateQueries({queryKey: ['collectionHealth']})
        } catch (problem) {
            setFailure(problem instanceof Error ? problem.message : String(problem))
        } finally {
            setBusy(false)
        }
    }

    if (error) return <div className="form-error" role="alert">Could not load the health checks: {error.message}</div>
    if (!data) return null
    return (
        <>
            {data.checks.map((check) => (
                <ToggleField
                    key={check.kind}
                    id={`settings-health-check-${check.kind}`}
                    label={`Check for ${check.title}`}
                    checked={check.on}
                    help={HELP[check.kind]}
                    onChange={(on) => {
                        if (mayChange && !busy) void save(() => setHealthCheck(check.kind, on))
                    }}
                />
            ))}
            <div className="settings-field settings-field--wide">
                <label>Dismissed suggestions</label>
                <div className="settings-field__help">
                    {data.dismissed
                        ? `You dismissed or put off ${data.dismissed} suggestion${data.dismissed === 1 ? '' : 's'}. Reset to see ${data.dismissed === 1 ? 'it' : 'them'} on Home again.`
                        : 'You have not dismissed any suggestions.'}
                </div>
                <div>
                    <button
                        type="button" className="btn btn-secondary" disabled={!mayChange || busy || !data.dismissed}
                        onClick={() => void save(resetHealthDismissals)}
                    >
                        Reset dismissed suggestions
                    </button>
                </div>
                {failure && <div className="form-error" role="alert">{failure}</div>}
            </div>
        </>
    )
}
