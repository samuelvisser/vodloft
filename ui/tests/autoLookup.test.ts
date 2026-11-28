import assert from 'node:assert/strict'
import test from 'node:test'

import {looksLikeUrl} from '../src/lib/useAutoLookup'

test('full links and links without a scheme look like links', () => {
    assert.equal(looksLikeUrl('https://www.youtube.com/@TraversyMedia'), true)
    assert.equal(looksLikeUrl('  youtube.com/watch?v=abc '), true)
    assert.equal(looksLikeUrl('http://soundcloud.com/artist'), true)
})

test('what is not a web address yet is not looked up on its own', () => {
    assert.equal(looksLikeUrl(''), false)
    assert.equal(looksLikeUrl('https://'), false)
    assert.equal(looksLikeUrl('https://youtube'), false)
    assert.equal(looksLikeUrl('ben shapiro'), false)
    assert.equal(looksLikeUrl('ftp://example.com/file'), false)
})
