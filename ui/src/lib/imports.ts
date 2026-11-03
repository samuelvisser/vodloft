import {useQuery} from '@tanstack/react-query'

import {errorMessage} from './users'
import {
    ImportPreviewSchema,
    ImportRunSchema,
    ImportRunSummarySchema,
    ImportUploadStatusSchema,
    ImporterSchema,
    type ImportOptions,
    type ImportPreview,
    type ImportRun,
    type ImportRunSummary,
    type ImportUploadStatus,
    type Importer,
} from '../types/schemas/imports'

/** The server takes chunks of up to 8 MiB. */
export const CHUNK_SIZE = 8 * 1024 * 1024
/** A reverse proxy that refuses large bodies (nginx allows 1 MB by default) gets chunks of this size instead. */
export const SMALL_CHUNK_SIZE = 512 * 1024
const ARCHIVE_SUFFIXES = ['.zip', '.tar.gz', '.tgz', '.tar']

function base(): string {
    return ((window as any).appConfig?.API_URL || '/api').replace(/\/+$/, '')
}

async function request<T>(path: string, parse: (data: unknown) => T, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${base()}/imports${path}`, {
        credentials: 'include',
        ...init,
        headers: init.body && typeof init.body === 'string' ? {'Content-Type': 'application/json', ...init.headers} : init.headers,
    })
    if (!response.ok) throw new Error(await errorMessage(response))
    return parse(response.status === 204 ? null : await response.json())
}

const json = (body: unknown): RequestInit => ({method: 'POST', body: JSON.stringify(body)})

export const IMPORTERS_KEY = ['importers'] as const

export function useImporters() {
    return useQuery<Importer[]>({
        queryKey: IMPORTERS_KEY,
        queryFn: () => request('', (data) => ImporterSchema.array().parse(data)),
    })
}

export function useImportRuns(key: string) {
    return useQuery<ImportRunSummary[]>({
        queryKey: ['importRuns', key],
        queryFn: () => request(`/${key}/runs`, (data) => ImportRunSummarySchema.array().parse(data)),
    })
}

export function readRun(key: string, id: number): Promise<ImportRun> {
    return request(`/${key}/runs/${id}`, (data) => ImportRunSchema.parse(data))
}

export function enableRunDownloadProfiles(key: string, id: number): Promise<ImportRun> {
    return request(`/${key}/runs/${id}/enable-download-profiles`, (data) => ImportRunSchema.parse(data), {method: 'POST'})
}

export function previewImport(key: string, options: ImportOptions): Promise<ImportPreview> {
    return request(`/${key}/preview`, (data) => ImportPreviewSchema.parse(data), json(options))
}

export function startRun(key: string, options: ImportOptions): Promise<ImportRunSummary> {
    return request(`/${key}/runs`, (data) => ImportRunSummarySchema.parse(data), json(options))
}

export function uploadFromFolder(key: string, folder: string, includeSecrets: boolean): Promise<ImportUploadStatus> {
    return request(`/${key}/upload/from-folder`, (data) => ImportUploadStatusSchema.parse(data), json({folder, includeSecrets}))
}

export function removeUpload(key: string): Promise<null> {
    return request(`/${key}/upload`, () => null, {method: 'DELETE'})
}

function isArchive(name: string): boolean {
    const lowered = name.toLowerCase()
    return ARCHIVE_SUFFIXES.some((suffix) => lowered.endsWith(suffix))
}

function globToRegExp(glob: string): RegExp {
    const escaped = glob.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]')
    return new RegExp(`(^|/)${escaped}$`)
}

/** The picked files the importer can use: its file patterns, or one archive. The server checks again. */
export function filesToOffer(files: File[], patterns: string[]): File[] {
    const archive = files.length === 1 && isArchive(files[0].name) ? files[0] : null
    if (archive) return [archive]
    const rules = patterns.map(globToRegExp)
    return files.filter((file) => rules.some((rule) => rule.test(relativePath(file))))
}

export function relativePath(file: File): string {
    return (file as File & {webkitRelativePath?: string}).webkitRelativePath || file.name
}

export type UploadProgress = {sent: number, total: number, file: string}

/** Send the picked files in chunks; a chunk the server already has is skipped, so a retry resumes. */
export async function uploadFiles(
    key: string,
    files: File[],
    includeSecrets: boolean,
    onProgress: (progress: UploadProgress) => void,
    signal?: AbortSignal,
): Promise<ImportUploadStatus> {
    const begun = await request(
        `/${key}/upload`,
        (data) => ImportUploadStatusSchema.parse(data),
        json({files: files.map((file) => ({path: relativePath(file), size: file.size})), includeSecrets}),
    )
    const bySource = new Map(files.map((file) => [relativePath(file), file]))
    const sending = begun.send.map((item) => ({...item, file: bySource.get(item.source)!})).filter((item) => item.file)
    const total = sending.reduce((sum, item) => sum + item.file.size, 0)
    let done = 0
    let chunkSize = CHUNK_SIZE
    for (const item of sending) {
        let offset = 0
        while (offset < item.file.size || (offset === 0 && item.file.size === 0)) {
            signal?.throwIfAborted()
            const chunk = item.file.slice(offset, offset + chunkSize)
            const response = await fetch(
                `${base()}/imports/${key}/upload/chunk?path=${encodeURIComponent(item.path)}&offset=${offset}`,
                {method: 'PUT', credentials: 'include', body: chunk, signal},
            )
            if (response.status === 413 && chunkSize > SMALL_CHUNK_SIZE) {
                // Too large for a proxy in between: send the rest in small chunks.
                chunkSize = SMALL_CHUNK_SIZE
                continue
            }
            if (response.status === 409) {
                const payload = await response.json().catch(() => null)
                const received = payload?.detail?.received
                if (typeof received !== 'number') throw new Error('The upload could not continue; start it again')
                offset = received
            } else if (!response.ok) {
                throw new Error(await errorMessage(response))
            } else {
                offset = (await response.json()).received
            }
            onProgress({sent: done + offset, total, file: item.source})
            if (item.file.size === 0) break
        }
        done += item.file.size
    }
    return request(`/${key}/upload/finish`, (data) => ImportUploadStatusSchema.parse(data), {method: 'POST'})
}

/** The report of a run as plain text, to download. */
export function runReportText(name: string, run: ImportRun): string {
    const lines = [
        `${name} import #${run.id}`,
        `Started ${run.createdAt}${run.finishedAt ? `, finished ${run.finishedAt}` : ''}: ${run.status}`,
        run.version ? `From ${run.version}` : '',
        '',
        'Counts',
        ...Object.entries(run.counts).map(([key, value]) => `  ${key.replace(/_/g, ' ')}: ${value}`),
        '',
        'Report',
        ...run.report.map((entry) => `  [${entry.kind}] ${entry.subject}: ${entry.message}`),
    ]
    for (const step of run.steps) {
        if (!step.problems.length) continue
        lines.push('', `Problems in ${step.collectionTitle ?? step.collectionSlug ?? 'a collection'}`)
        lines.push(...step.problems.map((problem) => `  ${problem.path ? `${problem.path}: ` : ''}${problem.error}`))
    }
    if (run.error) lines.push('', `Error: ${run.error}`)
    return lines.filter((line, index, all) => line !== '' || all[index - 1] !== '').join('\n') + '\n'
}
