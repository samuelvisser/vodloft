import {z} from 'zod'

export const ImportSupportSchema = z.enum(['exact', 'close', 'unsupported'])
export type ImportSupport = z.infer<typeof ImportSupportSchema>

export const ImportWarningSchema = z.looseObject({
    subject: z.string(),
    message: z.string(),
    support: ImportSupportSchema,
})
export type ImportWarning = z.infer<typeof ImportWarningSchema>

export const ImportUploadedFileSchema = z.looseObject({
    path: z.string(),
    size: z.number(),
    secret: z.boolean().default(false),
    received: z.number().nullish(),
})

export const ImportUploadStatusSchema = z.looseObject({
    upload: z.looseObject({uploadedAt: z.string(), files: z.array(ImportUploadedFileSchema)}).nullish(),
    incoming: z.looseObject({startedAt: z.string(), files: z.array(ImportUploadedFileSchema)}).nullish(),
    skipped: z.array(z.string()).default([]),
    send: z.array(z.looseObject({source: z.string(), path: z.string()})).default([]),
})
export type ImportUploadStatus = z.infer<typeof ImportUploadStatusSchema>

export const ImportRunStatusSchema = z.enum(['running', 'waiting', 'finished', 'failed'])

export const ImportRunSummarySchema = z.looseObject({
    id: z.int(),
    status: ImportRunStatusSchema,
    createdAt: z.string(),
    finishedAt: z.string().nullish(),
    uploadedAt: z.string().nullish(),
    counts: z.record(z.string(), z.number()),
    error: z.string().nullish(),
})
export type ImportRunSummary = z.infer<typeof ImportRunSummarySchema>

export const ImporterSchema = z.looseObject({
    key: z.string(),
    name: z.string(),
    files: z.array(z.string()),
    secretFiles: z.array(z.string()),
    upload: ImportUploadStatusSchema,
    lastRun: ImportRunSummarySchema.nullish(),
})
export type Importer = z.infer<typeof ImporterSchema>

export const ImportCollectionSchema = z.looseObject({
    externalId: z.string(),
    title: z.string(),
    url: z.string(),
    profileExternalId: z.string().nullish(),
    profileName: z.string().nullish(),
    becomes: z.enum(['new', 'linked', 'in_library']),
    collectionSlug: z.string().nullish(),
    files: z.int(),
    filesOnDisk: z.int(),
    filesAdopted: z.int(),
    suppressed: z.int(),
    missing: z.int(),
    downloadProfileOn: z.boolean(),
    customMetadata: z.record(z.string(), z.string()).default({}),
    warnings: z.array(ImportWarningSchema),
})
export type ImportCollection = z.infer<typeof ImportCollectionSchema>

export const ImportProfileSchema = z.looseObject({
    externalId: z.string(),
    name: z.string(),
    becomes: z.enum(['new', 'linked', 'reused']),
    localMediaProfileName: z.string().nullish(),
    originalTemplate: z.string().nullish(),
    outputTemplate: z.string().nullish(),
    support: ImportSupportSchema,
    report: z.array(z.string()),
    settings: z.record(z.string(), z.unknown()),
    customIndexes: z.array(z.looseObject({key: z.string(), name: z.string(), keepNumbers: z.boolean()})),
    warnings: z.array(ImportWarningSchema),
    pathProof: z.looseObject({
        identical: z.int(),
        total: z.int(),
        differences: z.array(z.looseObject({path: z.string(), rendered: z.string()})),
        error: z.string().nullish(),
    }),
    baseName: z.string().nullish(),
    mergedFrom: z.array(z.string()).default([]),
    fields: z.array(z.string()).default([]),
    keptSeparate: z.string().nullish(),
    changes: z.looseObject({
        updated: z.array(z.string()),
        kept: z.array(z.string()),
        newlyMapped: z.array(z.string()),
    }).nullish(),
})
export type ImportProfile = z.infer<typeof ImportProfileSchema>

export const ImportSettingSchema = z.looseObject({
    key: z.string(),
    value: z.unknown().optional(),
    support: ImportSupportSchema,
    note: z.string().nullish(),
    secret: z.boolean(),
    selected: z.boolean(),
})
export type ImportSetting = z.infer<typeof ImportSettingSchema>

export const ImportPreviewSchema = z.looseObject({
    importer: z.string(),
    version: z.string().nullish(),
    uploadedAt: z.string().nullish(),
    pathMap: z.looseObject({source: z.string(), target: z.string(), sampled: z.int(), found: z.int()}),
    collections: z.array(ImportCollectionSchema),
    profiles: z.array(ImportProfileSchema),
    settings: z.array(ImportSettingSchema),
    warnings: z.array(ImportWarningSchema),
    records: z.looseObject({
        kinds: z.record(z.string(), z.record(z.string(), z.number())),
        collections: z.array(z.looseObject({
            externalId: z.string(),
            title: z.string().nullish(),
            url: z.string().nullish(),
            becomes: z.string(),
        })),
    }).nullish(),
    lastRun: ImportRunSummarySchema.nullish(),
    mergeProfiles: z.boolean().default(false),
    counts: z.looseObject({collections: z.int(), files: z.int()}),
})
export type ImportPreview = z.infer<typeof ImportPreviewSchema>

export const ImportRunSchema = ImportRunSummarySchema.extend({
    options: z.record(z.string(), z.unknown()),
    version: z.string().nullish(),
    report: z.array(z.looseObject({
        kind: z.string(),
        subject: z.string(),
        message: z.string(),
        support: z.string().nullish(),
    })),
    steps: z.array(z.looseObject({
        collectionSlug: z.string().nullish(),
        collectionTitle: z.string().nullish(),
        status: z.enum(['waiting', 'done', 'failed']),
        files: z.int(),
        counts: z.record(z.string(), z.number()),
        problems: z.array(z.looseObject({path: z.string().nullish(), error: z.string()})),
        downloadProfileOn: z.boolean(),
        matching: z.looseObject({
            status: z.enum(['waiting', 'scanning', 'ready', 'failed', 'finished']),
            found: z.int(),
        }).nullish(),
    })),
})
export type ImportRun = z.infer<typeof ImportRunSchema>

export type ImportOptions = {
    pathMap?: [string, string] | null
    collections?: string[] | null
    settings?: string[] | null
    enableDownloadProfiles: boolean
    matchExistingFiles: boolean
    renameExistingFiles: boolean
    /** Leave out to do what the last import did. */
    mergeProfiles?: boolean | null
    templates: Record<string, string>
}
