import {useQuery} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {z} from 'zod'

import {apiUrl} from '../../lib/api'
import {faIcon} from '../../icons/faIcon'
import {collectionWords, CollectionWords} from '../../lib/collectionWords'
import {NamesSchema} from '../../types/schemas/source'
import '../common/DrmProtected.css'
import './SeasonPlaceNote.css'

const SeasonPlaceSchema = z.object({
    belongsElsewhere: z.boolean(),
    seasonName: z.string().nullable().optional(),
    linkTitle: z.string().nullable().optional(),
    /** What the collection's Site calls its link seasons, such as playlists. */
    linkNames: NamesSchema.nullable().optional(),
})
type SeasonPlace = z.infer<typeof SeasonPlaceSchema>

const MovedEpisodesSchema = z.object({episodeSlugs: z.array(z.string())})



/** What the Moved badge explains, in the collection's words. */
export const movedMessage = (words: CollectionWords = collectionWords(null)) =>
    `Belongs in another ${words.season.singular} now; it stays where it is until you move it, files and all`

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

/** Where the episode belongs now, in words. */
export function newPlace(place: SeasonPlace, words: CollectionWords = collectionWords(null)): string {
    const season = words.season.singular
    if (place.linkTitle) {
        if (place.linkNames?.singular === season) return `the ${season} ${place.linkTitle}`
        const name = place.seasonName && place.seasonName !== place.linkTitle ? ` (${place.seasonName})` : ''
        return `the ${season} of the ${place.linkNames?.singular} ${place.linkTitle}${name}`
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

/** A note on a downloaded episode that its collection's link seasons now put in another season, with a way to move
 * it. */
export default function SeasonPlaceNote({episodeSlug, canManage, onMove, words = collectionWords(null), fileWords = words}: {
    episodeSlug: string, canManage: boolean,
    /** Opens the episode's Move action. */
    onMove: () => void,
    /** What the collection calls its seasons and episodes, and the downloads of them. */
    words?: CollectionWords, fileWords?: CollectionWords,
}) {
    const {data: place} = useSeasonPlace(episodeSlug)
    const {season, episode} = words
    if (!place?.belongsElsewhere) return null

    return (
        <div className="season-place-note" role="note">
            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-arrow-left')} aria-hidden="true"/>
            <p>
                <strong>Moved.</strong> The {place.linkNames?.plural} of this collection changed, and this {episode.singular} belongs in{' '}
                {newPlace(place, words)} now. It is downloaded, so it stays in its old {season.singular} until you move it: moving it
                renames its files and puts them in the folder of its new {season.singular}. Move it here, or move every such
                {' '}{episode.singular} of the collection at once with <em>Move {fileWords.episode.plural}</em> in the collection's
                {' '}Actions menu.
            </p>
            {canManage && (
                <button type="button" className="btn btn-small" onClick={onMove}>
                    Move it there
                </button>
            )}
        </div>
    )
}
