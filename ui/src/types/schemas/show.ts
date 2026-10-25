import {z} from "zod";
import {EpisodeIdentifierReg, ShowTypeReg} from "../show";
import {DwMembershipLevelReg} from "../dailywire_user_info";
import {ApiDateTimeSchema} from "./datetime";
import {DEFAULT_SOURCE_KEY, SourcedFields} from "./source";


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

/** A show's link. Daily Wire links must point at a show page; other sites keep their full link. */
const showUrl = z
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
const ShowBaseFormSchema = z.object({
    url: showUrl,
    membershipLevel: z.enum(DwMembershipLevelReg.Enum).default(DwMembershipLevelReg.Enum.WL_ANY),
    type: z.union([z.enum(ShowTypeReg.values), z.literal('')]).default('').pipe(z.enum(ShowTypeReg.values)),
    episodeIdentifier: z.union([z.enum(EpisodeIdentifierReg.values), z.literal('')]).default('').pipe(z.enum(EpisodeIdentifierReg.values)),
});

export const ShowCreateFormSchema = ShowBaseFormSchema
export type ShowCreateFormIn = z.input<typeof ShowCreateFormSchema>;
export type ShowCreateFormOut = z.output<typeof ShowCreateFormSchema>;


export const ShowUpdateFormSchema = ShowBaseFormSchema
export type ShowUpdateFormIn = z.input<typeof ShowUpdateFormSchema>;
export type ShowUpdateFormOut = z.output<typeof ShowUpdateFormSchema>;


/* ------------------------------------------------------------------ */
/* PAYLOAD schema (what we POST to the backend)                    */
/* ------------------------------------------------------------------ */
const ShowBasePayloadSchema = ShowBaseFormSchema.extend({
    sourceKey: z.string().default(DEFAULT_SOURCE_KEY),
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


export const ShowCreatePayloadSchema = ShowBasePayloadSchema
export type ShowCreatePayloadIn = z.input<typeof ShowCreatePayloadSchema>;
export type ShowCreatePayloadOut = z.output<typeof ShowCreatePayloadSchema>;


export const ShowUpdatePayloadSchema = ShowBasePayloadSchema
export type ShowUpdatePayloadIn = z.input<typeof ShowUpdatePayloadSchema>;
export type ShowUpdatePayloadOut = z.output<typeof ShowUpdatePayloadSchema>;


/* ------------------------------------------------------------------ */
/* READ schema (lenient response)                                   */
/* ------------------------------------------------------------------ */
export const ShowReadSchema = z.looseObject({
    id: z.int(),
    uuid: z.string(),
    slug: z.string(),
    ...SourcedFields,
    membershipLevel: z.union([z.enum(DwMembershipLevelReg.values), z.string()]).optional(),
    type: z.union([z.enum(ShowTypeReg.values), z.string()]),
    episodeIdentifier: z.union([z.enum(EpisodeIdentifierReg.values), z.string()]),
    authorSlug: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    sharingUrl: z.string(),
    backgroundImagePath: z.string().nullable().optional(),
    logoImagePath: z.string().nullable().optional(),

    authorName: z.string(),
    authorHeadshotPath: z.string().nullable().optional(),

    thumbnailLandscapePath: z.string().nullable().optional(),
    thumbnailPortraitPath: z.string().nullable().optional(),
    thumbnailSquarePath: z.string().nullable().optional(),
    customMetadata: z.record(z.string(), z.string()).default({}),

    createdAt: ApiDateTimeSchema,
    updatedAt: ApiDateTimeSchema,
})
export type ShowRead = z.infer<typeof ShowReadSchema>;


export const ShowReadViewSchema = ShowReadSchema.extend({
    years: z.string(),
    episodeCount: z.int(),
});
export type ShowReadView = z.infer<typeof ShowReadViewSchema>;
