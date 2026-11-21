import {strict as assert} from 'node:assert'
import {test} from 'node:test'
import {QueryClient} from '@tanstack/react-query'

import {forgetDeletedCollection} from '../src/lib/deletedCollection'
import type {CollectionRead} from '../src/types/schemas/collection'

const stored = new Map<string, string>()
;(globalThis as any).localStorage = {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => void stored.set(key, value),
    removeItem: (key: string) => void stored.delete(key),
}

const collection = (slug: string) => ({slug}) as unknown as CollectionRead

test('A deleted collection leaves the cached list, its own caches and every page that lists it', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['collections'], [collection('kept'), collection('gone')])
    queryClient.setQueryData(['collection', 'gone'], collection('gone'))
    queryClient.setQueryData(['seasons', 'gone'], [])
    queryClient.setQueryData(['episodes', 'gone', 'preview', 15], {items: []})
    queryClient.setQueryData(['creator', 'artist'], {slug: 'artist'})
    queryClient.setQueryData(['creator', 'artist', 'episodes'], {items: []})
    queryClient.setQueryData(['creators'], [])
    queryClient.setQueryData(['collectionsView'], [])

    await forgetDeletedCollection(queryClient, 'gone')

    assert.deepEqual(queryClient.getQueryData<CollectionRead[]>(['collections'])?.map((c) => c.slug), ['kept'])
    assert.equal(queryClient.getQueryData(['collection', 'gone']), undefined)
    assert.equal(queryClient.getQueryData(['seasons', 'gone']), undefined)
    assert.equal(queryClient.getQueryData(['episodes', 'gone', 'preview', 15]), undefined)
    // The list in the browser's storage, which a reload starts from, forgets it too.
    assert.deepEqual(JSON.parse(stored.get('wl_rq_v1:collections') ?? '[]').map((c: CollectionRead) => c.slug), ['kept'])
    for (const key of [['creator', 'artist'], ['creator', 'artist', 'episodes'], ['creators'], ['collectionsView'], ['collections']]) {
        assert.equal(queryClient.getQueryState(key)?.isInvalidated, true, JSON.stringify(key))
    }
})

test('A page that shows the deleted collection keeps its query', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['collections'], [collection('gone')])
    queryClient.setQueryData(['collection', 'gone'], collection('gone'))

    await forgetDeletedCollection(queryClient, 'gone', {keepCollectionQuery: true})

    assert.notEqual(queryClient.getQueryData(['collection', 'gone']), undefined)
    assert.deepEqual(queryClient.getQueryData(['collections']), [])
})
