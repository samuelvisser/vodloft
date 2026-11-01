import {Controller, type UseFormReturn} from 'react-hook-form'

import {CollectionLocalMediaProfileScopeReg, type CollectionLocalMediaProfileScope} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'
import SimpleSelect from '../common/SimpleSelect'

export default function CollectionLocalMediaProfileScopeField({
    form,
    onScopeChange,
    isCreating,
}: {
    form: UseFormReturn<any>
    onScopeChange: (scope: CollectionLocalMediaProfileScope) => void
    isCreating: boolean
}) {
    const {control, formState: {errors}} = form

    return (
        <div className="form-row">
            <label htmlFor="mp-collection-scope">Available for</label>
            <Controller
                control={control}
                name="collectionScope"
                render={({field}) => (
                    <SimpleSelect
                        inputId="mp-collection-scope"
                        registry={CollectionLocalMediaProfileScopeReg}
                        value={field.value ?? 'both'}
                        onChange={(value) => {
                            const nextScope = value as CollectionLocalMediaProfileScope
                            // Let the defaulting logic read the previous scope before
                            // updating the form with the new one.
                            onScopeChange(nextScope)
                            field.onChange(nextScope)
                        }}
                        onBlur={field.onBlur}
                        aria-invalid={!!errors.collectionScope}
                        aria-describedby={errors.collectionScope ? 'mp-collection-scope-error' : 'mp-collection-scope-help'}
                    />
                )}
            />
            {errors.collectionScope && (
                <div id="mp-collection-scope-error" className="error" role="alert" aria-live="polite">
                    {String(errors.collectionScope.message)}
                </div>
            )}
            <div className="help" id="mp-collection-scope-help">
                <ReadMore summary="Controls where this profile is available in VODLoft.">
                    <p>Podcast-only profiles default to no subtitles. Series and mixed profiles default to downloading subtitles beside the media when first created.</p>
                    {isCreating
                        ? <p>Changing this selection adjusts the subtitle default until you explicitly choose a subtitle option.</p>
                        : <p>Changing availability on an existing profile does not change its saved subtitle behavior.</p>
                    }
                </ReadMore>
            </div>
        </div>
    )
}
