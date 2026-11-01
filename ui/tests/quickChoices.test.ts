import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {fitChoice, fitRules, NO_RULES, type QuickChoice} from '../src/lib/quickDownloads'
import type {QuickDownloadOptions} from '../src/types/schemas/quick_download'

function options(formatChoices: boolean, qualities: (number | null)[]): QuickDownloadOptions {
    return {
        link: {} as QuickDownloadOptions['link'],
        formatChoices,
        qualityChoices: formatChoices || qualities.length > 1,
        containers: formatChoices ? ['mp4', 'mkv'] : ['mp4'],
        videos: qualities.map((quality) => ({quality, sizeBytes: null, codec: 'h264', codecs: []})),
        audio: [{audioFormat: 'm4a'}],
    }
}

const wanted: QuickChoice = {
    kind: 'video', quality: 1080, container: 'mkv', codec: 'vp9', audioFormat: 'mp3', audioBitrate: 192,
    embedMetadata: true, embedArtwork: true,
}

test('a stream with qualities keeps the quality but only MP4 and M4A', () => {
    const fitted = fitChoice(wanted, options(false, [null, 1080, 720]))
    assert.equal(fitted.quality, 1080)
    assert.equal(fitted.container, 'mp4')
    assert.equal(fitted.codec, null)
    assert.equal(fitted.audioFormat, 'm4a')
    assert.equal(fitChoice({...wanted, quality: 1440}, options(false, [null, 1080, 720])).quality, 1080)
})

test('without qualities only Best is left', () => {
    assert.equal(fitChoice(wanted, options(false, [null])).quality, null)
})

test('the quality limit holds for a stream with qualities', () => {
    const rules = {...NO_RULES, maxQuality: 720}
    const fitted = fitRules({...wanted, container: 'mp4', codec: null}, options(false, [null, 1080, 720]), rules)
    assert.equal(fitted.quality, 720)
})
