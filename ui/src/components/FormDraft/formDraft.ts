import type {Versioned} from '../../types/data'
import {getCurrentAppVersion} from '../../utils/helpers'

// A draft keeps what was typed into a form in this browser, so a reload or a visit elsewhere does not lose it.
// It belongs to one VODLoft version and one shape of the form: a draft from another version is dropped.

function draftVersion(schemaVersion: string): string {
    return `${getCurrentAppVersion() ?? 'development'}:${schemaVersion}`
}

export function loadFormDraft<T>(key: string, schemaVersion: string): T | null {
    try {
        const raw = localStorage.getItem(key)
        if (!raw) return null
        const parsed = JSON.parse(raw) as Versioned<T> | null
        if (parsed?.version !== draftVersion(schemaVersion) || parsed.data == null) {
            localStorage.removeItem(key)
            return null
        }
        return parsed.data
    } catch {
        return null
    }
}

export function saveFormDraft<T>(key: string, schemaVersion: string, data: T): void {
    try {
        const payload: Versioned<T> = {version: draftVersion(schemaVersion), data}
        localStorage.setItem(key, JSON.stringify(payload))
    } catch {
        // Keeping a draft must never get in the way of filling in the form.
    }
}

export function clearFormDraft(key: string): void {
    try {
        localStorage.removeItem(key)
    } catch {
        // Ignore unavailable browser storage.
    }
}
