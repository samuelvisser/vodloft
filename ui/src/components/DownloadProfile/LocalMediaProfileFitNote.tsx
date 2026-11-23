import {useCallback, useMemo} from 'react'
import {Link} from 'react-router-dom'

import {useLocalMediaProfileSites} from '../../lib/queries'
import {CollectionTypeReg} from '../../types/collection'
import {
    addLocalMediaProfilePath, CollectionLocalMediaProfileScopeReg, isCollectionLocalMediaProfileAvailableFor,
    isLocalMediaProfileAvailableForSite, PreferredFormatReg,
} from '../../types/local_media_profile'
import type {CollectionRead} from '../../types/schemas/collection'
import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import RequestedNote from '../common/RequestedNote'
import {nameInText} from '../../lib/nameInText'

/** Why a Local Media Profile doesn't fit a collection, and the format a link asks for, if it doesn't. */
function mismatches(
    profile: LocalMediaProfileRead,
    collection: CollectionRead,
    format: string | null | undefined,
    knownSiteKeys: readonly string[] | undefined,
): string[] {
    const reasons: string[] = []
    if (!isCollectionLocalMediaProfileAvailableFor(profile, collection.type)) {
        const scope = profile.type === 'collection' ? profile.collectionScope ?? 'podcast-and-series' : undefined
        reasons.push(`This Local Media Profile is available for ${scope ? CollectionLocalMediaProfileScopeReg.getLabelLoose(scope) : 'videos and movies'}, `
            + `not for ${CollectionTypeReg.getLabelLoose(collection.type)} collections like ${nameInText(collection.title)}.`)
    }
    if (collection.site && !isLocalMediaProfileAvailableForSite(profile, collection.site.key, knownSiteKeys)) {
        reasons.push(`It isn't available for ${collection.site.name}, where ${nameInText(collection.title)} is.`)
    }
    if (format && profile.preferredFormat !== format) {
        reasons.push(`It downloads ${PreferredFormatReg.getLabelLoose(profile.preferredFormat)}, not the requested ${PreferredFormatReg.getLabelLoose(format)}.`)
    }
    // The first reason names the profile; the ones after it go on about it.
    if (reasons.length) reasons[0] = reasons[0].replace(/^It /, 'This Local Media Profile ')
    return reasons
}

/** Whether a Local Media Profile fits a collection: it is available for the collection's kind and Site, and
 *  downloads the format a link asks for. */
export function useLocalMediaProfileFits(collection: CollectionRead | undefined, format?: string | null) {
    const {data: sites} = useLocalMediaProfileSites()
    const knownSiteKeys = sites?.sites.map((site) => site.key)
    return useCallback(
        (profile: LocalMediaProfileRead) => !collection || mismatches(profile, collection, format, knownSiteKeys).length === 0,
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [collection, format, knownSiteKeys?.join()],
    )
}

/**
 * The Collection profiles a Download Profile for this collection can use: those available for the collection's kind
 * and Site. The format a Stream Profile's link asks for doesn't narrow them; the form marks the ones that download it.
 * `keep` stays offered whatever it is, such as the profile a Download Profile already uses.
 */
export function useLocalMediaProfilesForCollection(
    profiles: readonly LocalMediaProfileRead[] | undefined,
    collection: CollectionRead | undefined,
    keep?: number | null,
): LocalMediaProfileRead[] | undefined {
    const fits = useLocalMediaProfileFits(collection)
    const {data: sites} = useLocalMediaProfileSites()
    return useMemo(() => {
        if (!profiles) return undefined
        // Before a collection is chosen, every Collection profile is offered.
        if (!collection) return profiles.filter((profile) => profile.type === 'collection')
        // A profile for upcoming Sites fits a new Site only once the known Sites are in.
        if (!sites) return undefined
        return profiles.filter((profile) => profile.type === 'collection' && (profile.id === keep || fits(profile)))
    }, [profiles, collection, sites, keep, fits])
}

/**
 * Says when the Local Media Profile chosen for a Download Profile doesn't fit its collection, or the format the link
 * that opened the form asks for. When none the collection can still take fits, it
 * offers to create one, and the profile form brings the user back here with it.
 */
export default function LocalMediaProfileFitNote({profiles, selectedId, used, collection, format, returnTo}: {
    profiles: readonly LocalMediaProfileRead[] | undefined
    selectedId: number | null | undefined
    /** The profiles the collection already has a Download Profile for. */
    used: ReadonlySet<number>
    collection: CollectionRead | undefined
    format?: string | null
    /** This form, to come back to once a profile is created. */
    returnTo: string
}) {
    const {data: sites} = useLocalMediaProfileSites()
    if (!collection || !profiles) return null
    const knownSiteKeys = sites?.sites.map((site) => site.key)
    const collectionProfiles = profiles.filter((profile) => profile.type === 'collection')
    const selected = collectionProfiles.find((profile) => profile.id === selectedId)
    const reasons = selected ? mismatches(selected, collection, format, knownSiteKeys) : []
    const anyFits = collectionProfiles.some((profile) => !used.has(profile.id)
        && mismatches(profile, collection, format, knownSiteKeys).length === 0)
    if (selected && reasons.length === 0) return null
    if (!selected && anyFits) return null

    const formatLabel = format ? PreferredFormatReg.getLabelLoose(format) : undefined
    const message = reasons.length ? reasons.join(' ')
        : formatLabel ? `No Local Media Profile for ${nameInText(collection.title)} downloads ${formatLabel} yet.`
        : `No Local Media Profile fits ${nameInText(collection.title)} yet.`
    return (
        <RequestedNote>
            {anyFits ? message : (
                <span className="requested-note__with-action">
                    <span>{message}{reasons.length > 0 && ` No Local Media Profile fits ${nameInText(collection.title)}${formatLabel ? ` and downloads ${formatLabel}` : ''} yet.`}</span>
                    <Link
                        className="btn btn-small"
                        to={addLocalMediaProfilePath({
                            collectionType: collection.type,
                            siteKey: collection.site?.key,
                            format,
                            returnTo,
                            from: collection.title,
                            collectionId: collection.id,
                        })}
                    >
                        {formatLabel ? `Create one for ${formatLabel}` : 'Create one'}
                    </Link>
                </span>
            )}
        </RequestedNote>
    )
}
