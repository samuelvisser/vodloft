import {clearFormDraft, loadFormDraft, saveFormDraft} from '../FormDraft/formDraft'
import {isStreamProfileType, type StreamProfileType} from './streamProfileTypes'

/** What was typed into a Stream Profile form in this browser, so the user can leave it, such as to create the
 *  Download Profile it needs, and come back to it as it was. */
export type StreamProfileDraft = {
    mode: StreamProfileType
    values: Record<string, unknown>
}

const DRAFT_SCHEMA_VERSION = 'stream-profile-v1'

export function addStreamProfileDraftKey(): string {
    return 'streamProfileDraft:add'
}

export function editStreamProfileDraftKey(type: string, id: string | number): string {
    return `streamProfileDraft:edit:${type}:${id}`
}

export function loadStreamProfileDraft(key: string): StreamProfileDraft | null {
    const draft = loadFormDraft<StreamProfileDraft>(key, DRAFT_SCHEMA_VERSION)
    if (!draft) return null
    if (!draft.values || !isStreamProfileType(draft.mode)) {
        clearFormDraft(key)
        return null
    }
    return draft
}

export function saveStreamProfileDraft(key: string, draft: StreamProfileDraft): void {
    saveFormDraft(key, DRAFT_SCHEMA_VERSION, draft)
}

export function clearStreamProfileDraft(key: string): void {
    clearFormDraft(key)
}
