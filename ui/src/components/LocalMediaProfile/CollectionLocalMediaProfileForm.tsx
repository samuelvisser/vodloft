import {UseFormReturn} from 'react-hook-form'

import CollectionLocalMediaProfileOutputTemplate from './CollectionLocalMediaProfileOutputTemplate'

export default function CollectionLocalMediaProfileForm({form, isCreating}: { form: UseFormReturn<any>, isCreating: boolean }) {
    return <CollectionLocalMediaProfileOutputTemplate form={form} isCreating={isCreating}/>
}
