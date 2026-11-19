import {Controller, type UseFormReturn, useWatch} from 'react-hook-form'
import {components, type OptionProps} from 'react-select'

import {useLocalMediaProfileView} from '../../lib/queries'
import {CollectionLocalMediaProfileScopeReg, type CollectionLocalMediaProfileScope} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'
import DisabledReason from '../common/DisabledReason'
import SimpleSelect from '../common/SimpleSelect'
import {ScopeRequestedField} from './ProfileFit'
import {parseOutputTemplate, renderCompactOutputTemplate} from './outputTemplateFormatting'
import {outputTemplatePreset} from './outputTemplatePresets'
import {DEFAULT_COLLECTION_OUTPUT_TEMPLATE} from '../../types/schemas/collection_local_media_profile'

type Option = {value: string, label: string}

const TO_TRACKS_REASON = 'This profile already has downloads, so it can\'t be changed to Music tracks. Duplicate it to start one for Music tracks.'
const FROM_TRACKS_REASON = 'This profile already has downloaded music tracks, so what it is available for can\'t change. Duplicate it to start one for something else.'

// An option that can't be chosen explains why, as the items of an Actions menu do.
function ScopeOption(props: OptionProps<Option, false>) {
    const reason = props.isDisabled ? (props.selectProps as {disabledOptionReason?: string}).disabledOptionReason : undefined
    if (!reason) return <components.Option {...props}/>
    return (
        <DisabledReason reason={reason} placement="below-start" as="div">
            {({describedBy}) => <div aria-describedby={describedBy}><components.Option {...props}/></div>}
        </DisabledReason>
    )
}

const SCOPE_COMPONENTS = {Option: ScopeOption}

/** Sets what a profile needs for what it is now available for: Music tracks are audio only, and a Music collection's
 *  videos are music videos. A new profile also starts from the preset that fits; a saved one keeps its own
 *  template. */
export function switchCollectionScope(
    form: UseFormReturn<any>,
    previous: CollectionLocalMediaProfileScope,
    next: CollectionLocalMediaProfileScope,
    isCreating: boolean,
): string[] {
    const {getValues} = form
    const changed: string[] = []
    const options = {shouldDirty: true, shouldValidate: true}
    const setValue = (name: string, value: unknown) => {
        if (getValues(name) === value) return
        form.setValue(name, value, options)
        changed.push(name)
    }
    const startFrom = (key: string, base: string) => {
        const preset = outputTemplatePreset(key)!
        setValue('outputTemplate', renderCompactOutputTemplate(parseOutputTemplate(preset.template(base), 'editor')))
        for (const [name, value] of Object.entries(preset.choices)) setValue(name, value)
    }
    if (next === 'music_tracks') {
        // Tracks are sound only, tagged for music players.
        setValue('preferredFormat', 'format_audio_only')
        if (isCreating) {
            setValue('thumbnailMode', 'embed')
            startFrom('music', '/downloads/music')
        }
    } else if (previous === 'music_tracks' && getValues('audioFormat') === 'flac') {
        setValue('audioFormat', 'm4a')
    }
    if (next === 'music_videos') {
        // A Music collection's videos are music videos.
        setValue('episodeNfo', 'music_video')
        if (isCreating) {
            if (getValues('preferredFormat') === 'format_audio_only') setValue('preferredFormat', 'format_1080p')
            startFrom('music_videos', '/downloads/music-videos')
        }
    } else if (previous === 'music_videos') {
        setValue('episodeNfo', 'episode')
    }
    const music = (scope: string) => scope === 'music_tracks' || scope === 'music_videos'
    if (isCreating && music(previous) && !music(next)) {
        setValue('outputTemplate', DEFAULT_COLLECTION_OUTPUT_TEMPLATE)
    }
    return changed
}


/**
 * What a Collection profile is offered for. Music tracks keep audio only, with the tags music players read, so a
 * profile only changes to or from them before it has downloads.
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
    const slug = useWatch({control, name: 'slug'}) as string | undefined
    const scope = useWatch({control, name: 'collectionScope'}) as string | undefined
    const {data: view} = useLocalMediaProfileView(isCreating ? undefined : slug)
    const hasDownloads = !isCreating && (view?.statistics.managedMediaCount ?? 0) > 0
    const savedScope = view?.profile.type === 'collection' ? view.profile.collectionScope : undefined
    const locked = hasDownloads && savedScope === 'music_tracks'
    const tracksBlocked = hasDownloads && !locked

    return (
        <div className="form-row">
            <label htmlFor="mp-collection-scope">Available for</label>
            <ScopeRequestedField mode="collection" scope={scope} apply={(next) => {
                const nextScope = next as CollectionLocalMediaProfileScope
                const previousScope = (scope ?? 'both') as CollectionLocalMediaProfileScope
                onScopeChange(nextScope)
                form.setValue('collectionScope', nextScope, {shouldDirty: true, shouldValidate: true})
                return switchCollectionScope(form, previousScope, nextScope, isCreating)
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
                                    value={field.value ?? 'both'}
                                    isDisabled={locked}
                                    isOptionDisabled={(option) => tracksBlocked && option.value === 'music_tracks'}
                                    components={SCOPE_COMPONENTS}
                                    className="select-with-option-reasons"
                                    {...{disabledOptionReason: TO_TRACKS_REASON}}
                                    onChange={(value) => {
                                        const nextScope = value as CollectionLocalMediaProfileScope
                                        const previousScope = (field.value ?? 'both') as CollectionLocalMediaProfileScope
                                        // Let the defaulting logic read the previous scope before
                                        // updating the form with the new one.
                                        onScopeChange(nextScope)
                                        field.onChange(nextScope)
                                        switchCollectionScope(form, previousScope, nextScope, isCreating)
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
                        <strong>Music tracks</strong> keeps the tracks of Music collections as audio, with the artist,
                        album and track number that music players read. <strong>Music videos</strong> keeps their
                        videos, for a Music Videos library. A profile switches to or from Music tracks only before it
                        has downloads.
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
