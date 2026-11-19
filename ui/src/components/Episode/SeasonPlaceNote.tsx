import {useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'
import {z} from 'zod'
import {Link, useNavigate} from 'react-router-dom'

import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {faIcon} from '../../icons/faIcon'
import {collectionWords, CollectionWords} from '../../lib/collectionWords'
import '../common/DrmProtected.css'
import './SeasonPlaceNote.css'

const SeasonPlaceSchema = z.object({
    belongsElsewhere: z.boolean(),
    seasonName: z.string().nullable().optional(),
    linkTitle: z.string().nullable().optional(),
    linkKind: z.string().default('playlist'),
    /** Reassigned: the collection of its creator that the episode belongs in now. */
    collectionSlug: z.string().nullable().optional(),
    collectionTitle: z.string().nullable().optional(),
})
type SeasonPlace = z.infer<typeof SeasonPlaceSchema>

const MovedEpisodesSchema = z.object({episodeSlugs: z.array(z.string())})
const ReassignedEpisodesSchema = z.object({
    episodes: z.array(z.object({episodeSlug: z.string(), collectionSlug: z.string(), collectionTitle: z.string()})),
})
const ReassignedMoveSchema = z.object({
    episodes: z.number(), renamed: z.number(), downloading: z.number(),
    episodeSlug: z.string().nullable().optional(), collectionSlug: z.string().nullable().optional(),
})
export type ReassignedMove = z.infer<typeof ReassignedMoveSchema>

const SHOW_WORDS = collectionWords(null)

/** What the Moved badge explains, in the collection's words. */
export const movedMessage = (words: CollectionWords = SHOW_WORDS) =>
    `Belongs in another ${words.season.one} now; it stays where it is until you move it, files and all`

const placeKey = (episodeSlug: string) => ['episode', episodeSlug, 'seasonPlace']
const movedKey = (collectionSlug: string) => ['collection', collectionSlug, 'movedEpisodes']
const reassignedKey = (collectionSlug: string) => ['collection', collectionSlug, 'reassignedEpisodes']

/** Where an episode belongs now, when its collection's playlists put it in another season than the one it is in. */
export function useSeasonPlace(episodeSlug: string | undefined) {
    return useQuery({
        queryKey: placeKey(episodeSlug ?? ''),
        enabled: !!episodeSlug,
        queryFn: async ({signal}) => {
            const response = await fetch(`${apiUrl()}/episodes/${encodeURIComponent(episodeSlug!)}/season-place`, {signal, credentials: 'include'})
            return response.ok ? SeasonPlaceSchema.parse(await response.json()) : null
        },
    })
}

/** The slugs of a collection's episodes that belong in another season now. */
export function useMovedEpisodes(collectionSlug: string | undefined) {
    return useQuery({
        queryKey: movedKey(collectionSlug ?? ''),
        enabled: !!collectionSlug,
        queryFn: async ({signal}) => {
            const response = await fetch(
                `${apiUrl()}/collections/${encodeURIComponent(collectionSlug!)}/season-settings/moved-episodes`,
                {signal, credentials: 'include'},
            )
            return new Set(response.ok ? MovedEpisodesSchema.parse(await response.json()).episodeSlugs : [])
        },
    })
}

/** A collection's downloaded episodes that its creator places in another collection now: the title of that
 * collection, by episode slug. */
export function useReassignedEpisodes(collectionSlug: string | undefined) {
    return useQuery({
        queryKey: reassignedKey(collectionSlug ?? ''),
        enabled: !!collectionSlug,
        queryFn: async ({signal}) => {
            const response = await fetch(
                `${apiUrl()}/collections/${encodeURIComponent(collectionSlug!)}/season-settings/reassigned-episodes`,
                {signal, credentials: 'include'},
            )
            const episodes = response.ok ? ReassignedEpisodesSchema.parse(await response.json()).episodes : []
            return new Map(episodes.map((episode) => [episode.episodeSlug, episode.collectionTitle]))
        },
    })
}

/** What moving reassigned episodes did, in words. */
export function reassignedMoveMessage(result: ReassignedMove, words: CollectionWords = SHOW_WORDS): string {
    if (!result.episodes) return `No ${words.episode.many} to move`
    const parts = [
        result.renamed ? `renaming ${result.renamed} ${result.renamed === 1 ? 'download' : 'downloads'} into ${result.episodes === 1 ? 'its' : 'their'} new collection` : null,
        result.downloading ? `downloading ${result.downloading} again with the new collection's Local Media Profile; the old files go once that succeeded` : null,
    ].filter(Boolean)
    return `Moving ${result.episodes} ${result.episodes === 1 ? words.episode.one : words.episode.many}${parts.length ? `: ${parts.join(', and ')}` : ''}`
}

/** Move reassigned episodes to the collections their creator places them in now. */
export async function postReassignedMove(path: string): Promise<ReassignedMove> {
    const response = await fetch(`${apiUrl()}${path}`, {method: 'POST', credentials: 'include'})
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : 'Could not move the episodes')
    }
    return ReassignedMoveSchema.parse(await response.json())
}

