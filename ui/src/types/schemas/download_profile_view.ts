import {z} from 'zod'
import {DownloadProfileReadSchema} from './download_profile'

// Unified read view for a download profile coming from /download-profiles/as-view
export const DownloadProfileReadViewSchema = DownloadProfileReadSchema.extend({
    // External table fields
    showTitle: z.string(),
    showSlug: z.string(),
    showType: z.string(),
    showEpisodeIdentifier: z.string(),
    localMediaProfileName: z.string(),
    localMediaProfilePreferredFormat: z.string(),
})
export type DownloadProfileReadView = z.infer<typeof DownloadProfileReadViewSchema>
