import assert from 'node:assert/strict'
import test from 'node:test'

import {joinedNames} from '../src/types/creator'

const names = (singular: string, plural: string, a: string) => ({singular, plural, a})

test('several section types are named together, as the backend joins them', () => {
    assert.deepEqual(joinedNames([names('album', 'albums', 'an album'), names('playlist', 'playlists', 'a playlist')]),
        names('album or playlist', 'albums and playlists', 'an album or playlist'))
    assert.deepEqual(joinedNames([names('playlist', 'playlists', 'a playlist'), names('album', 'albums', 'an album'), names('list', 'lists', 'a list')]),
        names('playlist, album or list', 'playlists, albums and lists', 'a playlist, album or list'))
})
