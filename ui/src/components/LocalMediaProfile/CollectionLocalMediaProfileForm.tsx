import {UseFormReturn} from 'react-hook-form'

import CollectionLocalMediaProfileFields from './CollectionLocalMediaProfileFields'
import CollectionLocalMediaProfileOutputTemplate from './CollectionLocalMediaProfileOutputTemplate'

export default function CollectionLocalMediaProfileForm({form}: { form: UseFormReturn<any> }) {
    return (
        <>
            <CollectionLocalMediaProfileFields form={form}/>
            <CollectionLocalMediaProfileOutputTemplate form={form}/>
        </>
    )
}
