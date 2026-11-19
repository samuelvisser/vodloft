import {useEffect, useMemo, useRef, useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'

import {faIcon} from '../../icons/faIcon'
import PathChangeList, {type PathChange} from '../common/PathChangeList'
import SimpleSelect from '../common/SimpleSelect'
import Modal from '../Modal/Modal'
import DownloadLogDialog from '../MediaDownload/DownloadLogDialog'
import {useActiveOperation} from '../OperationNotifier/OperationNotifier'
import {useEpisodeDownloads, useLocalMediaProfiles} from '../../lib/queries'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {useLocalMediaProfileSelectRegistry} from '../../types/local_media_profile'
import {
    type EpisodeMoveOutcome,
    type LocalMediaProfileMoveCollection,
    type LocalMediaProfileMoveEpisode,
    LocalMediaProfileMovePreviewSchema,
} from '../../types/schemas/local_media_profile_move'
import {getErrorMessageFromResponse} from '../../utils/helpers'
import './MoveEpisodesDialog.css'
import {apiUrl} from '../../lib/api'
import {collectionWords, Noun} from '../../lib/collectionWords'

type Props = {
    profile: {id: number, slug: string, name: string, type?: string | null}
    /** Nothing downloaded is left on the profile and no Download Profile uses it. */
    sourceEmpty: boolean
    onDeleteProfile: () => void
    onClose: () => void
}

type Choice = {move: boolean, moveDownloadProfile: boolean}

const api = () => apiUrl()

const MOVES: readonly EpisodeMoveOutcome[] = ['move', 'replace']

function outcomeLabel(outcome: EpisodeMoveOutcome, target: string, noun: Noun): string {
    switch (outcome) {
        case 'move': return 'Moves'
        case 'replace': return `Moves, in place of ${target}'s record without a file`
        case 'target_has_file': return `Stays: ${target} already has this ${noun.one}`
        case 'path_taken': return 'Stays: another file already has the new path'
        case 'same_path': return `Same new path as another ${noun.one}`
        case 'file_missing': return 'Stays: the file is missing'
        case 'busy': return 'Stays: a download is running for it'
    }
}

function moving(collection: LocalMediaProfileMoveCollection) {
    return collection.episodes.filter((episode) => MOVES.includes(episode.outcome)).length
}

function movable(collection: LocalMediaProfileMoveCollection) {
    return collection.inScope && !collection.blocked && moving(collection) > 0
}

function plural(count: number, noun: Noun, before = '') {
    return `${count} ${before}${count === 1 ? noun.one : noun.many}`
}

/** Opens the download history of an episode's copy on the source profile, where it can be deleted. */
function HistoryButton({episode}: {episode: LocalMediaProfileMoveEpisode}) {
    const queryClient = useQueryClient()
    const [open, setOpen] = useState(false)
    const close = () => {
        setOpen(false)
        // The copy may have been deleted there.
        void queryClient.invalidateQueries({queryKey: ['localMediaProfileMovePreview']})
        void queryClient.invalidateQueries({queryKey: ['localMediaProfileView']})
    }
    return (
        <>
            <button
                type="button"
                className="btn btn-icon move-episodes-history"
                title="Open this download's history"
                aria-label={`Open the download history of ${episode.episodeTitle}`}
                onClick={() => setOpen(true)}
            >
                <FontAwesomeIcon icon={faIcon('fass', 'file-lines')}/>
            </button>
            {open && <EpisodeDownloadLog episode={episode} onClose={close}/>}
        </>
    )
}

function EpisodeDownloadLog({episode, onClose}: {episode: LocalMediaProfileMoveEpisode, onClose: () => void}) {
    const {data} = useEpisodeDownloads(episode.episodeSlug)
    const row = data?.find((download) => download.id === episode.mediaDownloadId) ?? null
    return <DownloadLogDialog row={row} onClose={onClose}/>
}

function episodeChange(episode: LocalMediaProfileMoveEpisode, target: string, noun: Noun): PathChange {
    const moves = MOVES.includes(episode.outcome)
    return {
        key: episode.mediaDownloadId,
        from: episode.sourcePath,
        to: moves ? episode.destinationPath ?? null : null,
        toNote: moves ? 'Worked out when the move runs' : undefined,
        muted: !moves,
        header: (
            <>
                <span className="move-episodes-episode-title">{episode.episodeTitle}</span>
                <span className={`move-episodes-episode-outcome${moves ? '' : ' is-stays'}`}>{outcomeLabel(episode.outcome, target, noun)}</span>
                {!moves && <HistoryButton episode={episode}/>}
            </>
        ),
    }
}

function CollectionCard({collection, choice, setChoice, source, target, disabled, noun}: {
    collection: LocalMediaProfileMoveCollection
    noun: Noun
    choice: Choice
    setChoice: (choice: Choice) => void
    source: string
    target: string
    disabled: boolean
}) {
    const [expanded, setExpanded] = useState(false)
    const count = moving(collection)
    const stays = collection.episodes.length - count
    const canMove = movable(collection)
    const hasSourceProfile = collection.sourceDownloadProfiles.length > 0
    const hasTargetProfile = collection.targetDownloadProfiles.length > 0

    return (
        <section className="move-episodes-collection" aria-label={collection.collectionTitle}>
            <label className="move-episodes-collection-header">
                <input
                    type="checkbox"
                    checked={canMove && choice.move}
                    disabled={!canMove || disabled}
                    onChange={(event) => setChoice({...choice, move: event.target.checked})}
                />
                <span className="move-episodes-collection-title">{collection.collectionTitle}</span>
                <span className="move-episodes-muted">
                    {plural(count, noun)} move{count === 1 ? 's' : ''}
                    {stays > 0 && `, ${stays} stay${stays === 1 ? 's' : ''}`}
                </span>
            </label>

            {!collection.inScope && (
                <p className="move-episodes-note">
                    {target} is not offered for this Collection: its {
                        !collection.typeOffered && !collection.siteOffered ? 'type and Site are'
                            : !collection.typeOffered ? 'type is' : 'Site is'
                    } not one the profile is for.
                </p>
            )}
            {collection.blocked && (
                <p className="move-episodes-note move-episodes-warning">
                    Several {noun.many} would get the same path in {target}. Change its output template so every
                    {' '}{noun.one} gets a path of its own first.
                </p>
            )}

            {canMove && choice.move && (
                <div className="move-episodes-download-profiles">
                    {hasSourceProfile && !hasTargetProfile && (
                        <>
                            <label className="move-episodes-check">
                                <input
                                    type="checkbox"
                                    checked={choice.moveDownloadProfile}
                                    disabled={disabled}
                                    onChange={(event) => setChoice({...choice, moveDownloadProfile: event.target.checked})}
                                />
                                <span>Also move its Download Profile to {target}</span>
                            </label>
                            {!choice.moveDownloadProfile && (
                                <p className="move-episodes-note move-episodes-warning">
                                    The Download Profile stays on {source} and downloads the moved {noun.many} there
                                    again.
                                </p>
                            )}
                        </>
                    )}
                    {hasTargetProfile && (
                        <p className="move-episodes-note">
                            The moved {noun.many} join {target}'s Download Profile for this Collection.
                        </p>
                    )}
                    {collection.retentionAtRisk > 0 && (
                        <p className="move-episodes-note move-episodes-warning">
                            {target}'s Download Profile deletes older {noun.many}: {plural(collection.retentionAtRisk, noun, 'moved ')}
                            {' '}fall{collection.retentionAtRisk === 1 ? 's' : ''} outside its limit and will be deleted.
                            Mark them as kept first to keep them.
                        </p>
                    )}
                    {hasSourceProfile && hasTargetProfile && (
                        <p className="move-episodes-note move-episodes-warning">
                            {source}'s Download Profile for this Collection stays and downloads the moved {noun.many}
                            there again. Turn it off or delete it after the move.
                        </p>
                    )}
                </div>
            )}

            <button type="button" className="btn btn-link move-episodes-toggle" onClick={() => setExpanded(!expanded)}>
                {expanded ? `Hide ${noun.many}` : `Show ${noun.many}`}
            </button>
            {expanded && (
                <PathChangeList
                    changes={collection.episodes.map((episode) => episodeChange(episode, target, noun))}
                    fromLabel="Now"
                    toLabel="After"
                    endless
                />
            )}
        </section>
    )
}

/** Move a Collection Local Media Profile's downloaded episodes, and their files, to another profile. */
export default function MoveEpisodesDialog({profile, sourceEmpty, onDeleteProfile, onClose}: Props) {
    // A Music profile keeps tracks.
    const noun = collectionWords(profile.type === 'music' ? 'music' : null, 'audio').episode
    const queryClient = useQueryClient()
    const startOperation = useStartOperation()
    const {data: profiles} = useLocalMediaProfiles()
    const others = useMemo(
        () => (profiles ?? []).filter((candidate) => candidate.type === 'collection' && candidate.id !== profile.id),
        [profiles, profile.id],
    )
    const registry = useLocalMediaProfileSelectRegistry(others, 'collection')
    const [targetId, setTargetId] = useState<string | null>(null)
    const target = others.find((candidate) => String(candidate.id) === targetId)
    const [choices, setChoices] = useState<Record<number, Choice>>({})
    const [starting, setStarting] = useState(false)
    const [finished, setFinished] = useState(false)

    const preview = useQuery({
        queryKey: ['localMediaProfileMovePreview', profile.slug, target?.slug] as const,
        enabled: Boolean(target),
        queryFn: async ({signal}) => {
            const params = new URLSearchParams({target: target!.slug})
            const response = await fetch(
                `${api()}/local-media-profiles/${encodeURIComponent(profile.slug)}/move-episodes/preview?${params}`,
                {credentials: 'include', signal},
            )
            if (!response.ok) throw new Error((await getErrorMessageFromResponse(response)).error)
            return LocalMediaProfileMovePreviewSchema.parse(await response.json())
        },
        refetchOnMount: 'always',
    })
    const collections = preview.data?.collections ?? []

    const operation = useActiveOperation('local_media_profile.move_episodes', 'local_media_profile', profile.id)
    const running = Boolean(operation) || starting
    const lastOperation = useRef<string | undefined>(undefined)
    useEffect(() => {
        if (lastOperation.current && !operation) {
            setFinished(true)
            void queryClient.invalidateQueries({queryKey: ['localMediaProfileMovePreview', profile.slug]})
        }
        lastOperation.current = operation?.id
    }, [operation, profile.slug, queryClient])

    const choiceOf = (collection: LocalMediaProfileMoveCollection): Choice => choices[collection.collectionId] ?? {
        move: true,
        moveDownloadProfile: collection.canMoveDownloadProfile,
    }
    const chosen = collections.filter((collection) => movable(collection) && choiceOf(collection).move)
    const episodes = chosen.reduce((total, collection) => total + moving(collection), 0)

    async function move() {
        if (!target || chosen.length === 0) return
        setStarting(true)
        try {
            await startOperation(`${api()}/local-media-profiles/${encodeURIComponent(profile.slug)}/move-episodes`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    targetSlug: target.slug,
                    collections: chosen.map((collection) => ({
                        collectionId: collection.collectionId,
                        moveDownloadProfile: collection.canMoveDownloadProfile && choiceOf(collection).moveDownloadProfile,
                    })),
                }),
            })
            setFinished(false)
            toast.success(`Moving ${plural(episodes, noun)} to ${target.name}`)
        } catch (error) {
            toast.error(error instanceof OperationStartError || error instanceof Error ? error.message : 'Could not start the move')
        } finally {
            setStarting(false)
        }
    }

    return (
        <Modal
            onDismiss={onClose}
            dismissOnOverlayClick={false}
            // Escape closes, as Close does, but not while it would lose the choices made per collection.
            dismissOnEscape={!starting && Object.keys(choices).length === 0}
            className="modal move-episodes-dialog"
            labelledBy="move-episodes-title"
        >
            <div className="modal-header">
                <div className="modal-icon" aria-hidden><FontAwesomeIcon icon={faIcon('fass', 'file-export')}/></div>
                <h2 id="move-episodes-title" className="modal-title">Move {noun.many} to another profile</h2>
            </div>

            <div className="move-episodes-body">
                <p className="move-episodes-intro">
                    The downloaded {noun.many} of "{profile.name}" move over to another Local Media Profile, with their
                    history, and their files are renamed into its layout. Nothing is overwritten: {noun.a} that
                    can't move stays where it is.
                </p>

                <div className="form-group">
                    <label htmlFor="move-episodes-target">Move to</label>
                    <SimpleSelect
                        inputId="move-episodes-target"
                        registry={registry}
                        value={targetId}
                        onChange={(value) => { setTargetId(value); setChoices({}); setFinished(false) }}
                        isDisabled={running}
                        // The dialog body scrolls, so its own menu would be clipped: draw it above the dialog.
                        menuPortalTarget={document.body}
                        menuPosition="fixed"
                        styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                        placeholder={others.length ? 'Choose a Local Media Profile' : 'No other Collection Local Media Profiles'}
                    />
                </div>

                {operation && (
                    <div className="form-info-card" role="status" aria-live="polite">
                        <FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/>{' '}
                        {operation.message || `Moving ${noun.many}…`}
                    </div>
                )}
                {sourceEmpty && (finished || (preview.data && collections.length === 0)) && (
                    <div className="form-info-card move-episodes-empty" role="status">
                        <span>Nothing downloaded is left on "{profile.name}" and no Download Profile uses it.</span>
                        <button type="button" className="btn btn-danger" onClick={onDeleteProfile}>
                            <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
                            <span>Delete {profile.name}</span>
                        </button>
                    </div>
                )}

                {target && preview.isLoading && <p className="move-episodes-muted">Working out what moves…</p>}
                {preview.error && <p role="alert">{preview.error.message}</p>}
                {target && preview.data && collections.length === 0 && (
                    <p className="move-episodes-muted">"{profile.name}" has no downloaded {noun.many} left to move.</p>
                )}
                {target && collections.map((collection) => (
                    <CollectionCard
                        key={collection.collectionId}
                        collection={collection}
                        choice={choiceOf(collection)}
                        setChoice={(choice) => setChoices((current) => ({...current, [collection.collectionId]: choice}))}
                        source={profile.name}
                        target={target.name}
                        disabled={running}
                        noun={noun}
                    />
                ))}
                {chosen.length > 0 && (
                    <p className="move-episodes-muted">
                        The Download Profiles of these Collections pause while their files move.
                    </p>
                )}
            </div>

            <div className="modal-actions">
                <button type="button" className="btn" onClick={onClose}>Close</button>
                <button
                    type="button"
                    className="btn btn-primary"
                    disabled={running || episodes === 0}
                    onClick={() => void move()}
                >
                    {starting ? 'Starting…' : episodes ? `Move ${plural(episodes, noun)}` : `Move ${noun.many}`}
                </button>
            </div>
        </Modal>
    )
}
