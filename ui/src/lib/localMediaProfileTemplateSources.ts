import {useState} from 'react'
import {useQuery} from '@tanstack/react-query'

import {useLazyCollection} from './lazyCollection'

import type {CollectionLocalMediaProfileScope} from '../types/local_media_profile'
import {apiUrl} from './api'

export type LocalMediaProfileTemplateSourceMode = 'collection' | 'movie' | 'video'

export type LocalMediaProfileTemplateVariable = {
    name: string
    description: string
}

export type LocalMediaProfileTemplateSource = {
    id: string
    label: string
    values: Record<string, string>
    fallback: boolean
    /** An example of a collection that is not saved yet: the values it shows by name. */
    pending?: string[]
}

export type LocalMediaProfileTemplateSourcePage = {
    items: LocalMediaProfileTemplateSource[]
    limit: number
    nextCursor?: string | null
    previousCursor?: string | null
    hasMore: boolean
    hasPrevious?: boolean
    revision: string
}

type LocalMediaProfileTemplateSourceOptions = {
    collectionScope?: CollectionLocalMediaProfileScope
    search?: string
    enabled?: boolean
    pageSize?: number
    anchorSourceId?: string
    /** Only media on these Sites, as the profile's Sites filter offers it; undefined for every Site. */
    siteKeys?: string[]
}

async function fetchTemplateJson<T>(
    path: string,
    signal?: AbortSignal,
    cache?: RequestCache,
): Promise<T> {
    const response = await fetch(
        `${apiUrl()}/local-media-profiles/template/${path}`,
        {signal, credentials: 'include', cache},
    )
    if (!response.ok) throw new Error(`Failed to load template data (${response.status})`)
    return response.json() as Promise<T>
}

/** The Sites a profile is for, as the server reads them: comma-separated, empty for none. */
function sitesParam(siteKeys: string[] | undefined): string | undefined {
    return siteKeys ? [...siteKeys].sort().join(',') : undefined
}

export function useLocalMediaProfileTemplateVariables(
    mode: LocalMediaProfileTemplateSourceMode,
    enabled = true,
) {
    return useQuery<LocalMediaProfileTemplateVariable[]>({
        queryKey: ['localMediaProfileTemplateVariables', mode],
        enabled,
        queryFn: ({signal}) => fetchTemplateJson(
            `variables?type=${encodeURIComponent(mode)}`,
            signal,
        ),
        staleTime: 30_000,
    })
}

export function useLocalMediaProfileTemplateSources(
    mode: LocalMediaProfileTemplateSourceMode,
    {
        collectionScope = 'both',
        search = '',
        enabled = true,
        pageSize = 30,
        anchorSourceId,
        siteKeys,
    }: LocalMediaProfileTemplateSourceOptions = {},
) {
    const sites = sitesParam(siteKeys)
    const effectiveAnchorSourceId = mode === 'collection' && !search.trim()
        ? anchorSourceId
        : undefined

    return useLazyCollection<LocalMediaProfileTemplateSource>({
        collectionPrefix: ['localMediaProfileTemplateSources'] as const,
        queryKey: [
            mode,
            collectionScope,
            search.trim(),
            effectiveAnchorSourceId ?? null,
            sites ?? null,
        ] as const,
        initialCount: pageSize,
        batchSize: pageSize,
        enabled,
        fetchPage: async ({cursor, limit}, signal) => {
            const params = new URLSearchParams({
                type: mode,
                limit: String(limit),
            })
            if (cursor) {
                params.set('cursor', cursor)
            } else if (effectiveAnchorSourceId) {
                params.set('anchor_source_id', effectiveAnchorSourceId)
            }
            if (mode === 'collection') params.set('collection_scope', collectionScope)
            if (search.trim()) params.set('search', search.trim())
            if (sites !== undefined) params.set('sites', sites)
            return fetchTemplateJson<LocalMediaProfileTemplateSourcePage>(
                `sources?${params.toString()}`,
                signal,
            )
        },
    })
}



export function useRandomCollectionTemplateSource(
    collectionScope: CollectionLocalMediaProfileScope = 'both',
    enabled = true,
    /** A saved profile starts on an episode of a collection that downloads to it. */
    localMediaProfileId: number | null = null,
    siteKeys?: string[],
) {
    const sites = sitesParam(siteKeys)
    // A per-mount key makes reopening the form request a fresh example instead
    // of reusing React Query's cache from the previous page visit.
    const [requestKey] = useState(() => Math.random())
    return useQuery<LocalMediaProfileTemplateSource | null>({
        queryKey: ['randomCollectionTemplateSource', collectionScope, localMediaProfileId, sites ?? null, requestKey],
        enabled,
        queryFn: ({signal}) => fetchTemplateJson(
            `sources/random-collection-episode?collection_scope=${encodeURIComponent(collectionScope)}`
            + (localMediaProfileId !== null ? `&local_media_profile_id=${localMediaProfileId}` : '')
            + (sites !== undefined ? `&sites=${encodeURIComponent(sites)}` : ''),
            signal,
            'no-store',
        ),
        staleTime: Infinity,
    })
}
