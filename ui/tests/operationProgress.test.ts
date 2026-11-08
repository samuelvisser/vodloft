import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {presentIndexingLabel, presentScanningLabel} from '../src/lib/operationProgress'
import type {TaskOperationRead} from '../src/types/schemas/operation'

function operation(progressMeta: Record<string, unknown>): TaskOperationRead {
    return {progress: null, progressMeta} as unknown as TaskOperationRead
}

test('the thumbnail check after an index says how far it is', () => {
    const checking = operation({found: 1249, thumbnails: {checked: 120, total: 1249}})

    assert.equal(presentIndexingLabel(checking), `Checking thumbnails… 120 of ${(1249).toLocaleString()}`)
    assert.equal(presentScanningLabel(checking), `Checking thumbnails… 120 of ${(1249).toLocaleString()}`)
    assert.equal(presentIndexingLabel(operation({found: 1249})), 'Indexing… 1249 episodes found')
})
