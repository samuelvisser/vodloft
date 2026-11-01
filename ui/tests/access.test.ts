import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {allows, homePath, setAccess, canUseSource, type AuthMe} from '../src/lib/access'

function me(levels: AuthMe['levels'], sources: AuthMe['sources'] = null): AuthMe {
    return {
        accountsEnabled: true, recovery: false,
        user: {id: 2, username: 'tim', templateKey: null, mustChangePassword: false},
        levels, administrator: false, sources, membersOnly: false, deleteFiles: false,
    }
}

test('levels rank none below view below manage', () => {
    const access = me({library: 'view'})
    assert.equal(allows(access, 'library'), true)
    assert.equal(allows(access, 'library', 'manage'), false)
    assert.equal(allows(access, 'tasks'), false)
    assert.equal(allows(null, 'library'), false)
})

test('a downloader starts on Quick download', () => {
    assert.equal(homePath(me({quick_downloads: 'view'})), '/quick-download')
    assert.equal(homePath(me({library: 'view', quick_downloads: 'view'})), '/')
    assert.equal(homePath(me({})), '/account')
})

test('source limits decide which Sources show', () => {
    setAccess(me({add_media: 'view'}, [{sourceKey: 'ytdlp', domains: ['youtube.com']}]))
    assert.equal(canUseSource('ytdlp'), true)
    assert.equal(canUseSource('dailywire'), false)
    setAccess(me({add_media: 'view'}))
    assert.equal(canUseSource('dailywire'), true)
    setAccess(null)
})

test('nothing is allowed until a one-time password is replaced', () => {
    const access = me({library: 'manage'})
    access.user!.mustChangePassword = true
    assert.equal(allows(access, 'library'), false)
})
