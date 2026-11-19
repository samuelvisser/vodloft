import {z} from 'zod'
import {DwMembershipLevelReg} from '../dailywire_user_info'

export const SectionTargetValues = ['main', 'own', 'skip'] as const
export const ChannelPresetValues = ['one_show', 'per_list', 'pick'] as const

export const ChannelSectionReadSchema = z.object({
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    kind: z.enum(['feed', 'list', 'show', 'item']),
    role: z.string(),
    kindLabel: z.string().nullable(),
    itemCount: z.number().nullable(),
    imageUrl: z.string().nullable(),
    description: z.string().nullable(),
    access: z.string().nullable(),
    year: z.string().nullable().optional(),
    collectionSlug: z.string().nullable(),
    collectionTitle: z.string().nullable(),
    status: z.enum(['known', 'new', 'ignored']).default('known'),
})
export type ChannelSectionRead = z.infer<typeof ChannelSectionReadSchema>

export const SectionPlanSchema = z.object({
    ref: z.string(),
    target: z.enum(SectionTargetValues),
})
export type SectionPlan = z.infer<typeof SectionPlanSchema>

export const ChannelLookupReadSchema = z.object({
    sourceKey: z.string(),
    siteKey: z.string(),
    siteName: z.string(),
    channelLabel: z.string(),
    /** The channel's lists can be seasons of its own collection. */
    linkSeasons: z.boolean().default(false),
    ref: z.string(),
    url: z.string().nullable(),
    title: z.string(),
    handle: z.string().nullable(),
    description: z.string().nullable(),
    avatarUrl: z.string().nullable(),
    bannerUrl: z.string().nullable(),
    links: z.array(z.string()),
    facts: z.array(z.string()),
    sections: z.array(ChannelSectionReadSchema),
    presets: z.array(z.object({key: z.enum(ChannelPresetValues), plan: z.array(SectionPlanSchema)})),
    channelSlug: z.string().nullable(),
    music: z.boolean().default(false),
})
export type ChannelLookupRead = z.infer<typeof ChannelLookupReadSchema>

export const NewSectionActionValues = ['ask', 'season', 'own', 'ignore'] as const

export const ChannelReadSchema = z.object({
    id: z.number(),
    slug: z.string(),
    sourceKey: z.string(),
    site: z.object({key: z.string(), name: z.string(), linkSeasons: z.boolean().default(false)}),
    channelLabel: z.string(),
    siteRef: z.string(),
    url: z.string().nullable(),
    title: z.string(),
    handle: z.string().nullable(),
    description: z.string().nullable(),
    avatarUrl: z.string().nullable(),
    bannerUrl: z.string().nullable(),
    links: z.array(z.string()),
    facts: z.array(z.string()),
    createdAt: z.string(),
    collectionCount: z.number(),
    episodeCount: z.number(),
    newSections: z.enum(NewSectionActionValues),
    genre: z.string().nullable(),
    contentRating: z.string().nullable(),
    checkedAt: z.string().nullable(),
})
export type ChannelRead = z.infer<typeof ChannelReadSchema>

export const ChannelPageReadSchema = ChannelReadSchema.extend({
    collections: z.array(z.object({
        slug: z.string(),
        title: z.string(),
        type: z.string(),
        thumbnailLandscapePath: z.string().nullable(),
        episodeCount: z.number(),
        links: z.array(z.string()),
    })),
    sections: z.array(ChannelSectionReadSchema),
    mainCollectionSlug: z.string().nullable(),
    /** Downloaded episodes the channel places in another of its collections than the one they are in. */
    reassignedCount: z.number().default(0),
})
export type ChannelPageRead = z.infer<typeof ChannelPageReadSchema>

/** The form that adds a channel: where each of its sections goes. */
export const ChannelCreateSchema = z.object({
    sourceKey: z.string().min(1),
    url: z.string().nullable().default(null),
    ref: z.string().nullable().default(null),
    preset: z.enum(ChannelPresetValues).default('one_show'),
    sections: z.array(SectionPlanSchema).default([]),
    membershipLevel: z.enum(DwMembershipLevelReg.Enum).default(DwMembershipLevelReg.Enum.HIGHEST_ALLOWED),
    newSections: z.enum(NewSectionActionValues).default('ask'),
}).refine((value) => value.sections.some((section) => section.target !== 'skip'), {
    message: 'Pick at least one section to keep',
    path: ['sections'],
})
export type ChannelCreateIn = z.input<typeof ChannelCreateSchema>
export type ChannelCreateOut = z.output<typeof ChannelCreateSchema>

/** The form that changes how VODLoft follows a channel. */
export const ChannelUpdateSchema = z.object({
    newSections: z.enum(NewSectionActionValues).default('ask'),
    genre: z.string().trim().max(200).default(''),
    contentRating: z.string().trim().max(50).default(''),
})
export type ChannelUpdateIn = z.input<typeof ChannelUpdateSchema>
export type ChannelUpdateOut = z.output<typeof ChannelUpdateSchema>

/** The channel behind a collection's link, before the collection is added to it. */
export const CollectionChannelMatchSchema = z.object({
    siteName: z.string(),
    channelLabel: z.string(),
    ref: z.string(),
    url: z.string().nullable().optional(),
    title: z.string(),
    handle: z.string().nullable().optional(),
    avatarUrl: z.string().nullable().optional(),
    channelSlug: z.string().nullable().optional(),
    /** The channel's section the collection is, when it is one. */
    sectionTitle: z.string().nullable().optional(),
    sectionKindLabel: z.string().nullable().optional(),
    /** Another of the channel's collections that keeps this section already, and can't let it go. */
    keptBy: z.string().nullable().optional(),
    /** The playlists that would be in two places once the collection joins; each stays in one, as you choose. */
    overlaps: z.array(z.object({
        ref: z.string(),
        title: z.string(),
        keptBy: z.string(),
        /** The channel's own collection keeps it and can let it go; a collection of its own keeps what it has. */
        canMoveHere: z.boolean(),
    })).default([]),
})
export type CollectionChannelMatch = z.infer<typeof CollectionChannelMatchSchema>

export const CollectionChannelLeaveSchema = z.object({
    channelTitle: z.string(),
})
export type CollectionChannelLeave = z.infer<typeof CollectionChannelLeaveSchema>
