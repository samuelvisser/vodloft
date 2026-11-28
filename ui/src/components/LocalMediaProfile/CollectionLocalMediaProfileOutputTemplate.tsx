import {UseFormReturn} from 'react-hook-form'

import OutputTemplateEditor from './OutputTemplateEditor'

export default function CollectionLocalMediaProfileOutputTemplate({form, readOnly = false, isCreating = false, onCollectionRoot}: {
    form: UseFormReturn<any>
    readOnly?: boolean
    isCreating?: boolean
    onCollectionRoot?: (path: string) => void
}) {
    return (
        <OutputTemplateEditor
            form={form}
            mode="collection"
            readOnly={readOnly}
            isCreating={isCreating}
            onCollectionRoot={onCollectionRoot}
            placeholder={'/downloads/shows/{{ collection }}/{{ episode_title }}.ext'}
        />
    )
}
