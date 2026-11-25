import {createContext, type ReactNode, useContext} from 'react'

import RequestedField, {useRequestedOrigin} from '../common/RequestedField'
import type {LocalMediaProfileType} from '../../types/local_media_profile'

/** What a profile form was opened for, from a link on the page of a collection, video or movie: the profile type,
 *  what it has to be available for and the Site. The fields these set say so when the user changes them to
 *  something that no longer fits. */
export type ProfileFit = {
    type?: LocalMediaProfileType
    scope?: string | null
    site?: string | null
    /** The download format, such as the one a Stream Profile streams. It only fills the field in. */
    format?: string | null
    /** The collection whose page the link is on: the example episodes come from it. */
    collectionId?: number
}

const ProfileFitContext = createContext<ProfileFit>({})
export const ProfileFitProvider = ProfileFitContext.Provider

/** What the link asked for, for a field of a profile of this type. */
export function useProfileFit(mode: LocalMediaProfileType): ProfileFit {
    const fit = useContext(ProfileFitContext)
    return !fit.type || fit.type === mode ? fit : {}
}

/** The choices of Available for that fit what a link asks for, broadest last, and how to name them. */
const SCOPE_FITS: Record<string, {fits: readonly string[], needs: string}> = {
    podcast: {fits: ['podcast', 'podcast-and-series'], needs: 'Podcasts, or Podcasts and Series'},
    series: {fits: ['series', 'podcast-and-series'], needs: 'Series, or Podcasts and Series'},
    music: {fits: ['music'], needs: 'Music'},
    videos: {fits: ['videos', 'both'], needs: 'Videos, or Videos and movies'},
    movies: {fits: ['movies', 'both'], needs: 'Movies, or Videos and movies'},
}

/** What a profile of this type is available for when it hasn't chosen yet. */
const DEFAULT_SCOPE: Record<LocalMediaProfileType, string> = {collection: 'podcast-and-series', video: 'both'}

/** The default Available for of the profile type a link's ``asked`` belongs to. */
function defaultScope(asked: string | null | undefined): string {
    return asked === 'videos' || asked === 'movies' ? DEFAULT_SCOPE.video : DEFAULT_SCOPE.collection
}

/** Where the user came from, for a note: the name the link gives, or "where you came from". */
export function OriginName({prefix}: {prefix: string}) {
    const origin = useRequestedOrigin()
    return origin ? <>{prefix} <strong>{origin}</strong></> : <>where you came from</>
}

/** Whether a profile available for ``scope`` is offered for what the link asks for. */
export function scopeFits(asked: string | null | undefined, scope: string | null | undefined): boolean {
    const wanted = asked ? SCOPE_FITS[asked] : undefined
    return !wanted || wanted.fits.includes(scope ?? defaultScope(asked))
}

/**
 * The Available for a link asks for: the broadest choice that fits it. A profile already available for it keeps its
 * choice; one for something else becomes available for both kinds, and for music it has to be the one asked for.
 */
export function fittingScope(asked: string, scope: string | null | undefined): string {
    if (scopeFits(asked, scope)) return scope ?? defaultScope(asked)
    const fits = SCOPE_FITS[asked]?.fits
    return fits ? fits[fits.length - 1] : asked
}

/** Available for, as a link fills it in. */
export function ScopeRequestedField({mode, scope, apply, children}: {
    mode: LocalMediaProfileType
    scope: string | null | undefined
    /** Sets Available for to the choice that fits, and returns the other fields that changed with it. */
    apply: (next: string) => readonly string[] | void
    children: ReactNode
}) {
    const fit = useProfileFit(mode)
    const field = mode === 'collection' ? 'collectionScope' : 'videoScope'
    const wanted = fit.scope ? SCOPE_FITS[fit.scope] : undefined
    return (
        <RequestedField
            id={field}
            requested={wanted ? fit.scope : undefined}
            value={scope}
            fields={[field]}
            apply={() => {
                const next = fittingScope(fit.scope!, scope)
                return next === (scope ?? DEFAULT_SCOPE[mode]) ? [] : apply(next)
            }}
            fits={() => scopeFits(fit.scope, scope)}
            incompatible={wanted && <>This profile won't be offered <OriginName prefix="for"/>, which needs {wanted.needs}.</>}
        >
            {children}
        </RequestedField>
    )
}
