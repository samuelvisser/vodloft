import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {sourceControls} from '../src/lib/sourceControls'

test('an episode its Source looks up again in batches offers Refresh metadata', () => {
    const youtube = {sourceFeatures: ['collections', 'episode_lists', 'metadata_refresh']}
    assert.equal(sourceControls(youtube).metadataRefresh, true)
})

test('an episode The Daily Wire looks up one by one offers Refresh metadata', () => {
    assert.equal(sourceControls({sourceFeatures: ['collections', 'episode_lookups']}).metadataRefresh, true)
})

test('an episode its Source never looks up again has no Refresh metadata', () => {
    assert.equal(sourceControls({sourceFeatures: ['collections', 'episode_lists']}).metadataRefresh, false)
})
