import {useMemo} from 'react'
import {Controller, type UseFormReturn} from 'react-hook-form'
import Select from 'react-select'

import {useSources} from '../../lib/queries'
import {sourcesForLocalMediaProfileType, type LocalMediaProfileType} from '../../types/local_media_profile'
import {createSelectRegistry} from '../../utils/selectRegistry'
import ReadMore from '../../utils/ReadMore'

/** The Sources a profile is offered for. Every Source is chosen until the user removes one. */
export default function LocalMediaProfileSourcesField({form, mode}: {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
}) {
    const {control, formState: {errors}} = form
    const {data: sources} = useSources()
    const sourceReg = useMemo(() => {
        const available = sourcesForLocalMediaProfileType(sources, mode)
        return createSelectRegistry(
            'LocalMediaProfileSource',
            Object.fromEntries(available.map((source) => [source.id, {label: source.name}])),
            available.map((source) => source.id),
        )
    }, [sources, mode])

    // With one Source there is nothing to choose.
    if (sourceReg.values.length < 2) return null

    return (
        <div className="form-row">
            <label htmlFor="mp-sources">Sources</label>
            <Controller
                control={control}
                name="sourceKeys"
                render={({field}) => (
                    <Select
                        inputId="mp-sources"
                        isMulti
                        isSearchable={false}
                        isClearable={false}
                        closeMenuOnSelect={false}
                        classNamePrefix="select"
                        placeholder="Choose at least one Source"
                        options={sourceReg.options}
                        value={sourceReg.options.filter((option) => field.value == null || field.value.includes(option.value))}
                        onChange={(options) => {
                            const chosen = options.map((option) => option.value)
                            // Every Source chosen offers the profile for Sources added later too.
                            field.onChange(chosen.length === sourceReg.values.length ? null : chosen)
                        }}
                        onBlur={field.onBlur}
                        aria-invalid={!!errors.sourceKeys}
                        aria-describedby={errors.sourceKeys ? 'mp-sources-error' : 'mp-sources-help'}
                    />
                )}
            />
            {errors.sourceKeys && (
                <div id="mp-sources-error" className="error" role="alert" aria-live="polite">
                    {String(errors.sourceKeys.message)}
                </div>
            )}
            <div className="help" id="mp-sources-help">
                <ReadMore summary="The Sources this profile is offered for.">
                    <p>Remove a Source to stop offering this profile for its media. While every Source is chosen, Sources added to VODLoft later are offered this profile too.</p>
                    <p>Media already downloaded with this profile stays where it is.</p>
                </ReadMore>
            </div>
        </div>
    )
}
