import {createContext, useContext, useMemo} from 'react'
import {useQuery} from '@tanstack/react-query'

import type {CollectionCreatePayloadOut} from '../types/schemas/collection'
import type {SeasonDetachedOut} from '../types/schemas/season'
import type {LocalMediaProfileTemplateSource} from './localMediaProfileTemplateSources'

/** A collection the Add collection form describes before it is saved. */
export type ExampleCollection = {
    sourceKey: string
    sharingUrl: string
    slug: string
    title: string
    authorName: string
    type: string
    episodeIdentifier: string
    seasons: {slug: string, name: string}[]
}

/**
 * The newest episodes of a collection that is being added. The server looks them up with the
 * Source's cheapest lookup and keeps them in memory only; nothing is saved.
 */
export type CollectionExamples = {
    collection: ExampleCollection
    sources: LocalMediaProfileTemplateSource[] | undefined
    loading: boolean
    failed: boolean
}

export const CollectionExamplesContext = createContext<CollectionExamples | null>(null)

/** The examples of the collection being added, inside the Add collection form; null elsewhere. */
export function useCollectionExamples(): CollectionExamples | null {
    return useContext(CollectionExamplesContext)
}

export function isExampleSource(source: {id: string} | null | undefined): boolean {
    return !!source?.id.startsWith('new-episode:')
}

/** Starts looking up the examples as soon as the collection is chosen, without holding anything up. */
export function useCollectionExamplesQuery(
    collection: CollectionCreatePayloadOut | undefined,
    seasons: SeasonDetachedOut[] | undefined,
): CollectionExamples | null {
    const example = useMemo<ExampleCollection | null>(() => collection ? {
        sourceKey: collection.sourceKey,
        sharingUrl: collection.sharingUrl || collection.url,
        slug: collection.slug,
        title: collection.title,
        authorName: collection.authorName,
        type: collection.type,
        episodeIdentifier: collection.episodeIdentifier,
        seasons: (seasons ?? []).map(({slug, name}) => ({slug, name})),
    } : null, [collection, seasons])
    const query = useQuery<LocalMediaProfileTemplateSource[]>({
        queryKey: ['collectionExamples', example],
        enabled: example !== null,
        queryFn: async ({signal}) => {
            const response = await fetch(
                `${(window as any).appConfig.API_URL}/local-media-profiles/template/sources/examples`,
                {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(example),
                    signal,
                },
            )
            if (!response.ok) throw new Error(`Could not look up the newest episodes (${response.status})`)
            return response.json() as Promise<LocalMediaProfileTemplateSource[]>
        },
        // The server keeps them for a while too; going back and forth asks nothing new.
        staleTime: 15 * 60_000,
        retry: false,
    })
    return useMemo(() => example ? {
        collection: example,
        sources: query.data,
        loading: query.isPending,
        failed: query.isError,
    } : null, [example, query.data, query.isPending, query.isError])
}