/** Move a reassigned episode, files and all, to the collection it belongs in now. */
export function useMoveToCollection(episodeSlug: string, collectionSlug?: string, words: CollectionWords = SHOW_WORDS) {
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const [moving, setMoving] = useState(false)
    const move = async () => {
        setMoving(true)
        try {
            const result = await postReassignedMove(`/episodes/${encodeURIComponent(episodeSlug)}/move-to-collection`)
            toast.success(reassignedMoveMessage(result, words))
            if (result.episodes && result.downloading === 0 && result.episodeSlug && result.collectionSlug) {
                // The episode lives in its new collection now.
                navigate(`/collection/${result.collectionSlug}/episode/${result.episodeSlug}`, {replace: true})
            }
            await Promise.all([
                queryClient.invalidateQueries({queryKey: placeKey(episodeSlug)}),
                queryClient.invalidateQueries({queryKey: ['episode', episodeSlug]}),
                ...(collectionSlug ? [
                    queryClient.invalidateQueries({queryKey: reassignedKey(collectionSlug)}),
                    queryClient.invalidateQueries({queryKey: ['collection', collectionSlug]}),
                ] : []),
            ])
        } catch (error) {
            toast.error(error instanceof Error ? error.message : `Could not move the ${words.episode.one}`)
        } finally {
            setMoving(false)
        }
    }
    return {move, moving}
}

/** Move an episode, files and all, to the season it belongs in now. */
export function useMoveToSeason(episodeSlug: string, collectionSlug?: string, words: CollectionWords = SHOW_WORDS) {
    const queryClient = useQueryClient()
    const startOperation = useStartOperation()
    const [moving, setMoving] = useState(false)
    const move = async () => {
        setMoving(true)
        try {
            await startOperation(`${apiUrl()}/episodes/${encodeURIComponent(episodeSlug)}/move-to-season`, {method: 'POST'})
            toast.success(`Moving the ${words.episode.one} and its files`)
            await Promise.all([
                queryClient.invalidateQueries({queryKey: placeKey(episodeSlug)}),
                queryClient.invalidateQueries({queryKey: ['episode', episodeSlug]}),
                ...(collectionSlug ? [queryClient.invalidateQueries({queryKey: movedKey(collectionSlug)})] : []),
            ])
        } catch (error) {
            toast.error(error instanceof OperationStartError ? error.message : `Could not move the ${words.episode.one}`)
        } finally {
            setMoving(false)
        }
    }
    return {move, moving}
}

