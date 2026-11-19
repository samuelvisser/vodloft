import assert from 'node:assert/strict'
import test from 'node:test'

import {addLocalMediaProfilePath, safeReturnPath} from '../src/types/local_media_profile'

test('a new profile fits what it is added for', () => {
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'bandcamp', audio: true}), '/add-local-media-profile?type=collection&for=music_tracks&site=bandcamp')
    // A Music collection on YouTube has music videos.
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'youtube'}), '/add-local-media-profile?type=collection&for=music_videos&site=youtube')
    assert.equal(addLocalMediaProfilePath({collectionType: 'podcast'}), '/add-local-media-profile?type=collection&for=podcast')
    assert.equal(addLocalMediaProfilePath({collectionType: 'series', siteKey: 'youtube', format: 'format_1080p'}), '/add-local-media-profile?type=collection&for=series&site=youtube&format=format_1080p')
    assert.equal(
        addLocalMediaProfilePath({collectionType: 'podcast', returnTo: '/add-download-profile?collection=show'}),
        '/add-local-media-profile?type=collection&for=podcast&returnTo=%2Fadd-download-profile%3Fcollection%3Dshow',
    )
    assert.equal(safeReturnPath('/add-download-profile?collection=show'), '/add-download-profile?collection=show')
    assert.equal(safeReturnPath('//example.com'), undefined)
    assert.equal(safeReturnPath('https://example.com'), undefined)
    assert.equal(addLocalMediaProfilePath({collectionType: null}), '/add-local-media-profile?type=collection')
    assert.equal(addLocalMediaProfilePath({video: 'movies', siteKey: 'dailywire'}), '/add-local-media-profile?type=video&for=movies&site=dailywire')
    assert.equal(addLocalMediaProfilePath({siteKey: 'dailywire'}), '/add-local-media-profile?type=video&site=dailywire')
    // The form names what the link came from, when it says.
    assert.equal(addLocalMediaProfilePath({collectionType: 'series', from: 'Marques Brownlee'}), '/add-local-media-profile?type=collection&for=series&from=Marques+Brownlee')
})
