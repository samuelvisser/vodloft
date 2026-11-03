import {type UseFormReturn} from 'react-hook-form'

import QualityField from './QualityField'

export default function CollectionLocalMediaProfileFields({form}: {form: UseFormReturn<any>}) {
    return <QualityField form={form} allowHls/>
}
