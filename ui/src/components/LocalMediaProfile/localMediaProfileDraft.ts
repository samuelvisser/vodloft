import {clearFormDraft, loadFormDraft, saveFormDraft} from '../FormDraft/formDraft'
import type {LocalMediaProfileType} from '../../types/local_media_profile'

export type LocalMediaProfileDraft<T> = {
    mode: LocalMediaProfileType
    values: Partial<T>
}

const DRAFT_SCHEMA_VERSION = 'local-media-profile-v3'

export function addLocalMediaProfileDraftKey(): string {
    return 'localMediaProfileDraft:add'
}

export function editLocalMediaProfileDraftKey(slug: string): string {
    return `localMediaProfileDraft:edit:${slug}`
}

export function loadLocalMediaProfileDraft<T>(key: string): LocalMediaProfileDraft<T> | null {
    const draft = loadFormDraft<LocalMediaProfileDraft<T>>(key, DRAFT_SCHEMA_VERSION)
    if (!draft) return null
    if (!draft.values || !['collection', 'video'].includes(draft.mode)) {
        clearFormDraft(key)
        return null
    }
    return draft
}

export function saveLocalMediaProfileDraft<T>(key: string, draft: LocalMediaProfileDraft<T>): void {
    saveFormDraft(key, DRAFT_SCHEMA_VERSION, draft)
}

export function clearLocalMediaProfileDraft(key: string): void {
    clearFormDraft(key)
}
