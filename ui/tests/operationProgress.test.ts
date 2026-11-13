import {strict as assert} from 'node:assert'
import {test} from 'node:test'

import {presentIndexingLabel, presentIndexingStatus, presentScanningLabel, presentScanningStatus} from '../src/lib/operationProgress'
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

test('a running indexing or scan says only how far it is on its own line', () => {
    assert.equal(presentIndexingStatus(operation({found: 1})), '1 episode found')
    assert.equal(presentScanningStatus(operation({found: 3})), '3 new episodes found')
    assert.equal(presentIndexingStatus({progress: 42, progressMeta: {}} as unknown as TaskOperationRead), '42%')
    assert.equal(presentIndexingStatus(operation({})), null)
    assert.equal(presentScanningLabel(operation({})), 'Scanning…')
})
