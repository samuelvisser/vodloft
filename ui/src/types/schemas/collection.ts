import {z} from "zod";
import {EpisodeIdentifierReg, EpisodeOrderReg, CollectionTypeReg} from "../collection";
import {DwMembershipLevelReg} from "../dailywire_user_info";
import {ApiDateTimeSchema} from "./datetime";
import {SiteReadSchema, SourcedFields} from "./source";


/** Ensure https:// if a scheme is missing */
function ensureProtocol(input: string): string {
    let v = (input ?? "").trim();
    if (!v) return v;
    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(v)) v = "https://" + v;
    return v;
}

function isDailyWire(url: URL): boolean {
    const host = url.hostname.toLowerCase();
    return host === "dailywire.com" || host === "www.dailywire.com";
}

/** A show's link. Daily Wire links must point at a collection page; other sites keep their full link. */
const collectionUrl = z
    .string()
    .nonempty({message: "URL is required"})
    .default('')
    .transform(ensureProtocol)
    .transform((s) => {
        try {
            const u = new URL(s);
            return isDailyWire(u) ? `${u.origin}${u.pathname}` : s;
        } catch {
            // let the later refinements surface the error
            return s;
        }
    })
    .refine((s) => {
        try {
            return ["http:", "https:"].includes(new URL(s).protocol);
        } catch {
            return false;
        }
    }, {message: "Enter a valid link"})
    .refine((s) => {
        const u = new URL(s);
        return !isDailyWire(u) || u.pathname.startsWith("/show/");
    }, {message: "URL must include /show/ in the path"})
    .refine((s) => {
        const u = new URL(s);
        return !isDailyWire(u) || !!u.pathname.slice("/show/".length).split("/")[0];
    }, {message: "URL must include a show name after /show/ (e.g., the-ben-shapiro-show)"});

/* ------------------------------------------------------------------ */
/* FORM schemas (only user-editable fields)                          */
/* ------------------------------------------------------------------ */
const CollectionBaseFormSchema = z.object({
    url: collectionUrl,
    membershipLevel: z.enum(DwMembershipLevelReg.Enum).default(DwMembershipLevelReg.Enum.HIGHEST_ALLOWED),
    type: z.union([z.enum(CollectionTypeReg.values), z.literal('')]).default('').pipe(z.enum(CollectionTypeReg.values)),
    episodeIdentifier: z.union([z.enum(EpisodeIdentifierReg.values), z.literal('')]).default('').pipe(z.enum(EpisodeIdentifierReg.values)),
});

export const CollectionCreateFormSchema = CollectionBaseFormSchema
export type CollectionCreateFormIn = z.input<typeof CollectionCreateFormSchema>;
export type CollectionCreateFormOut = z.output<typeof CollectionCreateFormSchema>;


export const CollectionUpdateFormSchema = CollectionBaseFormSchema
export type CollectionUpdateFormIn = z.input<typeof CollectionUpdateFormSchema>;
export type CollectionUpdateFormOut = z.output<typeof CollectionUpdateFormSchema>;


/* ------------------------------------------------------------------ */
/* PAYLOAD schema (what we POST to the backend)                    */
/* ------------------------------------------------------------------ */
const CollectionBasePayloadSchema = CollectionBaseFormSchema.extend({
    sourceKey: z.string().min(1, "sourceKey missing"),
    dwId: z.string().min(1, "dwId missing").default(''),
    slug: z.string().min(1, "slug missing").default(''),
    title: z.string().min(1, "title missing").default(''),
    description: z.string().nullable(),
    backgroundImagePath: z.string().nullable(),
    logoImagePath: z.string().nullable(),
    sharingUrl: z.string(),

    authorName: z.string().min(1, "authorName missing").default(''),
    authorSlug: z.string().min(1, "authorSlug missing").default(''),
    authorHeadshotPath: z.string().nullable(),

    thumbnailLandscapePath: z.string().nullable(),
    thumbnailPortraitPath: z.string().nullable(),
    thumbnailSquarePath: z.string().nullable(),
})


export const CollectionCreatePayloadSchema = CollectionBasePayloadSchema
export type CollectionCreatePayloadIn = z.input<typeof CollectionCreatePayloadSchema>;
export type CollectionCreatePayloadOut = z.output<typeof CollectionCreatePayloadSchema>;


export const CollectionUpdatePayloadSchema = CollectionBasePayloadSchema
export type CollectionUpdatePayloadIn = z.input<typeof CollectionUpdatePayloadSchema>;
export type CollectionUpdatePayloadOut = z.output<typeof CollectionUpdatePayloadSchema>;


/* ------------------------------------------------------------------ */
/* READ schema (lenient response)                                   */
/* ------------------------------------------------------------------ */
export const CollectionReadSchema = z.looseObject({
    id: z.int(),
    uuid: z.string(),
    slug: z.string(),
    ...SourcedFields,
    membershipLevel: z.union([z.enum(DwMembershipLevelReg.values), z.string()]).nullable(),
    type: z.union([z.enum(CollectionTypeReg.values), z.string()]),
    episodeIdentifier: z.union([z.enum(EpisodeIdentifierReg.values), z.string()]),
    episodeOrder: z.enum(EpisodeOrderReg.values),
    authorSlug: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    sharingUrl: z.string(),
    /** The website it is on; null for an older collection until VODLoft has found it. */
    site: SiteReadSchema.nullable().optional(),
    backgroundImagePath: z.string().nullable().optional(),
    logoImagePath: z.string().nullable().optional(),

    authorName: z.string(),
    authorHeadshotPath: z.string().nullable().optional(),

    thumbnailLandscapePath: z.string().nullable().optional(),
    thumbnailPortraitPath: z.string().nullable().optional(),
    thumbnailSquarePath: z.string().nullable().optional(),
    /** Your own yt-dlp options for this Collection, added after its Local Media Profile's. */
    ytdlpOptions: z.string().default(''),
    cookiesMode: z.enum(['automatic', 'never', 'always']).default('automatic'),
    cookiesNeededUntil: ApiDateTimeSchema.nullable().optional(),
    checkFrequency: z.enum(['default', 'less_often', 'own']).default('default'),
    checkCron: z.string().nullable().optional(),
    customMetadata: z.record(z.string(), z.string()).default({}),

    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
    /** Who added it, with user accounts on. */
    addedBy: z.string().nullable().optional(),
})
export type CollectionRead = z.infer<typeof CollectionReadSchema>;


export const CollectionReadViewSchema = CollectionReadSchema.extend({
    years: z.string(),
    episodeCount: z.int(),
});
export type CollectionReadView = z.infer<typeof CollectionReadViewSchema>;
