import {useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {z} from 'zod'

import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {apiJson} from '../../lib/api'
import type {KeepQuestionRead} from '../../types/schemas/media_download'

type EpisodeQuestion = {
    episodeId: number
    title: string
    href: string
    collectionTitle: string
    siteName: string
    profileNames: string[]
}

const AnsweredSchema = z.object({answered: z.number()})

/** One question per episode: an episode can have downloads on several Local Media Profiles. */
function byEpisode(questions: KeepQuestionRead[]): EpisodeQuestion[] {
    const episodes = new Map<number, EpisodeQuestion>()
    for (const question of questions) {
        const episode = episodes.get(question.episodeId)
        if (episode) {
            episode.profileNames.push(question.localMediaProfileName)
            continue
        }
        episodes.set(question.episodeId, {
            episodeId: question.episodeId,
            title: question.episodeTitle,
            href: `/collection/${question.collectionSlug}/episode/${question.episodeSlug}`,
            collectionTitle: question.collectionTitle,
            siteName: question.siteName,
            profileNames: [question.localMediaProfileName],
        })
    }
    return [...episodes.values()]
}

/**
 * Asks on Home whether to keep downloads whose episode the Source no longer has.
 *
 * The question stays until someone answers it, and retention leaves those downloads alone until then.
 */
export default function KeepQuestions({questions}: {questions: KeepQuestionRead[]}) {
    const queryClient = useQueryClient()
    const episodes = useMemo(() => byEpisode(questions), [questions])
    const [busy, setBusy] = useState<number[] | null>(null)
    const [error, setError] = useState<string | null>(null)
    const mayAnswer = can('managed_downloads', 'manage')
    if (!episodes.length) return null

    const answer = async (episodeIds: number[], keep: boolean) => {
        setBusy(episodeIds)
        setError(null)
        try {
            await apiJson('/media-downloads/keep-questions/answer', AnsweredSchema.parse, {
                method: 'POST',
                json: {episodeIds, keep},
            })
            await queryClient.invalidateQueries({queryKey: ['keepQuestions']})
            void queryClient.invalidateQueries({queryKey: ['mediaDownloads']})
            void queryClient.invalidateQueries({queryKey: ['mediaDownloadsView']})
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Could not save the answer')
        } finally {
            setBusy(null)
        }
    }
    const isBusy = (episodeId: number) => busy?.includes(episodeId) ?? false
    const allIds = episodes.map((episode) => episode.episodeId)
    const one = episodes.length === 1

    return (
        <section className="keep-questions" aria-labelledby="keep-questions-title">
            <div className="keep-questions-header">
                <FontAwesomeIcon icon={faIcon('fass', 'thumbtack')}/>
                <div>
                    <h2 id="keep-questions-title">
                        {one ? 'Keep a download the Source no longer has?' : `Keep ${episodes.length} downloads the Source no longer has?`}
                    </h2>
                    <p>
                        Removed from {one ? 'its Site' : 'their Site'} after VODLoft downloaded {one ? 'it' : 'them'}, so
                        your copy may be the last one. VODLoft won't delete {one ? 'it' : 'them'} until you answer;
                        Don't keep lets the Download Profile handle {one ? 'it' : 'them'} as usual.
                    </p>
                </div>
            </div>
            {error && <div className="form-error-card" role="alert">{error}</div>}
            <ul className="keep-questions-list">
                {episodes.map((episode) => (
                    <li key={episode.episodeId}>
                        <span className="keep-question-copy">
                            <Link to={episode.href}><strong>{episode.title}</strong></Link>
                            <small>{episode.collectionTitle} • no longer on {episode.siteName} • {episode.profileNames.join(', ')}</small>
                        </span>
                        {mayAnswer && (
                            <span className="keep-question-actions">
                                <button
                                    type="button" className="btn btn-primary" disabled={busy !== null}
                                    aria-label={`Keep ${episode.title}`}
                                    onClick={() => void answer([episode.episodeId], true)}
                                >
                                    {isBusy(episode.episodeId) ? 'Saving…' : 'Keep'}
                                </button>
                                <button
                                    type="button" className="btn btn-secondary" disabled={busy !== null}
                                    aria-label={`Don't keep ${episode.title}`}
                                    onClick={() => void answer([episode.episodeId], false)}
                                >
                                    Don't keep
                                </button>
                            </span>
                        )}
                    </li>
                ))}
            </ul>
            {mayAnswer && !one && (
                <div className="keep-questions-all">
                    <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => void answer(allIds, true)}>
                        Keep all
                    </button>
                    <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={() => void answer(allIds, false)}>
                        Don't keep any
                    </button>
                </div>
            )}
        </section>
    )
}
