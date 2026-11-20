import {useQuery} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {z} from 'zod'
import {Link} from 'react-router-dom'

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
    /** Reassigned: the collection of its creator that the episode belongs in now. */
    collectionSlug: z.string().nullable().optional(),
    collectionTitle: z.string().nullable().optional(),
})
type SeasonPlace = z.infer<typeof SeasonPlaceSchema>

const MovedEpisodesSchema = z.object({episodeSlugs: z.array(z.string())})
const ReassignedEpisodesSchema = z.object({
    episodes: z.array(z.object({episodeSlug: z.string(), collectionSlug: z.string(), collectionTitle: z.string()})),
})



/** What the Moved badge explains, in the collection's words. */
export const movedMessage = (words: CollectionWords = collectionWords(null)) =>
    `Belongs in another ${words.season.singular} now; it stays where it is until you move it, files and all`

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
export default function SeasonPlaceNote({episodeSlug, canManage, onMove, words = collectionWords(null), fileWords = words}: {
    episodeSlug: string, canManage: boolean,
    /** Opens the episode's Move action. */
    onMove: () => void,
    /** What the collection calls its seasons and episodes, and the downloads of them. */
    words?: CollectionWords, fileWords?: CollectionWords,
}) {
    const {data: place} = useSeasonPlace(episodeSlug)
    const {season, episode} = words
    if (place?.collectionSlug) {
        return (
            <div className="season-place-note" role="note">
                <FontAwesomeIcon icon={faIcon('fass', 'arrow-right-from-bracket')} aria-hidden="true"/>
                <p>
                    <strong>Reassigned.</strong> Its creator places this {episode.singular} in{' '}
                    <Link to={`/collection/${place.collectionSlug}`}>{place.collectionTitle}</Link> now. It is downloaded,
                    so it stays here, files and all, until you move it. Moving it renames its files into that collection,
                    or downloads it again there when that collection downloads it with another Local Media Profile; the
                    files here go once that succeeded.
                </p>
                {canManage && (
                    <button type="button" className="btn btn-small" onClick={onMove}>
                        Move to {place.collectionTitle}
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
