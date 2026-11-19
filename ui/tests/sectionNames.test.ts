import assert from 'node:assert/strict'
import test from 'node:test'

import {growingNames, joinedNames, listNames, sectionName} from '../src/types/creator'

const soundcloud = [
    {key: 'feed', kind: 'feed', one: 'feed', many: 'feeds', a: 'a feed'},
    {key: 'album', kind: 'list', one: 'album', many: 'albums', a: 'an album'},
    {key: 'playlist', kind: 'list', one: 'playlist', many: 'playlists', a: 'a playlist'},
    {key: 'single', kind: 'item', one: 'single', many: 'singles', a: 'a single'},
]

test('several section types are named together', () => {
    assert.deepEqual(listNames(soundcloud), {one: 'album or playlist', many: 'albums and playlists', a: 'an album or playlist'})
    assert.deepEqual(joinedNames([...soundcloud.slice(2, 3), soundcloud[1], {one: 'list', many: 'lists', a: 'a list'}]), {
        one: 'playlist, album or list', many: 'playlists, albums and lists', a: 'a playlist, album or list',
    })
    assert.deepEqual(growingNames([{kind: 'show', one: 'show', many: 'shows', a: 'a show'}, {kind: 'item', one: 'movie', many: 'movies', a: 'a movie'}]), {
        one: 'show', many: 'shows', a: 'a show',
    })
})

test('a section is named by its type, or by the first type of its kind', () => {
    assert.equal(sectionName(soundcloud, {type: 'playlist', kind: 'list'}).one, 'playlist')
    assert.equal(sectionName(soundcloud, {type: null, kind: 'list'}).a, 'an album')
    assert.equal(sectionName(soundcloud, {kind: 'show'}).many, 'shows')
})
