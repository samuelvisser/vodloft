import {createContext, type ReactNode, useContext, useEffect, useState} from 'react'
import {type UseFormReturn} from 'react-hook-form'

import {SettingsSection} from '../Settings/SettingsControls'
import '../../pages/SettingsPage.css'
import './LocalMediaProfileSection.css'

type Props = {
    form: UseFormReturn<any>
    title: string
    /** What the section is about, shown while it is open. */
    description: string
    /** The section's current values in one line, shown while it is folded. */
    summary: ReactNode
    /** The form fields inside, so the section opens when one of them has an error. */
    fields: readonly string[]
    defaultOpen?: boolean
    children: ReactNode
}

/** Fields that just changed for the user, such as by a preset, so the sections holding them open. */
export type RevealedFields = {fields: readonly string[]} | null

const RevealedFieldsContext = createContext<{
    revealed: RevealedFields
    reveal: (fields: readonly string[]) => void
}>({revealed: null, reveal: () => undefined})

/** Lets a part of the form open the sections of the fields it changed. */
export function RevealFieldsProvider({children}: {children: ReactNode}) {
    const [revealed, setRevealed] = useState<RevealedFields>(null)
    // A new object every time, so revealing the same fields again opens a section the user folded since.
    const reveal = (fields: readonly string[]) => setRevealed({fields})
    return <RevealedFieldsContext.Provider value={{revealed, reveal}}>{children}</RevealedFieldsContext.Provider>
}

export function useRevealFields() {
    return useContext(RevealedFieldsContext).reveal
}

/** One folding part of the Local Media Profile form, like the sections in Settings. */
export default function LocalMediaProfileSection({form, title, description, summary, fields, defaultOpen = false, children}: Props) {
    const [open, setOpen] = useState(defaultOpen)
    const {errors, submitCount} = form.formState
    const hasError = fields.some((name) => errors[name])
    // A refused save must show its errors, so the sections holding them open.
    useEffect(() => {
        if (hasError) setOpen(true)
    }, [hasError, submitCount])
    const {revealed} = useContext(RevealedFieldsContext)
    useEffect(() => {
        if (revealed?.fields.some((name) => fields.includes(name))) setOpen(true)
    }, [revealed, fields])

    return (
        <SettingsSection
            className="local-media-profile-section"
            bodyClassName="local-media-profile-section__body"
            title={title}
            description={open ? description : undefined}
            summaryExtra={open ? undefined : <small className="local-media-profile-section__summary">{summary}</small>}
            open={open}
            onToggle={setOpen}
        >
            {children}
        </SettingsSection>
    )
}
