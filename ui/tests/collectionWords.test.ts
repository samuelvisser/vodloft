import assert from 'node:assert/strict'
import test from 'node:test'

import {collectionWords, wordsFor} from '../src/lib/collectionWords'

test('a podcast or series has seasons and episodes', () => {
    for (const type of ['podcast', 'series', null]) {
        const words = collectionWords(type)
        assert.equal(words.season.one, 'season')
        assert.equal(words.episode.many, 'episodes')
        assert.equal(words.episode.a, 'an episode')
    }
})

test('a Music collection has albums, and tracks or music videos', () => {
    assert.equal(collectionWords('music').season.a, 'an album')
    assert.equal(collectionWords('music').episode.One, 'Music video')
    assert.equal(collectionWords('music', 'audio').episode.many, 'tracks')
    assert.equal(collectionWords('music', 'audio').count(1), '1 track')
    assert.equal(collectionWords('music', 'audio').count(1200), '1,200 tracks')
})

test('a Music collection on a Site with sound only holds tracks', () => {
    assert.equal(wordsFor({type: 'music', site: {audioOnly: true}}).episode.one, 'track')
    assert.equal(wordsFor({type: 'music', site: {audioOnly: false}}).episode.one, 'music video')
    // Its files are tracks wherever it is, as Music Local Media Profiles keep sound.
    assert.equal(wordsFor({type: 'music', site: {audioOnly: false}}, 'audio').episode.one, 'track')
    assert.equal(wordsFor({type: 'series', site: {audioOnly: true}}).episode.one, 'episode')
})
