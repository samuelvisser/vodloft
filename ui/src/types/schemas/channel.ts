import {z} from 'zod'
import {DwMembershipLevelReg} from '../dailywire_user_info'

export const SectionTargetValues = ['main', 'own', 'skip'] as const
export const LinkPlacementValues = ['site_seasons', 'one_season', 'specials'] as const
export const ChannelPresetValues = ['one_show', 'per_list', 'pick'] as const

export const ChannelSectionReadSchema = z.object({
    ref: z.string(),
    url: z.string(),
    title: z.string(),
    kind: z.enum(['feed', 'list', 'item']),
    role: z.string(),
    kindLabel: z.string().nullable(),
    itemCount: z.number().nullable(),
    imageUrl: z.string().nullable(),
    description: z.string().nullable(),
    access: z.string().nullable(),
    hasSeasons: z.boolean(),
    year: z.string().nullable().optional(),
    collectionSlug: z.string().nullable(),
    collectionTitle: z.string().nullable(),
    status: z.enum(['known', 'new', 'ignored']).default('known'),
})
export type ChannelSectionRead = z.infer<typeof ChannelSectionReadSchema>

export const SectionPlanSchema = z.object({
    ref: z.string(),
    target: z.enum(SectionTargetValues),
    placement: z.enum(LinkPlacementValues).default('site_seasons'),
})
export type SectionPlan = z.infer<typeof SectionPlanSchema>

export const ChannelLookupReadSchema = z.object({
    sourceKey: z.string(),
    siteKey: z.string(),
    siteName: z.string(),
    channelLabel: z.string(),
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
    claimOrder: z.array(z.string()),
    presets: z.array(z.object({key: z.enum(ChannelPresetValues), plan: z.array(SectionPlanSchema)})),
    channelSlug: z.string().nullable(),
    music: z.boolean().default(false),
})
export type ChannelLookupRead = z.infer<typeof ChannelLookupReadSchema>

export const NewSectionActionValues = ['ask', 'main', 'own', 'ignore'] as const

export const ChannelOrderEntrySchema = z.object({
    ref: z.string(),
    title: z.string(),
    kind: z.enum(['feed', 'list', 'item']),
    kindLabel: z.string().nullable(),
    collectionSlug: z.string(),
    collectionTitle: z.string(),
    placement: z.enum(LinkPlacementValues),
    videoCount: z.number(),
})
export type ChannelOrderEntry = z.infer<typeof ChannelOrderEntrySchema>

export const ChannelReadSchema = z.object({
    id: z.number(),
    slug: z.string(),
    sourceKey: z.string(),
    site: z.object({key: z.string(), name: z.string()}),
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
    order: z.array(ChannelOrderEntrySchema),
    mainCollectionSlug: z.string().nullable(),
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
    order: z.array(z.string()).default([]),
})
export type ChannelUpdateIn = z.input<typeof ChannelUpdateSchema>
export type ChannelUpdateOut = z.output<typeof ChannelUpdateSchema>

export const ChannelLinkMatchSchema = z.object({
    url: z.string(),
    title: z.string().nullable().optional(),
    sectionTitle: z.string().nullable().optional(),
    sectionKindLabel: z.string().nullable().optional(),
    /** Another of the channel's collections that keeps this section already. */
    keptBy: z.string().nullable().optional(),
})
export type ChannelLinkMatch = z.infer<typeof ChannelLinkMatchSchema>

/** The channel behind a collection's links, before the collection is added to it. */
export const CollectionChannelMatchSchema = z.object({
    siteName: z.string(),
    channelLabel: z.string(),
    ref: z.string(),
    url: z.string().nullable().optional(),
    title: z.string(),
    handle: z.string().nullable().optional(),
    avatarUrl: z.string().nullable().optional(),
    channelSlug: z.string().nullable().optional(),
    links: z.array(ChannelLinkMatchSchema),
})
export type CollectionChannelMatch = z.infer<typeof CollectionChannelMatchSchema>

export const CollectionChannelLeaveSchema = z.object({
    channelTitle: z.string(),
    videosKeptElsewhere: z.number(),
})
export type CollectionChannelLeave = z.infer<typeof CollectionChannelLeaveSchema>
