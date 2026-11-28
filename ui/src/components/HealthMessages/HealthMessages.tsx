import {useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {Link, useNavigate} from 'react-router-dom'

import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {wordsOf} from '../../lib/collectionWords'
import {answerCreatorSuggestion, groupCreatorSuggestion, setHealthCheck} from '../../lib/queries'
import {toast} from '../../lib/toast'
import type {CreatorSuggestion, HealthIssue, HealthLevel, UnhealthyCollection} from '../../types/schemas/collection_health'

/** The class of a message on Home of the level: an error, a warning, or info. */
export function alertClass(level: HealthLevel) {
    return `operation-alert operation-alert--${level}`
}

/** What one health issue of a collection needs from the user, as a message on Home. */
export function HealthIssueAlert({collection, issue}: {collection: UnhealthyCollection, issue: HealthIssue}) {
    switch (issue.kind) {
        case 'moves': {
            // Why its downloads wait, in its own words: what its seasons settings make its seasons now.
            const {season, count} = wordsOf(collection.words)
            return (
                <Link className={alertClass(issue.level)} to={`/collection/${collection.slug}?move=1`}>
                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')}/>
                    <span>
                        <strong>{collection.title}</strong>
                        <small>
                            {`${count(issue.count)} ${issue.count === 1 ? 'belongs' : 'belong'} in another ${season.singular} now. `}
                            {issue.seasonsPlan}
                        </small>
                    </span>
                    <span>Move</span>
                </Link>
            )
        }
        case 'new_lists': {
            const one = issue.count === 1
            return (
                <Link className={alertClass(issue.level)} to={`/edit-collection/${encodeURIComponent(collection.slug)}?seasons=1`}>
                    <FontAwesomeIcon icon={faIcon('fass', 'list')}/>
                    <span>
                        <strong>{collection.title}</strong>
                        <small>
                            {`${one ? issue.names.a.replace(/^\S+\s/, 'A new ') : `${issue.count} new ${issue.names.plural}`} `}
                            {`${one ? 'waits' : 'wait'} for you to choose whether ${one ? 'it is' : 'they are'} added.`}
                        </small>
                    </span>
                    <span>Choose</span>
                </Link>
            )
        }
    }
}

/** Suggests grouping several collections of one creator under the creator, to keep the Library tidy. */
export function CreatorSuggestionCard({suggestion}: {suggestion: CreatorSuggestion}) {
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const [busy, setBusy] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const mayAnswer = can('library', 'manage')
    const creator = suggestion.creatorNames.singular
    const titles = suggestion.collections.map((collection) => collection.title)
    const listed = titles.length > 3 ? `${titles.slice(0, 3).join(', ')} and ${titles.length - 3} more` : titles.join(', ')

    const run = async (action: string, work: () => Promise<unknown>, after?: () => void) => {
        setBusy(action)
        setError(null)
        try {
            await work()
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['collectionHealth']}),
                queryClient.invalidateQueries({queryKey: ['collections']}),
                queryClient.invalidateQueries({queryKey: ['creators']}),
            ])
            after?.()
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : String(failure))
        } finally {
            setBusy(null)
        }
    }

    const group = () => run('group', async () => {
        const slug = await groupCreatorSuggestion(suggestion.siteKey, suggestion.ref)
        toast(`${suggestion.title}'s collections are grouped now`)
        navigate(`/creator/${encodeURIComponent(slug)}`)
    })

    return (
        <div className={`${alertClass(suggestion.level)} health-suggestion`}>
            <FontAwesomeIcon icon={faIcon('fass', 'users')}/>
            <span>
                <strong>Group {suggestion.title}'s collections</strong>
                <small className="health-suggestion-detail">
                    {`${suggestion.collections.length} of your collections are by ${suggestion.title} on ${suggestion.siteName}, `}
                    {`and in no ${creator} yet: ${listed}. `}
                    {suggestion.creatorSlug
                        ? `Add them to ${suggestion.creatorTitle} to keep your Library tidy.`
                        : `Group them under ${suggestion.title} to keep your Library tidy.`}
                </small>
                {error && <small className="form-error" role="alert">{error}</small>}
                {mayAnswer && (
                    <span className="health-suggestion-actions">
                        <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={group}>
                            {busy === 'group' ? 'Grouping…' : 'Group'}
                        </button>
                        <button type="button" className="btn btn-secondary" disabled={busy !== null}
                            onClick={() => run('later', () => answerCreatorSuggestion(suggestion.siteKey, suggestion.ref, 'later'))}>
                            Later
                        </button>
                        <button type="button" className="btn btn-secondary" disabled={busy !== null}
                            onClick={() => run('dismiss', () => answerCreatorSuggestion(suggestion.siteKey, suggestion.ref, 'dismiss'))}>
                            Dismiss
                        </button>
                        <button type="button" className="health-suggestion-never" disabled={busy !== null}
                            onClick={() => run('never', () => setHealthCheck('creators', false), () => toast(
                                'VODLoft no longer suggests grouping creators. Turn it on again under Settings › Automation.',
                            ))}>
                            Never suggest grouping creators
                        </button>
                    </span>
                )}
            </span>
        </div>
    )
}
