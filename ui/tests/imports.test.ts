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
