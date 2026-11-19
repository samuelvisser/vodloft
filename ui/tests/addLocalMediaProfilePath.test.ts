import assert from 'node:assert/strict'
import test from 'node:test'

import {addLocalMediaProfilePath} from '../src/types/local_media_profile'

test('a new profile fits what it is added for', () => {
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'bandcamp', audio: true}), '/add-local-media-profile?type=music&site=bandcamp')
    // A Music collection on YouTube has music videos, which a Collection profile keeps.
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'youtube'}), '/add-local-media-profile?type=collection&for=music&site=youtube')
    assert.equal(addLocalMediaProfilePath({collectionType: 'podcast'}), '/add-local-media-profile?type=collection&for=podcast')
    assert.equal(addLocalMediaProfilePath({collectionType: null}), '/add-local-media-profile?type=collection')
    assert.equal(addLocalMediaProfilePath({siteKey: 'dailywire'}), '/add-local-media-profile?type=video&site=dailywire')
})
