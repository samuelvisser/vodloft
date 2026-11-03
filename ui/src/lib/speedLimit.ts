import {useQuery} from '@tanstack/react-query'

import {SpeedLimitStatusSchema} from '../types/schemas/settings'
import {errorMessage} from './users'

function base(): string {
    return ((window as any).appConfig?.API_URL || '/api').replace(/\/+$/, '')
}

/** How fast downloads may go right now; it follows saved settings and new measurements. */
export function useSpeedLimitStatus(savedSettingsVersion: unknown) {
    return useQuery({
        queryKey: ['settings', 'speedLimit', savedSettingsVersion],
        queryFn: async ({signal}) => {
            const response = await fetch(`${base()}/settings/speed-limit`, {signal, credentials: 'include'})
            if (!response.ok) throw new Error(await errorMessage(response))
            return SpeedLimitStatusSchema.parse(await response.json())
        },
        refetchInterval: 60_000,
    })
}
