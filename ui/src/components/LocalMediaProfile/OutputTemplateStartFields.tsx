import {useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {type UseFormReturn, useWatch} from 'react-hook-form'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../common/SimpleSelect'
import {useLibraryDefaults} from '../../lib/settings'
import {FilenameRestrictionModeReg} from '../../types/local_media_profile'
import {createSelectRegistry} from '../../utils/selectRegistry'
import ReadMore from '../../utils/ReadMore'
import {faIcon} from '../../icons/faIcon'
import type {LocalMediaProfileMode} from './LocalMediaProfileForm'
import {FollowsSettingsSelect} from './FollowsSettings'
import {parseOutputTemplate, renderCompactOutputTemplate} from './outputTemplateFormatting'
import {useRevealFields} from './LocalMediaProfileSection'
import {PRESET_CHOICE_FIELDS, outputTemplatePreset, outputTemplatePresetLabel, outputTemplatePresetRegistry, templateBaseFolder} from './outputTemplatePresets'

/** Which characters file and folder names may hold: the mode in Settings, or the profile's own. */
export function FilenameModeField({form}: {form: UseFormReturn<any>}) {
    const {data: defaults} = useLibraryDefaults()
    const systemFilenameModeLabel = defaults
        ? FilenameRestrictionModeReg.getLabelLoose(defaults.filenameRestrictionMode)
        : 'Loading system setting…'
    const filenameModeReg = createSelectRegistry('LocalMediaProfileFilenameMode', {
        system: {label: `System (${systemFilenameModeLabel})`},
        unrestricted: {label: FilenameRestrictionModeReg.getLabelLoose('unrestricted')},
        windows: {label: FilenameRestrictionModeReg.getLabelLoose('windows')},
        restricted: {label: FilenameRestrictionModeReg.getLabelLoose('restricted')},
    })
    return (
        <FollowsSettingsSelect
            form={form}
            name="filenameRestrictionMode"
            id="mp-filename-restriction-mode"
            label="Filenames"
            registry={filenameModeReg}
            systemLabel={systemFilenameModeLabel}
            help={(
                <ReadMore summary="Choose which characters file and folder names may hold, for the devices that read them.">
                    <p>
                        The modes follow yt-dlp, so new files are named as yt-dlp and Pinchflat name them.
                        <strong> System</strong> uses the mode chosen in Settings. Files you already have keep their
                        names until you rename the profile's files.
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
            )}
        />
    )
}

/**
 * For collections, the media server presets: a choice above the output template. It starts open on a new profile
 * and folded away on one that already has its template.
 */
export default function OutputTemplateStartFields({form, mode, isCreating}: {
    form: UseFormReturn<any>
    mode: LocalMediaProfileMode
    isCreating: boolean
}) {
    const {control, getValues, setValue} = form
    const [presetOpen, setPresetOpen] = useState(isCreating)
    const preferredFormat = useWatch({control, name: 'preferredFormat'})
    const [pendingPreset, setPendingPreset] = useState<string | null>(null)
    const music = useWatch({control, name: 'type'}) === 'music'
    const revealFields = useRevealFields()
    const outputTemplate = useWatch({control, name: 'outputTemplate'}) as string | undefined
    const choiceValues = useWatch({control, name: [...PRESET_CHOICE_FIELDS]}) as unknown[]
    const audioOnly = preferredFormat === 'format_audio_only'

    // The preset shows as chosen while the template and the choices are the ones it writes, also after a reload or
    // on a saved profile. Jellyfin and Kodi write the same template, and only their NFO choices tell them apart.
    const presetRegistry = outputTemplatePresetRegistry(audioOnly, music)
    const chosenPreset = useMemo(() => {
        if (!outputTemplate) return null
        const base = templateBaseFolder(outputTemplate, '/downloads')
        const current: Record<string, unknown> = Object.fromEntries(PRESET_CHOICE_FIELDS.map((name, i) => [name, choiceValues[i]]))
        return presetRegistry.values.find((key) => {
            const preset = outputTemplatePreset(key)
            return !!preset
                && renderCompactOutputTemplate(parseOutputTemplate(preset.template(base), 'editor')) === outputTemplate
                && Object.entries(preset.choices).every(([name, value]) => current[name] === value)
        }) ?? null
    }, [outputTemplate, choiceValues, presetRegistry])

    const applyPreset = (key: string) => {
        const preset = outputTemplatePreset(key)
        if (!preset) return
        const options = {shouldDirty: true, shouldTouch: true, shouldValidate: true}
        const base = templateBaseFolder(getValues('outputTemplate') ?? '', music ? '/downloads/music' : audioOnly ? '/downloads/podcasts' : '/downloads/shows')
        // The presets are written as the editor shows them; the form keeps the compact template.
        const template = renderCompactOutputTemplate(parseOutputTemplate(preset.template(base), 'editor'))
        setValue('outputTemplate', template, options)
        for (const [name, value] of Object.entries(preset.choices)) setValue(name, value, options)
        const indexingValues: {key: string}[] = getValues('indexingValues') ?? []
        if (preset.indexingValue && !indexingValues.some(({key}) => key === preset.indexingValue?.key)) {
            setValue('indexingValues', [...indexingValues, preset.indexingValue], options)
        }
        form.clearErrors('outputTemplate')
        // Many of the Files and metadata choices just changed, so that section opens to show them.
        revealFields(PRESET_CHOICE_FIELDS)
    }

    return (
        <>
            {mode === 'collection' && (
                <div className="form-row output-template-preset">
                    <button
                        type="button"
                        className="output-template-preset-toggle"
                        aria-expanded={presetOpen}
                        aria-controls="mp-output-template-preset-body"
                        onClick={() => setPresetOpen((open) => !open)}
                    >
                        <span>Start from a preset</span>
                        <FontAwesomeIcon icon={faIcon('fass', presetOpen ? 'chevron-up' : 'chevron-down')} aria-hidden="true"/>
                    </button>
                    {presetOpen && (
                        <div id="mp-output-template-preset-body" className="output-template-preset-body">
                            <SimpleSelect
                                inputId="mp-output-template-preset"
                                registry={presetRegistry}
                                value={chosenPreset}
                                placeholder={music ? 'Choose a layout…' : 'Choose a media server…'}
                                onChange={setPendingPreset}
                                aria-describedby="mp-output-template-preset-help"
                            />
                            <div className="help" id="mp-output-template-preset-help">
                                {music ? (
                                    <p>
                                        <strong>Music library</strong>: <code>Artist/Album/01 - Title</code>, which Plex,
                                        Jellyfin, Navidrome and most music players read. You can change any of it afterwards.
                                    </p>
                                ) : <ReadMore summary="Fill in an output template and NFO settings that a media server reads well. You can change any of it afterwards.">
                                    <p>
                                        <strong>Jellyfin and Emby</strong>: <code>Show/Season 01/Show S01E01 Title</code>, with
                                        show and season NFO files.
                                    </p>
                                    <p><strong>Kodi</strong>: like Jellyfin, with NFO files Kodi can read.</p>
                                    {!audioOnly && (
                                        <p>
                                            <strong>Music videos</strong>: <code>Artist/Title</code>, with a musicvideo NFO for a Music
                                            Videos library in Jellyfin, Emby, Kodi or Plex. The artist is the channel's name.
                                        </p>
                                    )}
                                    {audioOnly && (
                                        <p><strong>Audiobookshelf</strong>: <code>Podcast/Date - Title</code>.</p>
                                    )}
                                    <p>
                                        <strong>Plex</strong>: <code>Show/Season 01/Show - S01E01 [Title]</code>. Numbers in a
                                        title, such as 4x4, are written so Plex does not read them as the episode.
                                    </p>
                                    <p>
                                        The template starts in the folder your current template uses. Extras are numbered with
                                        an Indexing Value called <code>extra</code>, which the preset adds when the profile has none.
                                    </p>
                                </ReadMore>}
                            </div>
                        </div>
                    )}
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
                    The {pendingPreset ? outputTemplatePresetLabel(pendingPreset) : ''} preset
                    replaces the output template, and sets the metadata, NFO, file date and While downloading choices of this profile.
                </p>
            </ConfirmDialog>
        </>
    )
}
