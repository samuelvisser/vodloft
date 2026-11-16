import {z} from 'zod'
import {StreamProfileFieldsReadSchema, StreamProfileFieldsSchema} from './stream_profile_fields'

// ---------- Strict request (create/update) ----------
const IptvStreamProfileBaseSchema = StreamProfileFieldsSchema.extend({
    // A channel plays live episodes as they air, so it starts with them on.
    streamLiveEpisodes: z.boolean().default(true),
    // Empty takes the number after the owner's highest channel.
    channelNumber: z.int().min(1).max(99999).nullable().default(null),
    // Empty uses the collection's Site name.
    channelGroup: z.string().trim().nullable().default(null),
})

const validateLive = (value: {preferredFormat: string; streamLiveEpisodes: boolean}, ctx: z.RefinementCtx) => {
    if (value.streamLiveEpisodes && value.preferredFormat === 'format_audio_only') {
        ctx.addIssue({
            code: 'custom',
            path: ['streamLiveEpisodes'],
            message: 'Live episode streaming requires a video preferred format',
        })
    }
}

export const IptvStreamProfileCreateSchema = IptvStreamProfileBaseSchema.extend({
    collectionId: z.int(),
}).superRefine(validateLive)
export type IptvStreamProfileCreateIn = z.input<typeof IptvStreamProfileCreateSchema>
export type IptvStreamProfileCreateOut = z.output<typeof IptvStreamProfileCreateSchema>

export const IptvStreamProfileUpdateSchema = IptvStreamProfileBaseSchema.superRefine(validateLive)
export type IptvStreamProfileUpdateIn = z.input<typeof IptvStreamProfileUpdateSchema>
export type IptvStreamProfileUpdateOut = z.output<typeof IptvStreamProfileUpdateSchema>

export const IptvStreamProfileReadSchema = StreamProfileFieldsReadSchema.extend({
    type: z.literal('iptv'),
    channelNumber: z.int(),
    channelGroup: z.string().nullable(),
    playlistPath: z.string(),
    guidePath: z.string(),
})
export type IptvStreamProfileRead = z.infer<typeof IptvStreamProfileReadSchema>
