import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {cleanDomain, describeAccess} from '../src/lib/accessLabels'

test('typed domains are cleaned the way the server stores them', () => {
    assert.equal(cleanDomain('https://www.YouTube.com/watch?v=1'), 'youtube.com')
    assert.equal(cleanDomain(' m.youtube.com '), 'm.youtube.com')
    assert.equal(cleanDomain('vimeo.com:443/x'), 'vimeo.com')
    assert.equal(cleanDomain('  '), '')
})

const ytdlp = {id: 'ytdlp', name: 'yt-dlp', domains: ['*'], features: []}

test('the summary says what a limited downloader may do', () => {
    const lines = describeAccess({
        templateKey: 'downloader',
        levels: {quick_downloads: 'view'},
        sources: [{sourceKey: 'ytdlp', domains: ['youtube.com', 'youtu.be']}],
        membersOnly: false,
        deleteFiles: false,
    }, [ytdlp], 'tim')
    assert.equal(lines[0], 'tim sees Quick downloads (own).')
    assert.match(lines[1], /only use yt-dlp on youtube.com, youtu.be/)
    assert.match(lines[2], /not members-only/)
})

test('an administrator is summed up in one line', () => {
    const lines = describeAccess({templateKey: null, levels: {users: 'manage'}, sources: null, membersOnly: false, deleteFiles: false}, [], 'sam')
    assert.deepEqual(lines, ['sam is an administrator: everything, including managing users.'])
})
