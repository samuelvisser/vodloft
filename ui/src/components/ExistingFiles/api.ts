import {useQuery} from '@tanstack/react-query'
import {
    ExistingFilesOpenScan,
    ExistingFilesOpenScanSchema,
    ExistingFilesProfileReview,
    ExistingFilesProfileReviewSchema,
    ExistingFilesScan,
    ExistingFilesScanSchema,
    ExistingFilesScanSummary,
    ExistingFilesScanSummarySchema,
    FolderList,
    FolderListSchema,
} from '../../types/schemas/existing_files'

const api = () => (window as any).appConfig.API_URL as string

export class ExistingFilesRequestError extends Error {}

async function request<T>(path: string, schema: {parse(value: unknown): T}, init?: RequestInit): Promise<T> {
    const response = await fetch(`${api()}${path}`, {
        credentials: 'include',
        ...init,
        headers: init?.body ? {'Content-Type': 'application/json', ...(init.headers ?? {})} : init?.headers,
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
        const detail = data?.detail
        const message = typeof detail === 'string' ? detail
            : Array.isArray(detail) && typeof detail[0]?.msg === 'string' ? detail[0].msg
            : data?.message ?? `HTTP ${response.status}`
        throw new ExistingFilesRequestError(message)
    }
    return schema.parse(data)
}

const collectionPath = (slug: string) => `/collections/${encodeURIComponent(slug)}/existing-files`

export function useExistingFilesScan(collectionSlug: string | undefined, localMediaProfileId: number | undefined) {
    return useQuery<ExistingFilesScan, Error>({
        queryKey: ['existingFiles', collectionSlug, localMediaProfileId],
        enabled: Boolean(collectionSlug && localMediaProfileId),
        queryFn: () => readScan(collectionSlug!, localMediaProfileId!),
        // While a scan waits for the episodes or reads the folder, check back every few seconds.
        refetchInterval: (query) => {
            const status = query.state.data?.status
            return status === 'waiting' || status === 'scanning' ? 2500 : false
        },
    })
}

export function useExistingFilesScans(collectionSlug: string | undefined, enabled: boolean) {
    return useQuery<ExistingFilesScanSummary[], Error>({
        queryKey: ['existingFilesScans', collectionSlug],
        enabled: Boolean(collectionSlug) && enabled,
        queryFn: () => request(`${collectionPath(collectionSlug!)}/scans`, ExistingFilesScanSummarySchema.array()),
        refetchInterval: (query) => (query.state.data ?? []).some(
            (scan) => scan.status === 'waiting' || scan.status === 'scanning',
        ) ? 4000 : false,
    })
}

/** The scans of every Collection that still need a person, for the page that reviews them all. */
export function useOpenExistingFilesScans() {
    return useQuery<ExistingFilesOpenScan[], Error>({
        queryKey: ['existingFilesOpen'],
        queryFn: () => request('/collections/existing-files/open', ExistingFilesOpenScanSchema.array()),
        refetchInterval: (query) => (query.state.data ?? []).some(
            (scan) => scan.status === 'waiting' || scan.status === 'scanning',
        ) ? 4000 : false,
    })
}

/** Every open scan of one Local Media Profile, as one review of its whole folder. */
export function useProfileExistingFiles(localMediaProfileId: number | undefined) {
    return useQuery<ExistingFilesProfileReview, Error>({
        queryKey: ['existingFilesProfile', localMediaProfileId],
        enabled: Boolean(localMediaProfileId),
        queryFn: () => request(`/collections/existing-files/profiles/${localMediaProfileId}`, ExistingFilesProfileReviewSchema),
        refetchInterval: (query) => (query.state.data?.collections ?? []).some(
            (scan) => scan.status === 'waiting' || scan.status === 'scanning',
        ) ? 4000 : false,
    })
}

export function readScan(collectionSlug: string, localMediaProfileId: number) {
    return request(`${collectionPath(collectionSlug)}?local_media_profile_id=${localMediaProfileId}`, ExistingFilesScanSchema)
}

export function startScan(collectionSlug: string, body: {localMediaProfileId: number, folder: string, template?: string | null}) {
    return request(`${collectionPath(collectionSlug)}/scan`, ExistingFilesScanSchema, {
        method: 'POST', body: JSON.stringify(body),
    })
}

const AdoptResultSchema = {
    parse: (value: unknown) => value as {adopted: number, errors: {path: string, error: string}[]},
}

export async function adoptFiles(
    collectionSlug: string,
    localMediaProfileId: number,
    matches: {path: string, episodeId: number}[],
    onProgress?: (done: number) => void,
) {
    // The server takes up to 500 files a request; each one is read to record its identity.
    let adopted = 0
    const errors: {path: string, error: string}[] = []
    for (let start = 0; start < matches.length; start += 200) {
        const result = await request(`${collectionPath(collectionSlug)}/adopt`, AdoptResultSchema, {
            method: 'POST',
            body: JSON.stringify({localMediaProfileId, matches: matches.slice(start, start + 200)}),
        })
        adopted += result.adopted
        errors.push(...result.errors)
        onProgress?.(Math.min(matches.length, start + 200))
    }
    return {adopted, errors}
}

export function finishScan(collectionSlug: string, localMediaProfileId: number) {
    return request(`${collectionPath(collectionSlug)}/finish`, {
        parse: (value: unknown) => value as {downloadProfilesEnabled: number},
    }, {method: 'POST', body: JSON.stringify({localMediaProfileId})})
}

export function listFolders(folder: string): Promise<FolderList> {
    return request(`/collections/existing-files/folders?folder=${encodeURIComponent(folder)}`, FolderListSchema)
}
