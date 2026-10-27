import type {ReactNode} from 'react'

import {SettingsSection} from '../Settings/SettingsControls'

/** A Source's part of Settings › Sources: a settings section whose parts stack in one column. */
export default function SourceSection({title, description, summaryExtra, children}: {
    title: string
    description?: string
    summaryExtra?: ReactNode
    children: ReactNode
}) {
    return (
        <SettingsSection
            className="source-section"
            bodyClassName="source-section__body"
            title={title}
            description={description}
            summaryExtra={summaryExtra}
        >
            {children}
        </SettingsSection>
    )
}
