import assert from 'node:assert/strict'
import test from 'node:test'

import {addLocalMediaProfilePath} from '../src/types/local_media_profile'

test('a new profile fits what it is added for', () => {
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'bandcamp', audio: true}), '/add-local-media-profile?type=collection&for=music_tracks&site=bandcamp')
    // A Music collection on YouTube has music videos.
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'youtube'}), '/add-local-media-profile?type=collection&for=music_videos&site=youtube')
    assert.equal(addLocalMediaProfilePath({collectionType: 'podcast'}), '/add-local-media-profile?type=collection&for=podcast')
    assert.equal(addLocalMediaProfilePath({collectionType: 'series', siteKey: 'youtube', format: 'format_1080p'}), '/add-local-media-profile?type=collection&for=series&site=youtube&format=format_1080p')
    assert.equal(addLocalMediaProfilePath({collectionType: null}), '/add-local-media-profile?type=collection')
    assert.equal(addLocalMediaProfilePath({video: 'movies', siteKey: 'dailywire'}), '/add-local-media-profile?type=video&for=movies&site=dailywire')
    assert.equal(addLocalMediaProfilePath({siteKey: 'dailywire'}), '/add-local-media-profile?type=video&site=dailywire')
})
