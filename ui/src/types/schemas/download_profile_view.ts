import {z} from 'zod'
import {DownloadProfileReadSchema} from './download_profile'

// Unified read view for a download profile coming from /download-profiles/as-view
export const DownloadProfileReadViewSchema = DownloadProfileReadSchema.extend({
    // External table fields
    collectionTitle: z.string(),
    collectionSlug: z.string(),
    collectionType: z.string(),
    collectionSourceKey: z.string(),
    collectionSiteKey: z.string().nullable().optional().default(null),
    collectionEpisodeIdentifier: z.string(),
    localMediaProfileName: z.string(),
    localMediaProfilePreferredFormat: z.string(),
    // Disk space this profile's downloaded files take
    storageSizeBytes: z.number(),
})
export type DownloadProfileReadView = z.infer<typeof DownloadProfileReadViewSchema>
