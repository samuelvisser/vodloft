import type {ReactNode} from 'react'
import {UseFormReturn} from 'react-hook-form'

import CollectionLocalMediaProfileOutputTemplate from './CollectionLocalMediaProfileOutputTemplate'

export default function CollectionLocalMediaProfileForm({form, isCreating, onCollectionRoot, outputTemplateActions}: {
    form: UseFormReturn<any>
    isCreating: boolean
    onCollectionRoot?: (path: string) => void
    outputTemplateActions?: ReactNode
}) {
    return <CollectionLocalMediaProfileOutputTemplate form={form} isCreating={isCreating} onCollectionRoot={onCollectionRoot} headerActions={outputTemplateActions}/>
}
