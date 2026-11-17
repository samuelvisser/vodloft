import {type ReactNode, useEffect, useState} from 'react'
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

/** One folding part of the Local Media Profile form, like the sections in Settings. */
export default function LocalMediaProfileSection({form, title, description, summary, fields, defaultOpen = false, children}: Props) {
    const [open, setOpen] = useState(defaultOpen)
    const {errors, submitCount} = form.formState
    const hasError = fields.some((name) => errors[name])
    // A refused save must show its errors, so the sections holding them open.
    useEffect(() => {
        if (hasError) setOpen(true)
    }, [hasError, submitCount])

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
