import assert from 'node:assert/strict'
import test from 'node:test'

import {setCollectionContracts} from '../src/lib/collectionWords'
import {addLocalMediaProfilePath, safeReturnPath} from '../src/types/local_media_profile'
import contracts from './fixtures/collectionContracts.json'

// What a new profile keeps for each collection type comes from the backend's collection contracts.
setCollectionContracts(contracts)

test('a new profile fits what it is added for', () => {
    // A profile for Music keeps tracks or music videos by what it downloads.
    assert.equal(addLocalMediaProfilePath({collectionType: 'music', siteKey: 'bandcamp'}), '/add-local-media-profile?type=collection&for=music&site=bandcamp')
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
