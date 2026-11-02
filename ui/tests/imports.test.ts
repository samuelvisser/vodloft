import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {filesToOffer, runReportText} from '../src/lib/imports'
import type {ImportRun} from '../src/types/schemas/imports'

function picked(path: string, size = 1): File {
    const file = new File([new Uint8Array(size)], path.split('/').pop()!)
    Object.defineProperty(file, 'webkitRelativePath', {value: path})
    return file
}

test('only the files an importer takes are offered from a picked folder', () => {
    const files = [
        picked('config/db/pinchflat.db'),
        picked('config/db/pinchflat.db-wal'),
        picked('config/extras/yt-dlp-configs/base-config.txt'),
        picked('config/metadata/sources/1/poster.jpg'),
        picked('config/extras/cookies.txt'),
    ]
    const offered = filesToOffer(files, ['db/pinchflat.db', 'db/pinchflat.db-wal', 'extras/yt-dlp-configs/*.txt', 'extras/cookies.txt'])
    assert.deepEqual(offered.map((file) => file.webkitRelativePath), [
        'config/db/pinchflat.db', 'config/db/pinchflat.db-wal', 'config/extras/yt-dlp-configs/base-config.txt', 'config/extras/cookies.txt',
    ])
})

test('a single archive is offered as it is', () => {
    const archive = new File([new Uint8Array(1)], 'config.tar.gz')
    assert.deepEqual(filesToOffer([archive], ['wireloft.db']), [archive])
})

test('the run report lists counts, entries and problems', () => {
    const run: ImportRun = {
        id: 3, status: 'finished', createdAt: '2026-11-02T10:00:00Z', finishedAt: '2026-11-02T10:05:00Z',
        counts: {adopted: 2, not_reachable: 1}, options: {}, version: '1.2.4',
        report: [{kind: 'linked', subject: 'Morning Show', message: 'joined the collection in your library'}],
        steps: [{
            collectionTitle: 'Morning Show', status: 'done', files: 3, counts: {}, downloadProfileOn: false,
            problems: [{path: '/downloads/a.mp4', error: 'not found'}],
        }],
    }
    const text = runReportText('WireLoft', run)
    assert.match(text, /WireLoft import #3/)
    assert.match(text, /not reachable: 1/)
    assert.match(text, /\[linked\] Morning Show: joined/)
    assert.match(text, /\/downloads\/a\.mp4: not found/)
})

test('an upload behind a proxy with a 1 MB limit continues in small chunks and resumes where the server is', async () => {
    const {uploadFiles, SMALL_CHUNK_SIZE} = await import('../src/lib/imports')
    const size = 3 * 1024 * 1024 + 5
    const file = picked('config/wireloft.db', size)
    let stored = 0
    let refusedOnce = false
    const chunkSizes: number[] = []
    const original = globalThis.fetch
    ;(globalThis as any).window ??= {appConfig: {API_URL: '/api'}}
    globalThis.fetch = (async (input: string, init?: RequestInit) => {
        const url = new URL(input, 'http://vodloft.test')
        const ok = (body: unknown) => new Response(JSON.stringify(body), {status: 200})
        if (url.pathname.endsWith('/upload') && init?.method === 'POST') {
            return ok({skipped: [], send: [{source: 'config/wireloft.db', path: 'wireloft.db'}]})
        }
        if (url.pathname.endsWith('/upload/finish')) return ok({skipped: [], send: []})
        const body = init!.body as Blob
        if (body.size > 1024 * 1024) return new Response('Request Entity Too Large', {status: 413})
        const offset = Number(url.searchParams.get('offset'))
        if (offset === SMALL_CHUNK_SIZE && !refusedOnce) {
            // The connection dropped after the server stored this chunk: it says where to go on.
            refusedOnce = true
            stored += body.size
            return new Response(JSON.stringify({detail: {message: 'offset', received: stored}}), {status: 409})
        }
        if (offset !== stored) {
            return new Response(JSON.stringify({detail: {message: 'offset', received: stored}}), {status: 409})
        }
        stored += body.size
        chunkSizes.push(body.size)
        return ok({received: stored})
    }) as typeof fetch
    try {
        await uploadFiles('wireloft', [file], false, () => undefined)
    } finally {
        globalThis.fetch = original
    }
    assert.equal(stored, size)
    assert.ok(chunkSizes.every((chunk) => chunk <= SMALL_CHUNK_SIZE))
})
