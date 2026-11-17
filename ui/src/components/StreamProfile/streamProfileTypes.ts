import {IptvStreamProfileCreateSchema, IptvStreamProfileUpdateSchema} from '../../types/schemas/iptv_stream_profile'
import {RssStreamProfileCreateSchema, RssStreamProfileUpdateSchema} from '../../types/schemas/rss_stream_profile'
import {WebdavStreamProfileCreateSchema, WebdavStreamProfileUpdateSchema} from '../../types/schemas/webdav_stream_profile'

/** What the pages need to know of each stream profile type: its name, API and form schemas. */
export const STREAM_PROFILE_TYPES = {
    rss: {
        label: 'RSS',
        endpoint: 'rss-stream-profiles',
        createSchema: RssStreamProfileCreateSchema,
        updateSchema: RssStreamProfileUpdateSchema,
    },
    iptv: {
        label: 'IPTV',
        endpoint: 'iptv-stream-profiles',
        createSchema: IptvStreamProfileCreateSchema,
        updateSchema: IptvStreamProfileUpdateSchema,
    },
    webdav: {
        label: 'WebDAV',
        endpoint: 'webdav-stream-profiles',
        createSchema: WebdavStreamProfileCreateSchema,
        updateSchema: WebdavStreamProfileUpdateSchema,
    },
} as const

export type StreamProfileType = keyof typeof STREAM_PROFILE_TYPES

export function isStreamProfileType(value: string | undefined): value is StreamProfileType {
    return !!value && value in STREAM_PROFILE_TYPES
}

/** The update request that keeps a profile as it is, for changing one of its settings. */
export function streamProfileUpdate(impl: {type: StreamProfileType, effectiveTitle: string}) {
    return STREAM_PROFILE_TYPES[impl.type].updateSchema.parse({...impl, title: impl.effectiveTitle})
}
