import assert from 'node:assert/strict'
import test from 'node:test'

import {filterSentence, plainText} from '../src/components/DownloadProfile/whichEpisodesText'
import {defaultEpisodeFilters} from '../src/types/schemas/download_profile'

const albums = {singular: 'album', plural: 'albums'}
const slugs = ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8', 'a9']
const label = (slug: string) => slug.toUpperCase()
const seasonsLine = (seasonSlugs: string[], includeUpcoming: boolean) => plainText(filterSentence(
    {action: 'only', field: 'seasons', seasonSlugs, includeUpcoming}, undefined, label, false, undefined, albums, slugs,
))

test('a seasons line that picks every season says so instead of naming them', () => {
    assert.equal(seasonsLine([...slugs].reverse(), true), 'Only download if the album is any of all albums or upcoming ones')
    assert.equal(seasonsLine(slugs, false), 'Only download if the album is any of all albums')
})

test('a seasons line names at most three seasons, newest first, and counts the others', () => {
    assert.equal(
        seasonsLine(slugs.slice(0, 8), true),
        'Only download if the album is A8, A7, A6, 5 more albums or upcoming albums',
    )
    assert.equal(seasonsLine(['a1', 'a2', 'a3', 'a4'], false), 'Only download if the album is A4, A3, A2 or 1 more album')
    assert.equal(seasonsLine(['a2'], true), 'Only download if the album is A2 or upcoming albums')
})

test('a new profile picks the newest season or every season, as the Site says, and upcoming ones', () => {
    const seasons = [{slug: 'old'}, {slug: 'new'}]
    const seasonsFilter = (profileSeasons: 'newest' | 'all') => (
        defaultEpisodeFilters('seasonal', [], seasons, profileSeasons).find((filter) => filter.field === 'seasons')
    )
    assert.deepEqual(seasonsFilter('newest')?.seasonSlugs, ['new'])
    assert.deepEqual(seasonsFilter('all')?.seasonSlugs, ['old', 'new'])
    assert.equal(seasonsFilter('all')?.includeUpcoming, true)
})
