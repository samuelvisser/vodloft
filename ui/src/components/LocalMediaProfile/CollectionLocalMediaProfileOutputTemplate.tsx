import type {ReactNode} from 'react'
import {UseFormReturn} from 'react-hook-form'

import OutputTemplateEditor from './OutputTemplateEditor'

export default function CollectionLocalMediaProfileOutputTemplate({form, readOnly = false, isCreating = false, onCollectionRoot, headerActions}: {
    form: UseFormReturn<any>
    readOnly?: boolean
    isCreating?: boolean
    onCollectionRoot?: (path: string) => void
    headerActions?: ReactNode
}) {
    return (
        <OutputTemplateEditor
            form={form}
            mode="collection"
            readOnly={readOnly}
            isCreating={isCreating}
            onCollectionRoot={onCollectionRoot}
            headerActions={headerActions}
            placeholder={'/downloads/shows/{{ collection }}/{{ episode_title }}.ext'}
            help={(
                <>
                    <p>
                        Collection, season, episode, and publication-date values are available. The editor's variable menu
                        lists every supported value and explains what it represents.
                    </p>
                    <p>
                        Conditional year example:<br/>
                        <code>{"{{ episode_title }}{% if year %} ({{ year }}){% endif %}.ext"}</code>
                    </p>
                    <p>
                        If a date, season, or another optional value is not known, it is an empty string. Use an
                        <b> if</b> block to omit any punctuation or folders that belong with it.
                    </p>
                </>
            )}
        />
    )
}
