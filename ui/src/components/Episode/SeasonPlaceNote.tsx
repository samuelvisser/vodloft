import {useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'
import {z} from 'zod'

import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {faIcon} from '../../icons/faIcon'
import '../common/DrmProtected.css'
import './SeasonPlaceNote.css'

const SeasonPlaceSchema = z.object({
    belongsElsewhere: z.boolean(),
    seasonName: z.string().nullable().optional(),
    linkTitle: z.string().nullable().optional(),
    linkKind: z.string().default('playlist'),
})
type SeasonPlace = z.infer<typeof SeasonPlaceSchema>

const MovedEpisodesSchema = z.object({episodeSlugs: z.array(z.string())})

export const MOVED_MESSAGE = 'Belongs in another season now; it stays where it is until you move it, files and all'

const placeKey = (episodeSlug: string) => ['episode', episodeSlug, 'seasonPlace']
const movedKey = (collectionSlug: string) => ['collection', collectionSlug, 'movedEpisodes']

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

/** Move an episode, files and all, to the season it belongs in now. */
export function useMoveToSeason(episodeSlug: string, collectionSlug?: string) {
    const queryClient = useQueryClient()
    const startOperation = useStartOperation()
    const [moving, setMoving] = useState(false)
    const move = async () => {
        setMoving(true)
        try {
            await startOperation(`${apiUrl()}/episodes/${encodeURIComponent(episodeSlug)}/move-to-season`, {method: 'POST'})
            toast.success('Moving the episode and its files')
            await Promise.all([
                queryClient.invalidateQueries({queryKey: placeKey(episodeSlug)}),
                queryClient.invalidateQueries({queryKey: ['episode', episodeSlug]}),
                ...(collectionSlug ? [queryClient.invalidateQueries({queryKey: movedKey(collectionSlug)})] : []),
            ])
        } catch (error) {
            toast.error(error instanceof OperationStartError ? error.message : 'Could not move the episode')
        } finally {
            setMoving(false)
        }
    }
    return {move, moving}
}

/** Where the episode belongs now, in words. */
export function newPlace(place: SeasonPlace): string {
    if (place.linkTitle) {
        const season = place.seasonName && place.seasonName !== place.linkTitle ? ` (${place.seasonName})` : ''
        return `the season of the ${place.linkKind} ${place.linkTitle}${season}`
    }
    return place.seasonName ? `the season ${place.seasonName}` : 'another season'
}

/** Marks an episode that belongs in another season now; as text, a label on a details line. */
export function MovedBadge({onCover = false, asText = false}: {onCover?: boolean, asText?: boolean}) {
    return (
        <span className={asText ? 'episode-summary-item episode-summary-label moved-label' : `drm-badge moved-badge${onCover ? ' drm-badge-cover' : ''}`} title={MOVED_MESSAGE}>
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')} aria-hidden="true"/>
            Moved
        </span>
    )
}

/** A note on a downloaded episode that its collection's link seasons now put in another season, with a way to move it. */
export default function SeasonPlaceNote({episodeSlug, collectionSlug, canManage}: {episodeSlug: string, collectionSlug?: string, canManage: boolean}) {
    const {data: place} = useSeasonPlace(episodeSlug)
    const {move, moving} = useMoveToSeason(episodeSlug, collectionSlug)
    if (!place?.belongsElsewhere) return null

    return (
        <div className="season-place-note" role="note">
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')} aria-hidden="true"/>
            <p>
                <strong>Moved.</strong> The {place.linkKind}s of this collection changed, and this episode belongs in{' '}
                {newPlace(place)} now. It is downloaded, so it stays in its old season until you move it: moving it
                renames its files and puts them in the folder of its new season. Move it here, or move every such
                episode of the collection at once with <em>Rename all episode files</em> and <em>Rename season folders
                too</em> in the collection's Actions menu.
            </p>
            {canManage && (
                <button type="button" className="btn btn-small" onClick={() => void move()} disabled={moving}>
                    {moving ? 'Moving…' : 'Move it there'}
                </button>
            )}
        </div>
    )
}
