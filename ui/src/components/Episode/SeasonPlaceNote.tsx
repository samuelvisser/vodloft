import {useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import toast from 'react-hot-toast'
import {z} from 'zod'

import {apiUrl} from '../../lib/api'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {faIcon} from '../../icons/faIcon'
import './SeasonPlaceNote.css'

const SeasonPlaceSchema = z.object({
    belongsElsewhere: z.boolean(),
    seasonName: z.string().nullable().optional(),
    linkTitle: z.string().nullable().optional(),
    linkKind: z.string().default('playlist'),
})

/** A note on a downloaded episode that its collection's link seasons now put in another season, with a way to move it. */
export default function SeasonPlaceNote({episodeSlug, canManage}: {episodeSlug: string, canManage: boolean}) {
    const queryClient = useQueryClient()
    const startOperation = useStartOperation()
    const [moving, setMoving] = useState(false)
    const queryKey = ['episode', episodeSlug, 'seasonPlace']
    const {data: place} = useQuery({
        queryKey,
        queryFn: async ({signal}) => {
            const response = await fetch(`${apiUrl()}/episodes/${encodeURIComponent(episodeSlug)}/season-place`, {signal, credentials: 'include'})
            return response.ok ? SeasonPlaceSchema.parse(await response.json()) : null
        },
    })
    if (!place?.belongsElsewhere) return null

    const where = place.linkTitle
        ? `the season of the ${place.linkKind} ${place.linkTitle}${place.seasonName && place.seasonName !== place.linkTitle ? ` (${place.seasonName})` : ''}`
        : place.seasonName ? `the season ${place.seasonName}` : 'another season'
    const move = async () => {
        setMoving(true)
        try {
            await startOperation(`${apiUrl()}/episodes/${encodeURIComponent(episodeSlug)}/move-to-season`, {method: 'POST'})
            toast.success('Moving the episode and its files')
            await queryClient.invalidateQueries({queryKey})
            await queryClient.invalidateQueries({queryKey: ['episode', episodeSlug]})
        } catch (error) {
            toast.error(error instanceof OperationStartError ? error.message : 'Could not move the episode')
        } finally {
            setMoving(false)
        }
    }

    return (
        <div className="season-place-note" role="note">
            <FontAwesomeIcon icon={faIcon('fass', 'folder')} aria-hidden="true"/>
            <p>
                This episode belongs in {where} now. It stays where it is because it is downloaded, so its files
                keep their place.
            </p>
            {canManage && (
                <button type="button" className="btn btn-small" onClick={() => void move()} disabled={moving}>
                    {moving ? 'Moving…' : 'Move it there'}
                </button>
            )}
        </div>
    )
}
