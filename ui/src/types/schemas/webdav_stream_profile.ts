import {z} from 'zod'
import {StreamProfileFieldsReadSchema, StreamProfileFieldsSchema} from './stream_profile_fields'
import {WebdavMetadataFilesReg, WebdavSeasonFoldersReg} from '../stream_profile'

// ---------- Strict request (create/update) ----------
const WebdavStreamProfileBaseSchema = StreamProfileFieldsSchema.extend({
    // Empty uses the profile's title.
    folderName: z.string().trim().nullable().default(null),
    seasonFolders: z.enum(WebdavSeasonFoldersReg.values).default('season'),
    metadataFiles: z.enum(WebdavMetadataFilesReg.values).default('nfo_and_artwork'),
    // A share lists whole files, so it never has live episodes.
    streamLiveEpisodes: z.literal(false).default(false),
})

export const WebdavStreamProfileCreateSchema = WebdavStreamProfileBaseSchema.extend({
    collectionId: z.int(),
})
export type WebdavStreamProfileCreateIn = z.input<typeof WebdavStreamProfileCreateSchema>
export type WebdavStreamProfileCreateOut = z.output<typeof WebdavStreamProfileCreateSchema>

export const WebdavStreamProfileUpdateSchema = WebdavStreamProfileBaseSchema
export type WebdavStreamProfileUpdateIn = z.input<typeof WebdavStreamProfileUpdateSchema>
export type WebdavStreamProfileUpdateOut = z.output<typeof WebdavStreamProfileUpdateSchema>

export const WebdavStreamProfileReadSchema = StreamProfileFieldsReadSchema.extend({
    type: z.literal('webdav'),
    folderName: z.string().nullable(),
    seasonFolders: z.enum(WebdavSeasonFoldersReg.values),
    metadataFiles: z.enum(WebdavMetadataFilesReg.values),
    sharePath: z.string(),
})
export type WebdavStreamProfileRead = z.infer<typeof WebdavStreamProfileReadSchema>
