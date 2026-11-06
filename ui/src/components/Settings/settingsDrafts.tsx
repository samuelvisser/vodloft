import {createContext, useCallback, useContext, useEffect, useRef, useState} from 'react'

/**
 * Settings that are not in config.yml, such as each Site's, but that the Settings page saves and
 * discards together with it. A section registers itself while it has unsaved changes.
 */
export type SettingsDraft = {
    /** How many settings changed, for the page's "Unsaved changes" bar. */
    count: number
    /** Saves the changes; resolves false when the backend refused them and the section shows why. */
    save: () => Promise<boolean>
    discard: () => void
}

type SettingsDraftsContextValue = {
    setDraft: (id: string, draft: SettingsDraft | null) => void
}

export const SettingsDraftsContext = createContext<SettingsDraftsContextValue | null>(null)

/** The Settings page's register of sections with unsaved changes. */
export function useSettingsDraftRegister() {
    const [drafts, setDrafts] = useState<Record<string, SettingsDraft>>({})
    const setDraft = useCallback((id: string, draft: SettingsDraft | null) => {
        setDrafts((current) => {
            if (!draft && !(id in current)) return current
            const next = {...current}
            if (draft) next[id] = draft
            else delete next[id]
            return next
        })
    }, [])
    return {drafts, setDraft}
}

/** Puts a section's unsaved changes in the Settings page's save bar while it has any. */
export function useSettingsDraft(id: string, count: number, save: () => Promise<boolean>, discard: () => void) {
    const context = useContext(SettingsDraftsContext)
    const saveRef = useRef(save)
    const discardRef = useRef(discard)
    saveRef.current = save
    discardRef.current = discard

    useEffect(() => {
        if (!context) return
        context.setDraft(id, count > 0
            ? {count, save: () => saveRef.current(), discard: () => discardRef.current()}
            : null)
    }, [context, id, count])

    useEffect(() => () => context?.setDraft(id, null), [context, id])
}
