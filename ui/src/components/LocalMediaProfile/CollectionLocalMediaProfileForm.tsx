import {UseFormReturn} from 'react-hook-form'

import CollectionLocalMediaProfileOutputTemplate from './CollectionLocalMediaProfileOutputTemplate'

export default function CollectionLocalMediaProfileForm({form, isCreating, onCollectionRoot}: {
    form: UseFormReturn<any>
    isCreating: boolean
    onCollectionRoot?: (path: string) => void
}) {
    return <CollectionLocalMediaProfileOutputTemplate form={form} isCreating={isCreating} onCollectionRoot={onCollectionRoot}/>
}
