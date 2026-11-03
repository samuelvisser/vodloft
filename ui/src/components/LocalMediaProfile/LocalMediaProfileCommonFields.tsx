import {Controller, UseFormReturn} from 'react-hook-form'

import {type LocalMediaProfileType} from '../../types/local_media_profile'
import CollectionLocalMediaProfileScopeField from './CollectionLocalMediaProfileScopeField'
import SubtitleLines from './SubtitleLines'
import {useSubtitleModeDefaults} from './useSubtitleModeDefaults'

import {useLibraryDefaults} from '../../lib/settings'
import ReadMore from '../../utils/ReadMore'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import OptionsEditor from '../common/OptionsEditor/OptionsEditor'

// Where the Local Media Profile's own settings are, for options that would repeat them.
const SETTING_LINKS = {
    quality: {label: 'Quality', elementId: 'quality-up-to'},
    subtitles: {label: 'Subtitles', elementId: 'subtitle-lines'},
    thumbnails: {label: 'Episode thumbnail behavior', elementId: 'local-media-thumbnail-mode'},
    metadata: {label: 'Media metadata behavior', elementId: 'local-media-metadata-mode'},
    file_names: {label: 'the output template’s file names', elementId: 'mp-path-help'},
}

const THUMBNAIL_MODE_LABELS = {
    no_thumbnail: 'No thumbnail',
    embed: 'Embed in media',
    sidecar: 'Download besides media',
    embed_and_sidecar: 'Both embed and download',
} as const

const METADATA_MODE_LABELS = {
    no_metadata: 'No metadata',
    embed: 'Embed in media',
    nfo: 'Download as NFO',
    embed_and_nfo: 'Both embed and download',
} as const

