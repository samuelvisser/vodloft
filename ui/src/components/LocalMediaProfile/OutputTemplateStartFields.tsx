import {useState} from 'react'
import {Controller, type UseFormReturn, useWatch} from 'react-hook-form'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../common/SimpleSelect'
import {FilenameRestrictionModeReg} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'
import type {LocalMediaProfileMode} from './LocalMediaProfileForm'
import {parseOutputTemplate, renderCompactOutputTemplate} from './outputTemplateFormatting'
import {outputTemplatePreset, outputTemplatePresetRegistry, templateBaseFolder} from './outputTemplatePresets'

/** The filename mode and, for collections, the media server presets: the choices above the output template. */
export default function OutputTemplateStartFields({form, mode}: { form: UseFormReturn<any>, mode: LocalMediaProfileMode }) {
    const {control, getValues, setValue, formState: {errors}} = form
    const preferredFormat = useWatch({control, name: 'preferredFormat'})
    const [pendingPreset, setPendingPreset] = useState<string | null>(null)
    const audioOnly = preferredFormat === 'format_audio_only'

    const applyPreset = (key: string) => {
        const preset = outputTemplatePreset(key)
        if (!preset) return
        const options = {shouldDirty: true, shouldTouch: true, shouldValidate: true}
        const base = templateBaseFolder(getValues('outputTemplate') ?? '', audioOnly ? '/downloads/podcasts' : '/downloads/shows')
        // The presets are written as the editor shows them; the form keeps the compact template.
        setValue('outputTemplate', renderCompactOutputTemplate(parseOutputTemplate(preset.template(base), 'editor')), options)
        for (const [name, value] of Object.entries(preset.choices)) setValue(name, value, options)
        const indexingValues: {key: string}[] = getValues('indexingValues') ?? []
        if (preset.indexingValue && !indexingValues.some(({key}) => key === preset.indexingValue?.key)) {
            setValue('indexingValues', [...indexingValues, preset.indexingValue], options)
        }
        form.clearErrors('outputTemplate')
    }

    return (
        <>
            <div className="form-row">
                <label htmlFor="mp-filename-restriction-mode">Filename restrictions</label>
                <Controller
                    control={control}
                    name="filenameRestrictionMode"
                    render={({field}) => (
                        <SimpleSelect
                            inputId="mp-filename-restriction-mode"
                            registry={FilenameRestrictionModeReg}
                            value={field.value ?? null}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            aria-invalid={!!errors.filenameRestrictionMode}
                            aria-describedby={errors.filenameRestrictionMode ? 'mp-filename-restriction-mode-error' : 'mp-filename-restriction-mode-help'}
                        />
                    )}
                />
                {errors.filenameRestrictionMode && (
                    <div id="mp-filename-restriction-mode-error" className="error" role="alert" aria-live="polite">
                        {String(errors.filenameRestrictionMode.message)}
                    </div>
                )}
                <div className="help" id="mp-filename-restriction-mode-help">
                    <ReadMore summary="Choose which characters file and folder names may hold, for the devices that read them.">
                        <p>
                            The modes follow yt-dlp, so new files are named as yt-dlp and Pinchflat name them. A new
                            profile starts with the mode chosen in Settings. Files you already have keep their names
                            until you rename the profile's files.
                        </p>
                        <p>
                            <strong>Minimal restrictions</strong> preserves Unicode and punctuation. Only a <code>/</code> in
                            a value changes, to <code>⧸</code>.
                        </p>
                        <p>
                            <strong>Windows-compatible</strong> turns characters Windows does not allow into look-alikes,
                            such as <code>：</code> for <code>:</code>, and keeps reserved names from being used.
                            Unicode is preserved. Choose it for a library on a Windows computer or a network share.
                        </p>
                        <p>
                            <strong>Restricted</strong> uses ASCII-only names without spaces or ampersands, for a car
                            stereo or an older player. A name with nothing ASCII left becomes <code>no_ascii_file_name</code>.
                        </p>
                    </ReadMore>
                </div>
            </div>

            {mode === 'collection' && (
                <div className="form-row">
                    <label htmlFor="mp-output-template-preset">Start from a preset</label>
                    <SimpleSelect
                        inputId="mp-output-template-preset"
                        registry={outputTemplatePresetRegistry(audioOnly)}
                        value={null}
                        placeholder="Choose a media server…"
                        onChange={setPendingPreset}
                        aria-describedby="mp-output-template-preset-help"
                    />
                    <div className="help" id="mp-output-template-preset-help">
                        <ReadMore summary="Fill in an output template and NFO settings that a media server reads well. You can change any of it afterwards.">
                            <p>
                                <strong>Plex</strong>: <code>Show/Season 01/Show - S01E01 [Title]</code>. Numbers in a
                                title, such as 4x4, are written so Plex does not read them as the episode.
                            </p>
                            <p>
                                <strong>Jellyfin and Emby</strong>: <code>Show/Season 01/Show S01E01 Title</code>, with
                                show and season NFO files.
                            </p>
                            <p><strong>Kodi</strong>: like Jellyfin, with NFO files Kodi can read.</p>
                            {audioOnly && (
                                <p><strong>Audiobookshelf</strong>: <code>Podcast/Date - Title</code>.</p>
                            )}
                            <p>
                                The template starts in the folder your current template uses. Extras are numbered with
                                an Indexing Value called <code>extra</code>, which the preset adds when the profile has none.
                            </p>
                        </ReadMore>
                    </div>
                </div>
            )}

            <ConfirmDialog
                open={pendingPreset !== null}
                title="Replace the output template?"
                onDismiss={() => setPendingPreset(null)}
                cancelButton={{label: 'Keep my template', onClick: () => setPendingPreset(null)}}
                confirmButton={{
                    label: 'Use the preset',
                    onClick: () => {
                        if (pendingPreset) applyPreset(pendingPreset)
                        setPendingPreset(null)
                    },
                }}
            >
                <p>
                    The {pendingPreset ? outputTemplatePresetRegistry(true).getLabelLoose(pendingPreset) : ''} preset
                    replaces the output template, and sets the metadata, NFO and file date choices of this profile.
                </p>
            </ConfirmDialog>
        </>
    )
}
