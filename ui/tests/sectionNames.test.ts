import assert from 'node:assert/strict'
import test from 'node:test'

import {growingNames, joinedNames, listNames, sectionName, withArticle} from '../src/types/creator'

const soundcloud = [
    {key: 'feed', kind: 'feed', one: 'feed', many: 'feeds'},
    {key: 'album', kind: 'list', one: 'album', many: 'albums'},
    {key: 'playlist', kind: 'list', one: 'playlist', many: 'playlists'},
    {key: 'single', kind: 'item', one: 'single', many: 'singles'},
]

test('several section types are named together', () => {
    assert.deepEqual(listNames(soundcloud), {one: 'album or playlist', many: 'albums and playlists'})
    assert.deepEqual(joinedNames([...soundcloud.slice(1, 3), {one: 'list', many: 'lists'}]), {
        one: 'album, playlist or list', many: 'albums, playlists and lists',
    })
    assert.deepEqual(growingNames([{kind: 'show', one: 'show', many: 'shows'}, {kind: 'item', one: 'movie', many: 'movies'}]), {
        one: 'show', many: 'shows',
    })
})

test('a section is named by its type, or by the first type of its kind', () => {
    assert.equal(sectionName(soundcloud, {type: 'playlist', kind: 'list'}).one, 'playlist')
    assert.equal(sectionName(soundcloud, {type: null, kind: 'list'}).one, 'album')
    assert.equal(sectionName(soundcloud, {kind: 'show'}).many, 'shows')
    assert.equal(withArticle('album'), 'an album')
})
