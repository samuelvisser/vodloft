import assert from 'node:assert/strict'
import test from 'node:test'

import {growingNames, joinedNames, listNames} from '../src/types/creator'

const names = (singular: string, plural: string, a: string) => ({singular, plural, a})

const soundcloud = [
    {key: 'feed', kind: 'feed', names: names('feed', 'feeds', 'a feed')},
    {key: 'album', kind: 'list', names: names('album', 'albums', 'an album')},
    {key: 'playlist', kind: 'list', names: names('playlist', 'playlists', 'a playlist')},
    {key: 'single', kind: 'item', names: names('single', 'singles', 'a single')},
]

test('several section types are named together', () => {
    assert.deepEqual(listNames(soundcloud), names('album or playlist', 'albums and playlists', 'an album or playlist'))
    assert.deepEqual(joinedNames([soundcloud[2].names, soundcloud[1].names, names('list', 'lists', 'a list')]),
        names('playlist, album or list', 'playlists, albums and lists', 'a playlist, album or list'))
    assert.deepEqual(growingNames([{kind: 'show', names: names('show', 'shows', 'a show')}, {kind: 'item', names: names('movie', 'movies', 'a movie')}]),
        names('show', 'shows', 'a show'))
})
