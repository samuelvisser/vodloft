import {useCallback, useEffect, useRef, useState} from 'react'

import type {ExampleCollection} from '../../lib/collectionExamples'
import {WhichEpisodesSchema, type EpisodeFilter, type WhichEpisodes} from '../../types/schemas/download_profile'
import {apiUrl} from '../../lib/api'

export type WhichEpisodesRequest = {
    /** The saved Collection, or the newest episodes of the one that is being added. */
    collectionId?: number
    exampleCollection?: ExampleCollection
    downloadWithCountdown: boolean
    filters: EpisodeFilter[]
    includeEpisodes: boolean
}

export type WhichEpisode = NonNullable<WhichEpisodes['episodes']>[number]

/** Episodes asked for at a time while scrolling through the list. */
const PAGE_SIZE = 50
/** The most the backend sends in one page; a changed line asks again for what was already loaded, up to this. */
const MAX_PAGE_SIZE = 200

type State = {
    result: WhichEpisodes | null
    loading: boolean
    /** The episodes loaded so far, newest first; null while the list is not asked for. */
    episodes: WhichEpisode[] | null
    loadingMore: boolean
    /** The last page could not be loaded; the list waits for a retry instead of asking again by itself. */
    moreFailed: boolean
}

async function fetchPage(body: string, offset: number, limit: number, signal: AbortSignal): Promise<WhichEpisodes | null> {
    const response = await fetch(`${apiUrl()}/download-profiles/which-episodes`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        signal,
        body: JSON.stringify({...JSON.parse(body), episodesOffset: offset, episodesLimit: limit}),
    })
    // A filter that is still being typed (an unfinished pattern) cannot be counted yet; keep the last counts.
    if (!response.ok) return null
    return WhichEpisodesSchema.parse(await response.json())
}

/**
 * How many indexed episodes each Which episodes filter leaves out; asked again shortly after each change.
 * With includeEpisodes, the list of episodes comes a page at a time: call loadMore for the next one.
 */
export function useWhichEpisodes(request: WhichEpisodesRequest | null): State & {hasMore: boolean; loadMore: () => void} {
    const serialized = request ? JSON.stringify(request) : null
    const [state, setState] = useState<State>({result: null, loading: false, episodes: null, loadingMore: false, moreFailed: false})
    // Read by loadMore and by the next change without making either run again.
    const current = useRef({serialized, state})
    current.current = {serialized, state}
    const more = useRef<AbortController | null>(null)

    useEffect(() => {
        more.current?.abort()
        if (!serialized) {
            setState({result: null, loading: false, episodes: null, loadingMore: false, moreFailed: false})
            return
        }
        const controller = new AbortController()
        // Keep the episodes already scrolled past, so a changed line does not jump the list back to the top.
        const loaded = current.current.state.episodes?.length ?? 0
        const limit = Math.min(Math.max(PAGE_SIZE, loaded), MAX_PAGE_SIZE)
        setState((value) => ({...value, loading: true, loadingMore: false}))
        const timer = window.setTimeout(async () => {
            try {
                const result = await fetchPage(serialized, 0, limit, controller.signal)
                setState((value) => result
                    ? {result, loading: false, episodes: result.episodes ?? null, loadingMore: false, moreFailed: false}
                    : {...value, loading: false})
            } catch {
                if (!controller.signal.aborted) setState((value) => ({...value, loading: false}))
            }
        }, 300)
        return () => {
            controller.abort()
            window.clearTimeout(timer)
        }
    }, [serialized])

    const hasMore = !!state.result && !!state.episodes && state.episodes.length < state.result.total

    const loadMore = useCallback(() => {
        const {serialized: body, state: value} = current.current
        if (!body || !value.result || !value.episodes || value.loading || value.loadingMore) return
        if (value.episodes.length >= value.result.total) return
        const controller = new AbortController()
        more.current = controller
        const offset = value.episodes.length
        setState((previous) => ({...previous, loadingMore: true, moreFailed: false}))
        fetchPage(body, offset, PAGE_SIZE, controller.signal).then((page) => {
            if (controller.signal.aborted) return
            setState((previous) => ({
                ...previous,
                loadingMore: false,
                moreFailed: !page?.episodes,
                episodes: page?.episodes && previous.episodes?.length === offset
                    ? [...previous.episodes, ...page.episodes]
                    : previous.episodes,
            }))
        }).catch(() => {
            if (!controller.signal.aborted) setState((previous) => ({...previous, loadingMore: false, moreFailed: true}))
        })
    }, [])

    useEffect(() => () => more.current?.abort(), [])

    return {...state, hasMore, loadMore}
}
