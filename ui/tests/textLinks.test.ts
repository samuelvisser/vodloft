import assert from 'node:assert/strict'
import test from 'node:test'

import {splitTextLinks} from '../src/utils/textLinks'

const links = (text: string) => splitTextLinks(text).filter((part) => part.kind === 'link').map((part) => part.kind === 'link' ? part.url : '')

test('web addresses in a description become links, and the text around them stays', () => {
    assert.deepEqual(splitTextLinks('Follow her on YouTube:\nhttps://www.youtube.com/@Faith-May2005\n\nThanks'), [
        {kind: 'text', text: 'Follow her on YouTube:\n'},
        {kind: 'link', url: 'https://www.youtube.com/@Faith-May2005'},
        {kind: 'text', text: '\n\nThanks'},
    ])
    assert.deepEqual(splitTextLinks('No links here'), [{kind: 'text', text: 'No links here'}])
})

test('punctuation that ends the sentence is not part of the address', () => {
    assert.deepEqual(links('See https://example.com/a. Or (https://example.com/b), or https://example.com/c!'),
        ['https://example.com/a', 'https://example.com/b', 'https://example.com/c'])
})

test('brackets that belong to the address stay', () => {
    assert.deepEqual(links('https://en.wikipedia.org/wiki/Foo_(bar) and https://example.com/?q=1&x=[2]'),
        ['https://en.wikipedia.org/wiki/Foo_(bar)', 'https://example.com/?q=1&x=[2]'])
})

test('a scheme without a host is not a link', () => {
    assert.deepEqual(links('https:// nothing'), [])
})