export default function LocalMediaProfileCommonFields({
    form, mode, isCreating,
}: {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
    isCreating: boolean
}) {
    const {control, register, formState: {errors}} = form
    const {onSubtitleModeChange, onScopeChange} = useSubtitleModeDefaults(form, mode, isCreating)
    const {data: defaults} = useLibraryDefaults()
    const systemDownloadModeLabel = !defaults
        ? 'Loading system setting…'
        : defaults.downloadMode === 'temporary'
            ? 'Save to temporary folder first'
            : 'Save directly to downloads'
    const systemThumbnailModeLabel = !defaults
        ? 'Loading system setting…'
        : THUMBNAIL_MODE_LABELS[defaults.thumbnailMode]
    const systemMetadataModeLabel = !defaults
        ? 'Loading system setting…'
        : METADATA_MODE_LABELS[defaults.metadataMode]

    const downloadModeReg = createSelectRegistry('LocalMediaProfileDownloadMode', {
        system: {label: `System (${systemDownloadModeLabel})`},
        direct: {label: 'Save directly to downloads'},
        temporary: {label: 'Save to temporary folder first'},
    })
    const thumbnailModeReg = createSelectRegistry('LocalMediaProfileThumbnailMode', {
        system: {label: `System (${systemThumbnailModeLabel})`},
        no_thumbnail: {label: 'No thumbnail'},
        embed: {label: 'Embed in media'},
        sidecar: {label: 'Download besides media'},
        embed_and_sidecar: {label: 'Both embed and download'},
    })
    const metadataModeReg = createSelectRegistry('LocalMediaProfileMetadataMode', {
        system: {label: `System (${systemMetadataModeLabel})`},
        no_metadata: {label: 'No metadata'},
        embed: {label: 'Embed in media'},
        nfo: {label: 'Download as NFO'},
        embed_and_nfo: {label: 'Both embed and download'},
    })

    return (
        <>
            {errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}

            {/* Hidden fields for id and slug to include them in submit when present */}
            <input type="hidden" {...register('id', {setValueAs: (v) => (v === '' || v == null ? undefined : Number(v))})} />
            <input type="hidden" {...register('slug')} />
            <input type="hidden" {...register('type')} />

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

            {mode === 'collection' && (
                <CollectionLocalMediaProfileScopeField
                    form={form}
                    onScopeChange={onScopeChange}
                    isCreating={isCreating}
                />
            )}

            <div className="form-row">
                <label htmlFor="local-media-download-mode">Download behavior</label>
                <Controller
                    control={control}
                    name="downloadMode"
                    render={({field}) => (
                        <SimpleSelect
                            inputId="local-media-download-mode"
                            registry={downloadModeReg}
                            value={field.value ?? 'system'}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            aria-invalid={!!errors.downloadMode}
                            aria-describedby={errors.downloadMode ? 'local-media-download-mode-errors' : 'local-media-download-mode-help'}
                        />
                    )}
                />
                {errors.downloadMode && (
                    <div id="local-media-download-mode-errors" className="error" role="alert" aria-live="polite">
                        {errors.downloadMode.message as string}
                    </div>
                )}
                <div className="help" id="local-media-download-mode-help">
                    <ReadMore summary="Choose whether incomplete downloads are written in their destination or staged elsewhere first.">
                        <p>
                            <strong>System</strong> follows the current system-wide default.
                        </p>
                        <p>
                            <strong>Save directly to downloads</strong> writes download temporary files beside the final media destination and reserves the final filename while downloading.
                        </p>
                        <p>
                            <strong>Save to temporary folder first</strong> keeps download and processing files in the configured temporary folder and only publishes the completed media file at the end.
                        </p>
                        <p>
                            Temporary mode is particularly useful when the destination is watched by a media server and you do not want it to pick up partly downloaded or empty media files.
                            Save directly to downloads, due to its simple nature, is a little faster and less prone to errors. Though if errors do happen in either mode, VODLoft will
                            automatically restore from them.
                        </p>
                    </ReadMore>
                </div>
            </div>

            <div className="form-row">
                <label htmlFor="local-media-thumbnail-mode">Episode thumbnail behavior</label>
                <Controller
                    control={control}
                    name="thumbnailMode"
                    render={({field}) => (
                        <SimpleSelect
                            inputId="local-media-thumbnail-mode"
                            registry={thumbnailModeReg}
                            value={field.value ?? 'system'}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            aria-invalid={!!errors.thumbnailMode}
                            aria-describedby={errors.thumbnailMode ? 'local-media-thumbnail-mode-errors' : 'local-media-thumbnail-mode-help'}
                        />
                    )}
                />
                {errors.thumbnailMode && (
                    <div id="local-media-thumbnail-mode-errors" className="error" role="alert" aria-live="polite">
                        {errors.thumbnailMode.message as string}
                    </div>
                )}
                <div className="help" id="local-media-thumbnail-mode-help">
                    <ReadMore summary="Choose how this profile stores the source's thumbnail for downloaded media.">
                        <p><strong>System</strong> follows the current system-wide default.</p>
                        <p><strong>No thumbnail</strong> keeps downloads media-only.</p>
                        <p><strong>Embed in media</strong> stores the thumbnail as cover artwork inside the downloaded media file.</p>
                        <p><strong>Download besides media</strong> saves the thumbnail as an image alongside the media file.</p>
                        <p><strong>Both embed and download</strong> does both.</p>
                    </ReadMore>
                </div>
            </div>

            <div className="form-row">
                <label htmlFor="local-media-metadata-mode">Media metadata behavior</label>
                <Controller
                    control={control}
                    name="metadataMode"
                    render={({field}) => (
                        <SimpleSelect
                            inputId="local-media-metadata-mode"
                            registry={metadataModeReg}
                            value={field.value ?? 'system'}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            aria-invalid={!!errors.metadataMode}
                            aria-describedby={errors.metadataMode ? 'local-media-metadata-mode-errors' : 'local-media-metadata-mode-help'}
                        />
                    )}
                />
                {errors.metadataMode && (
                    <div id="local-media-metadata-mode-errors" className="error" role="alert" aria-live="polite">
                        {String(errors.metadataMode.message)}
                    </div>
                )}
                <div className="help" id="local-media-metadata-mode-help">
                    <ReadMore summary="Choose how this profile stores metadata for downloaded media.">
                        <p><strong>System</strong> follows the current system-wide default.</p>
                        <p><strong>No metadata</strong> leaves the downloaded media without VODLoft-generated metadata.</p>
                        <p><strong>Embed in media</strong> writes useful media-server metadata directly into supported media containers.</p>
                        <p><strong>Download as NFO</strong> writes the same metadata in a same-basename NFO file beside the media.</p>
                        <p><strong>Both embed and download</strong> does both.</p>
                        <p>HLS bundles cannot contain embedded file metadata, so only the NFO part applies when selected.</p>
                    </ReadMore>
                </div>
            </div>

            <SubtitleLines form={form} onSubtitleModeChange={onSubtitleModeChange}/>

            {mode !== 'movie' && (
                <div className="form-row">
                    <label htmlFor="local-media-ytdlp-options">Your own yt-dlp options</label>
                    <Controller
                        control={control}
                        name="ytdlpOptions"
                        render={({field}) => (
                            <OptionsEditor
                                id="local-media-ytdlp-options"
                                value={field.value ?? ''}
                                onChange={field.onChange}
                                onBlur={field.onBlur}
                                invalid={!!errors.ytdlpOptions}
                                describedBy={errors.ytdlpOptions ? 'local-media-ytdlp-options-errors' : 'local-media-ytdlp-options-help'}
                                settingLinks={SETTING_LINKS}
                            />
                        )}
                    />
                    {errors.ytdlpOptions && (
                        <div id="local-media-ytdlp-options-errors" className="error" role="alert" aria-live="polite">
                            {String(errors.ytdlpOptions.message)}
                        </div>
                    )}
                    <div className="help" id="local-media-ytdlp-options-help">
                        <ReadMore summary="Extra options for downloads yt-dlp makes, such as YouTube’s. Most people leave this empty.">
                            <p>Write options the way yt-dlp’s own option files have them: one or more per line, and lines starting with # are notes.
                                Each line is checked with yt-dlp’s own parser as you type.</p>
                            <p>A few options are <strong>blocked</strong>, with the reason: the ones that would change where files go or what they are called
                                (such as <code>-o</code> and <code>-P</code>), pick the format past the Quality setting (<code>-f</code>), or run other programs (<code>--exec</code>).
                                Options VODLoft already has a setting for point to that setting instead.</p>
                            <p>A Collection can add its own options on top of these, on its Edit page. They only apply to Collections and videos from the yt-dlp Source, not to The Daily Wire or NPO Start.</p>
                        </ReadMore>
                    </div>
                </div>
            )}
        </>
    )
}
