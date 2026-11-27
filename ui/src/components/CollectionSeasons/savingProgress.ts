import {useQuery} from '@tanstack/react-query'
import {z} from 'zod'

import {apiUrl} from '../../lib/api'
import {planSteps} from '../../lib/progressPlan'
import type {ProgressStep} from '../../types/progress'
import {PlanSchema} from '../../types/schemas/progress_plan'

const SavingSchema = z.object({plan: PlanSchema.nullable().default(null)})

/** The steps of a Seasons save while it runs, as the server follows it by the dialog's token: the Seasons dialog's
 * own save, or one collection's in the Library's bulk edit. Empty until the save has started. */
export function useSavingSteps(collectionSlug: string | undefined, token: string, saving: boolean): ProgressStep[] {
    const {data} = useQuery({
        queryKey: ['seasonsSaving', collectionSlug, token] as const,
        enabled: saving && !!collectionSlug,
        queryFn: async ({signal}) => {
            const response = await fetch(
                `${apiUrl()}/collections/${encodeURIComponent(collectionSlug!)}/season-settings/saving?token=${encodeURIComponent(token)}`,
                {credentials: 'include', signal},
            )
            if (!response.ok) return null
            return SavingSchema.parse(await response.json()).plan
        },
        refetchInterval: saving ? 500 : false,
        staleTime: 0, gcTime: 0, retry: false,
    })
    return saving && data ? planSteps(data.stages, (stage) => stage.label ?? 'Working') : []
}
