import {Controller, type UseFormReturn, useWatch} from 'react-hook-form'

import {VideoLocalMediaProfileScopeReg, type VideoLocalMediaProfileScope} from '../../types/local_media_profile'
import {DEFAULT_MOVIE_OUTPUT_TEMPLATE, DEFAULT_VIDEO_OUTPUT_TEMPLATE} from '../../types/schemas/video_local_media_profile'
import SimpleSelect from '../common/SimpleSelect'
import {ScopeRequestedField} from './ProfileFit'

const DEFAULT_TEMPLATES: Record<VideoLocalMediaProfileScope, string> = {
    both: DEFAULT_VIDEO_OUTPUT_TEMPLATE,
    videos: DEFAULT_VIDEO_OUTPUT_TEMPLATE,
    movies: DEFAULT_MOVIE_OUTPUT_TEMPLATE,
}

/** What a Video profile is offered for: single videos, movies with their extras, or both. */
export default function VideoLocalMediaProfileScopeField({form, isCreating}: {form: UseFormReturn<any>, isCreating: boolean}) {
    const {control, getValues, setValue, formState: {errors}} = form
    const scope = useWatch({control, name: 'videoScope'}) as string | undefined
    return (
        <div className="form-row">
            <label htmlFor="mp-video-scope">Available for</label>
            <ScopeRequestedField mode="video" scope={scope} apply={(next) => {
                form.setValue('videoScope', next, {shouldDirty: true, shouldValidate: true})
                return []
            }}>
            <Controller
                control={control}
                name="videoScope"
                render={({field}) => (
                    <SimpleSelect
                        inputId="mp-video-scope"
                        registry={VideoLocalMediaProfileScopeReg}
                        value={field.value ?? 'both'}
                        onChange={(value) => {
                            const previous = (field.value ?? 'both') as VideoLocalMediaProfileScope
                            const next = value as VideoLocalMediaProfileScope
                            field.onChange(next)
                            // A new profile's template follows while it is still the one the previous choice gave.
                            if (isCreating && getValues('outputTemplate') === DEFAULT_TEMPLATES[previous]) {
                                setValue('outputTemplate', DEFAULT_TEMPLATES[next], {shouldDirty: true, shouldValidate: true})
                            }
                        }}
                        onBlur={field.onBlur}
                        aria-invalid={!!errors.videoScope}
                        aria-describedby={errors.videoScope ? 'mp-video-scope-error' : 'mp-video-scope-help'}
                    />
                )}
            />
            </ScopeRequestedField>
            {errors.videoScope && (
                <div id="mp-video-scope-error" className="error" role="alert" aria-live="polite">
                    {String(errors.videoScope.message)}
                </div>
            )}
            <div className="help" id="mp-video-scope-help">
                Whether this profile is offered for single videos, for movies and their extras, or for both.
            </div>
        </div>
    )
}
