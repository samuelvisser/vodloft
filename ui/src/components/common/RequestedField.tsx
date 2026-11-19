import {createContext, type ReactNode, useContext, useEffect, useMemo, useReducer, useRef} from 'react'

import RequestedNote from './RequestedNote'

/** What the link a form was opened with set, by field: the value it set, so the field can tell when the user changed
 *  it again. Kept for the whole form, so a field that unmounts and comes back is not set a second time. */
type Store = Map<string, {applied: boolean, snapshot?: string}>

type RequestedFieldsValue = {
    /** A new record, which only says when a choice no longer fits, or an existing one, where every field the link
     *  changed says so. */
    mode: 'create' | 'edit'
    store: Store
    /** Hears the form fields a link changed, such as to open the folded sections that hold them. */
    onApplied: (fields: readonly string[]) => void
    /** Whether the form holds its values yet. An edit form first loads the record. */
    ready: boolean
}

const RequestedFieldsContext = createContext<RequestedFieldsValue | null>(null)

/**
 * The form a link can fill in. A provider inside another shares its record of what the link set, and adds its own
 * ``onApplied``, such as a form whose sections open for the fields the link changed.
 */
export function RequestedFieldsProvider({mode, onApplied, ready, children}: {
    mode?: 'create' | 'edit'
    onApplied?: (fields: readonly string[]) => void
    ready?: boolean
    children: ReactNode
}) {
    const parent = useContext(RequestedFieldsContext)
    const ownStore = useRef<Store>(new Map())
    const value = useMemo<RequestedFieldsValue>(() => ({
        mode: mode ?? parent?.mode ?? 'create',
        store: parent?.store ?? ownStore.current,
        ready: (ready ?? true) && (parent?.ready ?? true),
        onApplied: (fields) => {
            parent?.onApplied(fields)
            onApplied?.(fields)
        },
    }), [mode, onApplied, ready, parent])
    return <RequestedFieldsContext.Provider value={value}>{children}</RequestedFieldsContext.Provider>
}

type Props = {
    /** Names this field in the form, once per form. */
    id: string
    /** What the link asks for, or nothing when the form was opened without it. */
    requested: unknown
    /** The field's value now. */
    value: unknown
    /** Sets the field to what the link asks for. Returns false while it can't yet, such as while the choices load,
     *  and may return the other form fields it changed with it. */
    apply: () => boolean | readonly string[] | void
    /** The form fields this one stands for, which a form opens when the link changed them. */
    fields?: readonly string[]
    /** For a field that decides whether the record fits what the link was for: whether the value now still does.
     *  Leave it out for a field that only fills something in. */
    fits?: () => boolean
    /** Says why the value now no longer fits what the link was for. */
    incompatible?: ReactNode
    /** In an existing record, says that the link changed this field. */
    changed?: ReactNode
    children: ReactNode
}

const DEFAULT_CHANGED = 'The link you followed changed this setting. Check it before you save.'

/**
 * A form field a link can set, such as the Local Media Profile a link from a Stream Profile asks for. It sets the
 * field once, as the form opens. In an existing record it then says that the link changed it, while the value is
 * still the one the link set. A field that decides whether the record fits what the link was for says so as soon as
 * the user changes it to a value that no longer does, in a new record and an existing one.
 */
export default function RequestedField({id, requested, value, apply, fields = [], fits, incompatible, changed = DEFAULT_CHANGED, children}: Props) {
    const context = useContext(RequestedFieldsContext)
    const [, rerender] = useReducer((count: number) => count + 1, 0)
    const asked = requested !== undefined && requested !== null && requested !== ''
    const entry = context?.store.get(id)

    useEffect(() => {
        if (!context?.ready || !asked || context.store.get(id)?.applied) return
        const result = apply()
        if (result === false) return
        context.store.set(id, {applied: true})
        context.onApplied([...fields, ...(Array.isArray(result) ? result : [])])
        rerender()
    })

    // The value the link set, as the field shows it once the change has rendered.
    const current = JSON.stringify(value ?? null)
    if (entry?.applied && entry.snapshot === undefined) entry.snapshot = current

    let note: ReactNode = null
    if (asked && fits && !fits()) note = incompatible
    else if (context?.mode === 'edit' && entry?.applied && entry.snapshot === current) note = changed
    return (
        <>
            {children}
            {note && <RequestedNote>{note}</RequestedNote>}
        </>
    )
}
