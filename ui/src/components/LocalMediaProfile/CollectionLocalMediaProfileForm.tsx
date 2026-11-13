import {UseFormReturn} from 'react-hook-form'

import CollectionLocalMediaProfileOutputTemplate from './CollectionLocalMediaProfileOutputTemplate'

export default function CollectionLocalMediaProfileForm({form}: { form: UseFormReturn<any> }) {
    return <CollectionLocalMediaProfileOutputTemplate form={form}/>
}
