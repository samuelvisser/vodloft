import type {ReactNode} from 'react'
import {Controller, type UseFormReturn, useWatch} from 'react-hook-form'

import {CollectionLocalMediaProfileScopeReg, type CollectionLocalMediaProfileScope} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'
import DisabledReason from '../common/DisabledReason'
import type {SelectOptionState} from '../common/Select'
import SimpleSelect from '../common/SimpleSelect'
import {switchProfileKind, useTracksLock} from './musicKind'
import {ScopeRequestedField} from './ProfileFit'

const FROM_TRACKS_REASON = 'This profile already has downloaded music tracks, so what it is available for can\'t change. Duplicate it to start one for something else.'
const TO_TRACKS_REASON = 'This profile already has downloads and downloads audio only, which for Music keeps tracks. Choose a video download first, or duplicate it to start one for music tracks.'

// An option that can't be chosen explains why, as the items of an Actions menu do.
const explainDisabledOption = (option: ReactNode, _data: unknown, {isDisabled}: SelectOptionState) => isDisabled ? (
    <DisabledReason reason={TO_TRACKS_REASON} placement="below-start" as="div">
        {({describedBy}) => <div aria-describedby={describedBy}>{option}</div>}
    </DisabledReason>
) : option

/**
 * What a Collection profile is offered for. A profile for Music keeps tracks, with the tags music players read, when it
 * downloads audio only, so a profile only starts or stops keeping tracks before it has downloads.
 */
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
    const [scope, format] = useWatch({control, name: ['collectionScope', 'preferredFormat']}) as [string | undefined, string | undefined]
    const {hasDownloads, savedTracks} = useTracksLock(form, isCreating)
    const locked = hasDownloads && savedTracks
    // Music with the audio only download keeps tracks, which a profile with downloads can't start doing.
    const tracksBlocked = hasDownloads && !locked && format === 'format_audio_only'
    const switchScope = (previousScope: CollectionLocalMediaProfileScope, nextScope: CollectionLocalMediaProfileScope) =>
        switchProfileKind(form, {scope: previousScope, format}, {scope: nextScope, format}, isCreating)

    return (
        <div className="form-row">
            <label htmlFor="mp-collection-scope">Available for</label>
            <ScopeRequestedField mode="collection" scope={scope} apply={(next) => {
                const nextScope = next as CollectionLocalMediaProfileScope
                const previousScope = (scope ?? 'podcast-and-series') as CollectionLocalMediaProfileScope
                onScopeChange(nextScope)
                form.setValue('collectionScope', nextScope, {shouldDirty: true, shouldValidate: true})
                return switchScope(previousScope, nextScope)
            }}>
            <Controller
                control={control}
                name="collectionScope"
                render={({field}) => (
                    <DisabledReason reason={locked ? FROM_TRACKS_REASON : undefined} placement="below-start" as="div">
                        {({describedBy, explain}) => (
                            <div onClick={locked ? explain : undefined}>
                                <SimpleSelect
                                    inputId="mp-collection-scope"
                                    registry={CollectionLocalMediaProfileScopeReg}
                                    value={field.value ?? 'podcast-and-series'}
                                    isDisabled={locked}
                                    isOptionDisabled={(option) => tracksBlocked && option.value === 'music'}
                                    renderOption={explainDisabledOption}
                                    className="select-with-option-reasons"
                                    onChange={(value) => {
                                        const nextScope = value as CollectionLocalMediaProfileScope
                                        const previousScope = (field.value ?? 'podcast-and-series') as CollectionLocalMediaProfileScope
                                        // Let the defaulting logic read the previous scope before
                                        // updating the form with the new one.
                                        onScopeChange(nextScope)
                                        field.onChange(nextScope)
                                        switchScope(previousScope, nextScope)
                                    }}
                                    onBlur={field.onBlur}
                                    aria-invalid={!!errors.collectionScope}
                                    aria-describedby={describedBy ?? (errors.collectionScope ? 'mp-collection-scope-error' : 'mp-collection-scope-help')}
                                />
                            </div>
                        )}
                    </DisabledReason>
                )}
            />
            </ScopeRequestedField>
            {errors.collectionScope && (
                <div id="mp-collection-scope-error" className="error" role="alert" aria-live="polite">
                    {String(errors.collectionScope.message)}
                </div>
            )}
            <div className="help" id="mp-collection-scope-help">
                <ReadMore summary="Controls where this profile is available in VODLoft.">
                    <p>
                        <strong>Music</strong> keeps the tracks of Music collections when the profile downloads
                        audio only, with the artist, album and track number that music players read, and their music
                        videos when it downloads video, for a Music Videos library. A profile only starts or stops
                        keeping tracks before it has downloads.
                    </p>
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
