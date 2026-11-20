import assert from 'node:assert/strict'
import test from 'node:test'

import {collectionWords, setCollectionContracts, wordsFor} from '../src/lib/collectionWords'
import contracts from './fixtures/collectionContracts.json'

// The words the backend serves (tests/unit/test_collection_contracts.py keeps this copy the same).
setCollectionContracts(contracts)

test('a podcast or series has seasons and episodes', () => {
    for (const type of ['podcast', 'series', null]) {
        const words = collectionWords(type)
        assert.equal(words.season.singular, 'season')
        assert.equal(words.episode.plural, 'episodes')
        assert.equal(words.episode.a, 'an episode')
    }
})

test('a Music collection has albums, and tracks or music videos', () => {
    assert.equal(collectionWords('music').season.a, 'an album')
    assert.equal(collectionWords('music').episode.Singular, 'Music video')
    assert.equal(collectionWords('music', 'audio').episode.plural, 'tracks')
    assert.equal(collectionWords('music', 'audio').count(1), '1 track')
    assert.equal(collectionWords('music', 'audio').count(1200), '1,200 tracks')
})

test('a Music collection on a Site with sound only holds tracks', () => {
    assert.equal(wordsFor({type: 'music', site: {audioOnly: true}}).episode.singular, 'track')
    assert.equal(wordsFor({type: 'music', site: {audioOnly: false}}).episode.singular, 'music video')
    // Its files are tracks wherever it is, as Music Local Media Profiles keep sound.
    assert.equal(wordsFor({type: 'music', site: {audioOnly: false}}, 'audio').episode.singular, 'track')
    assert.equal(wordsFor({type: 'series', site: {audioOnly: true}}).episode.singular, 'episode')
})
