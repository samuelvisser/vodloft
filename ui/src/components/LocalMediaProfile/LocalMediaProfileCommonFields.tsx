import {useEffect} from 'react'
import {UseFormReturn} from 'react-hook-form'

import {type LocalMediaProfileType} from '../../types/local_media_profile'
import {type CollectionLocalMediaProfileScope} from '../../types/local_media_profile'
import {useLocalMediaProfileSites} from '../../lib/queries'
import CollectionLocalMediaProfileScopeField from './CollectionLocalMediaProfileScopeField'
import LocalMediaProfileSitesField from './LocalMediaProfileSitesField'
import VideoLocalMediaProfileScopeField from './VideoLocalMediaProfileScopeField'

/** The Profile section: name, where the profile is offered and for which Sites. */
export default function LocalMediaProfileCommonFields({
    form, mode, isCreating, onScopeChange,
}: {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
    isCreating: boolean
    onScopeChange: (scope: CollectionLocalMediaProfileScope) => void
}) {
    const {register, getValues, setValue, formState: {errors}} = form
    // A new profile starts the settings only some Sites show as Settings says.
    const {data: sites} = useLocalMediaProfileSites()
    useEffect(() => {
        if (!sites) return
        for (const [name, value] of Object.entries(sites.defaults)) {
            if (getValues(name) === undefined) setValue(name, value, {shouldDirty: false})
        }
    }, [sites, getValues, setValue])

    return (
        <>
            <div className="form-row">
                <label htmlFor="mp-name">Name</label>
                <input
                    id="mp-name"
                    className="input"
                    type="text"
                    placeholder="My 4k Profile"
                    {...register('name')}
                    aria-invalid={!!errors.name}
                    aria-describedby={errors.name ? 'mp-name-validate' : undefined}
                />
                {errors.name && (
                    <div id="mp-name-validate" className="error" role="alert" aria-live="polite">
                        {String(errors.name.message)}
                    </div>
                )}
            </div>

            <div className="local-media-profile-pair">
                {mode === 'collection'
                    ? <CollectionLocalMediaProfileScopeField form={form} onScopeChange={onScopeChange} isCreating={isCreating}/>
                    : <VideoLocalMediaProfileScopeField form={form} isCreating={isCreating}/>}
                <LocalMediaProfileSitesField form={form} mode={mode}/>
            </div>
        </>
    )
}
