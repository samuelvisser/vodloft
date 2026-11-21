import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {filterComplete, filterSentence, plainText} from '../src/components/DownloadProfile/whichEpisodesText'
import {EpisodeFilterSchema, newEpisodeFilter} from '../src/types/schemas/download_profile'

const SEASON = {singular: 'season', plural: 'seasons'}

test('an unplayable formats filter needs nothing more and reads as a sentence', () => {
    const only = newEpisodeFilter('unplayable')
    assert.equal(filterComplete(only), true)
    assert.equal(EpisodeFilterSchema.safeParse(only).success, true)
    assert.equal(plainText(filterSentence(only, undefined, undefined, false, new Date(), SEASON)), 'Only download if the formats are unplayable, such as with DRM')
    assert.equal(plainText(filterSentence({...only, action: 'skip'}, undefined, undefined, false, new Date(), SEASON)), 'Skip if the formats are unplayable, such as with DRM')
})
