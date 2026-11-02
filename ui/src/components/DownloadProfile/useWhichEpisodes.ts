import {useEffect, useState} from 'react'

import {WhichEpisodesSchema, type EpisodeRule, type WhichEpisodes} from '../../types/schemas/download_profile'

export type WhichEpisodesRequest = {
    collectionId: number
    epIdTypeList: string[]
    downloadWithCountdown: boolean
    downloadDaysInPast: number
    downloadEpisodeCount: number
    downloadStartingFrom: string | null
    seasonSlugs: string[]
    includeUpcomingSeasons: boolean
    rules: EpisodeRule[]
    includeEpisodes: boolean
}

/** How many indexed episodes each Which episodes line leaves out; asked again shortly after each change. */
export function useWhichEpisodes(request: WhichEpisodesRequest | null): {result: WhichEpisodes | null; loading: boolean} {
    const serialized = request ? JSON.stringify(request) : null
    const [state, setState] = useState<{result: WhichEpisodes | null; loading: boolean}>({result: null, loading: false})

    useEffect(() => {
        if (!serialized) {
            setState({result: null, loading: false})
            return
        }
        const controller = new AbortController()
        setState((current) => ({...current, loading: true}))
        const timer = window.setTimeout(async () => {
            try {
                const response = await fetch(`${(window as any).appConfig.API_URL}/download-profiles/which-episodes`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    signal: controller.signal,
                    body: serialized,
                })
                // A line that is still being typed (an unfinished pattern) cannot be counted yet; keep the last counts.
                if (!response.ok) {
                    setState((current) => ({...current, loading: false}))
                    return
                }
                setState({result: WhichEpisodesSchema.parse(await response.json()), loading: false})
            } catch {
                if (!controller.signal.aborted) setState((current) => ({...current, loading: false}))
            }
        }, 300)
        return () => {
            controller.abort()
            window.clearTimeout(timer)
        }
    }, [serialized])

    return state
}