/** Where the episode belongs now, in words. */
export function newPlace(place: SeasonPlace, words: CollectionWords = SHOW_WORDS): string {
    const season = words.season.one
    if (place.linkTitle) {
        if (place.linkKind === season) return `the ${season} ${place.linkTitle}`
        const name = place.seasonName && place.seasonName !== place.linkTitle ? ` (${place.seasonName})` : ''
        return `the ${season} of the ${place.linkKind} ${place.linkTitle}${name}`
    }
    return place.seasonName ? `the ${season} ${place.seasonName}` : `another ${season}`
}

/** Marks an episode that belongs in another season now; as text, a label on a details line. */
export function MovedBadge({onCover = false, asText = false, words}: {onCover?: boolean, asText?: boolean, words?: CollectionWords}) {
    return (
        <span className={asText ? 'episode-summary-item episode-summary-label moved-label' : `drm-badge moved-badge${onCover ? ' drm-badge-cover' : ''}`} title={movedMessage(words)}>
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')} aria-hidden="true"/>
            Moved
        </span>
    )
}

/** Marks a downloaded episode that its creator places in another collection now. */
export function ReassignedBadge({collectionTitle, onCover = false, asText = false}: {collectionTitle: string, onCover?: boolean, asText?: boolean}) {
    return (
        <span
            className={asText ? 'episode-summary-item episode-summary-label moved-label' : `drm-badge moved-badge${onCover ? ' drm-badge-cover' : ''}`}
            title={`Belongs in ${collectionTitle} now; it stays here, files and all, until you move it`}
        >
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-from-bracket')} aria-hidden="true"/>
            Reassigned
        </span>
    )
}

/** A note on a downloaded episode that its collection's link seasons now put in another season, or that its creator
 * places in another collection, with a way to move it. */
export default function SeasonPlaceNote({episodeSlug, collectionSlug, canManage, words = SHOW_WORDS, fileWords = words}: {
    episodeSlug: string, collectionSlug?: string, canManage: boolean,
    /** What the collection calls its seasons and episodes, and the downloads of them. */
    words?: CollectionWords, fileWords?: CollectionWords,
}) {
    const {data: place} = useSeasonPlace(episodeSlug)
    const {move, moving} = useMoveToSeason(episodeSlug, collectionSlug, words)
    const toCollection = useMoveToCollection(episodeSlug, collectionSlug, words)
    const {season, episode} = words
    if (place?.collectionSlug) {
        return (
            <div className="season-place-note" role="note">
                <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-from-bracket')} aria-hidden="true"/>
                <p>
                    <strong>Reassigned.</strong> Its creator places this {episode.one} in{' '}
                    <Link to={`/collection/${place.collectionSlug}`}>{place.collectionTitle}</Link> now. It is downloaded,
                    so it stays here, files and all, until you move it. Moving it renames its files into that collection,
                    or downloads it again there when that collection downloads it with another Local Media Profile; the
                    files here go once that succeeded.
                </p>
                {canManage && (
                    <button type="button" className="btn btn-small" onClick={() => void toCollection.move()} disabled={toCollection.moving}>
                        {toCollection.moving ? 'Moving…' : `Move to ${place.collectionTitle}`}
                    </button>
                )}
            </div>
        )
    }
    if (!place?.belongsElsewhere) return null

    return (
        <div className="season-place-note" role="note">
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')} aria-hidden="true"/>
            <p>
                <strong>Moved.</strong> The {place.linkKind}s of this collection changed, and this {episode.one} belongs in{' '}
                {newPlace(place, words)} now. It is downloaded, so it stays in its old {season.one} until you move it: moving it
                renames its files and puts them in the folder of its new {season.one}. Move it here, or move every such
                {' '}{episode.one} of the collection at once with <em>Rename all {fileWords.episode.one} files</em> and{' '}
                <em>Rename {season.one} folders too</em> in the collection's Actions menu.
            </p>
            {canManage && (
                <button type="button" className="btn btn-small" onClick={() => void move()} disabled={moving}>
                    {moving ? 'Moving…' : 'Move it there'}
                </button>
            )}
        </div>
    )
}
