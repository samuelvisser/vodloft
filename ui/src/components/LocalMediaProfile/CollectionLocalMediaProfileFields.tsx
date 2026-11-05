import {type UseFormReturn} from 'react-hook-form'

import QualityField from './QualityField'

export default function CollectionLocalMediaProfileFields({form}: {form: UseFormReturn<any>}) {
    return (
        <>
            <hr className="form-section-divider" aria-hidden="true"/>
            <QualityField form={form} mode="collection"/>
        </>
    )
}
