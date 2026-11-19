import {useLayoutEffect, useMemo, useRef, useState} from 'react'
import CodeMirror from '@uiw/react-codemirror'
import type {Extension} from '@codemirror/state'
import {EditorView} from '@codemirror/view'
import {Controller, type UseFormReturn, useWatch} from 'react-hook-form'

import {useLibraryDefaults} from '../../lib/settings'
import {EpisodeNfoReg, profileSitesOffering, type LocalMediaProfileType} from '../../types/local_media_profile'
import {useLocalMediaProfileSites} from '../../lib/queries'
import ReadMore from '../../utils/ReadMore'
import SimpleSelect from '../common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {useLocalMediaProfileTemplateVariables} from '../../lib/localMediaProfileTemplateSources'
import {FollowCheck, FollowsSettingsBadge, FollowsSettingsSelect} from './FollowsSettings'
import {useExampleEpisode} from './ExampleEpisodeContext'
import {useJinjaCompletions} from './OutputTemplateEditor'
import {outputTemplateSyntaxExtensions} from './outputTemplateCodeMirror'
import {getOutputTemplateVariables, type OutputTemplateVariable} from './outputTemplateVariables'
import './OutputTemplateEditor.css'

/** A mode that says whether something is saved inside the media, beside it, both or neither. */
type InsideBeside = {none: string, inside: string, beside: string, both: string}
const THUMBNAIL: InsideBeside = {none: 'no_thumbnail', inside: 'embed', beside: 'sidecar', both: 'embed_and_sidecar'}
const METADATA: InsideBeside = {none: 'no_metadata', inside: 'embed', beside: 'nfo', both: 'embed_and_nfo'}

export function isInside(modes: InsideBeside, value: string | undefined): boolean {
    return value === modes.inside || value === modes.both
}

export function isBeside(modes: InsideBeside, value: string | undefined): boolean {
    return value === modes.beside || value === modes.both
}

function combine(modes: InsideBeside, inside: boolean, beside: boolean): string {
    return inside ? (beside ? modes.both : modes.inside) : (beside ? modes.beside : modes.none)
}

/** Whether one of the profile's Sites is downloaded by a program that writes an info file, as yt-dlp does. */
export function useOffersInfoFile(form: UseFormReturn<any>, mode: LocalMediaProfileType): boolean {
    const [siteKeys, includeUpcomingSites] = useWatch({control: form.control, name: ['siteKeys', 'includeUpcomingSites']}) as [string[] | null, boolean]
    const {data: sites} = useLocalMediaProfileSites()
    if (!sites) return false
    const withInfoFile = profileSitesOffering(sites, mode, siteKeys, includeUpcomingSites, (options) => options.infoFile)
    return withInfoFile.sites.length > 0 || withInfoFile.upcoming
}

const DOWNLOAD_MODE_LABELS = {direct: 'Save directly to downloads', temporary: 'Save to temporary folder first'} as const

/** One row of the grid: a mode as two boxes, inside and beside the media, that start from Settings. */
function GridRow({form, name, modes, systemValue, label, description, insideLabel, besideLabel}: {
    form: UseFormReturn<any>
    name: string
    modes: InsideBeside
    systemValue: string | undefined
    label: string
    description: string
    insideLabel: string
    besideLabel: string
}) {
    return (
        <Controller
            control={form.control}
            name={name}
            render={({field}) => {
                const following = (field.value ?? 'system') === 'system'
                const value = following ? systemValue : field.value
                const inside = isInside(modes, value)
                const beside = isBeside(modes, value)
                return (
                    <>
                        <div className="media-files-grid__name">
                            <strong>{label}</strong>
                            <FollowsSettingsBadge
                                following={following}
                                onChoose={() => systemValue && field.onChange(systemValue)}
                                onUseSettings={() => field.onChange('system')}
                            />
                            <span>{description}</span>
                        </div>
                        <div>
                            <FollowCheck
                                id={`mp-${name}-inside`}
                                checked={inside}
                                following={following}
                                disabled={following && !systemValue}
                                onChange={(checked) => field.onChange(combine(modes, checked, beside))}
                                label={<span className="media-files-grid__label">{insideLabel}</span>}
                            />
                        </div>
                        <div>
                            <FollowCheck
                                id={`mp-${name}-beside`}
                                checked={beside}
                                following={following}
                                disabled={following && !systemValue}
                                onChange={(checked) => field.onChange(combine(modes, inside, checked))}
                                label={<span className="media-files-grid__label">{besideLabel}</span>}
                            />
                        </div>
                    </>
                )
            }}
        />
    )
}

function PlainCheck({form, name, id, label, description}: {
    form: UseFormReturn<any>
    name: string
    id: string
    label: string
    description: string
}) {
    return (
        <Controller
            control={form.control}
            name={name}
            render={({field}) => (
                <FollowCheck
                    id={id}
                    checked={!!field.value}
                    following={false}
                    onChange={(checked) => field.onChange(checked)}
                    label={label}
                    description={description}
                />
            )}
        />
    )
}

/**
 * What a profile saves besides the media: thumbnail and metadata inside or beside it, NFO files for the show, artwork
 * in the collection root, file dates, and how a download is written.
 */
export default function MediaFilesFields({form, mode}: {form: UseFormReturn<any>; mode: LocalMediaProfileType}) {
    const {control, formState: {errors}} = form
    const {data: defaults} = useLibraryDefaults()
    const [metadataMode, showNfo] = useWatch({control, name: ['metadataMode', 'showNfo']}) as [string | undefined, boolean | undefined]
    const effectiveMetadata = (metadataMode ?? 'system') === 'system' ? defaults?.metadataMode : metadataMode
    const offersInfoFile = useOffersInfoFile(form, mode)
    const writesNfo = isBeside(METADATA, effectiveMetadata) || (mode === 'collection' && !!showNfo)
    const fieldErrors = ['thumbnailMode', 'metadataMode', 'kodiSafeNfo', 'showNfo', 'downloadCollectionAssets', 'fileDateFromPublishDate', 'saveInfoJson']
        .map((name) => errors[name]?.message)
        .filter(Boolean)

    const downloadModeReg = createSelectRegistry('LocalMediaProfileDownloadMode', {
        system: {label: `System (${defaults ? DOWNLOAD_MODE_LABELS[defaults.downloadMode] : 'Loading system setting…'})`},
        direct: {label: DOWNLOAD_MODE_LABELS.direct},
        temporary: {label: DOWNLOAD_MODE_LABELS.temporary},
    })

    return (
        <>
            <div className="media-files-grid" role="group" aria-label="Saved with each download">
                <div className="media-files-grid__head">Saved with each {mode === 'collection' ? 'episode' : mode}</div>
                <div className="media-files-grid__head">Inside the media</div>
                <div className="media-files-grid__head">Beside the media</div>
                <GridRow
                    form={form} name="thumbnailMode" modes={THUMBNAIL} systemValue={defaults?.thumbnailMode}
                    label="Thumbnail" description="Cover art" insideLabel="Embed" besideLabel="Image file"
                />
                <GridRow
                    form={form} name="metadataMode" modes={METADATA} systemValue={defaults?.metadataMode}
                    label="Metadata" description="Title, date, description" insideLabel="Embed" besideLabel="NFO file"
                />
            </div>

            {writesNfo && mode === 'collection' && (
                <div className="form-row media-files-checks--indented">
                    <label htmlFor="local-media-episode-nfo">Each episode is</label>
                    <Controller
                        control={control}
                        name="episodeNfo"
                        render={({field}) => (
                            <SimpleSelect
                                inputId="local-media-episode-nfo" registry={EpisodeNfoReg} value={field.value ?? 'episode'}
                                onChange={(value) => field.onChange(value)}
                            />
                        )}
                    />
                    <div className="help">
                        Music videos get a musicvideo NFO with the creator's artist, which Jellyfin, Emby and Kodi keep in a Music Videos library.
                    </div>
                    {errors.episodeNfo && <div className="error" role="alert">{String(errors.episodeNfo.message)}</div>}
                </div>
            )}

            {writesNfo && (
                <div className="media-files-checks media-files-checks--indented">
                    <PlainCheck
                        form={form} name="kodiSafeNfo" id="local-media-kodi-safe-nfo" label="Kodi-safe NFO text"
                        description="Replace emoji and other characters Kodi cannot show with □. File names stay as they are."
                    />
                </div>
            )}

            {mode === 'collection' && <MetadataTextFields form={form}/>}

            {mode === 'collection' && (
                <>
                    <div className="media-files-subheading">For the show</div>
                    <div className="media-files-checks">
                        <PlainCheck
                            form={form} name="showNfo" id="local-media-show-nfo" label="Show and season NFO files"
                            description="tvshow.nfo in the collection root and season.nfo in each season folder, for Jellyfin, Emby and Kodi. Plex does not read them."
                        />
                        <Controller
                            control={control}
                            name="downloadCollectionAssets"
                            render={({field}) => {
                                const following = field.value == null
                                const systemEnabled = defaults?.downloadCollectionAssets
                                return (
                                    <FollowCheck
                                        id="mp-collection-assets"
                                        checked={following ? !!systemEnabled : !!field.value}
                                        following={following}
                                        disabled={following && systemEnabled === undefined}
                                        onChange={(checked) => field.onChange(checked)}
                                        label={(
                                            <span className="media-files-check-label">
                                                Poster and background{' '}
                                                <FollowsSettingsBadge
                                                    following={following}
                                                    onChoose={() => systemEnabled !== undefined && field.onChange(systemEnabled)}
                                                    onUseSettings={() => field.onChange(null)}
                                                />
                                            </span>
                                        )}
                                        description="Saved in the collection root that Output path shows, with a poster for each season a playlist fills. Artwork you added yourself is kept."
                                    />
                                )
                            }}
                        />
                    </div>
                </>
            )}

            <div className="media-files-checks">
                <PlainCheck
                    form={form} name="fileDateFromPublishDate" id="local-media-file-date" label="Date files by publish date"
                    description="So players and file browsers sort episodes in the order they aired. An old episode you download today then does not show up under Recently added."
                />
                {offersInfoFile && (
                    <PlainCheck
                        form={form} name="saveInfoJson" id="local-media-info-json" label="Save the site's info file"
                        description="Everything yt-dlp knows about the video, as an .info.json file beside the media, for other programs that read it. Only for sites VODLoft downloads with yt-dlp."
                    />
                )}
            </div>

            {fieldErrors.map((message) => (
                <div key={String(message)} className="error" role="alert" aria-live="polite">{String(message)}</div>
            ))}

            <FollowsSettingsSelect
                form={form}
                name="downloadMode"
                id="local-media-download-mode"
                label="While downloading"
                registry={downloadModeReg}
                systemLabel={defaults ? DOWNLOAD_MODE_LABELS[defaults.downloadMode] : 'Loading system setting…'}
                help={(
                    <ReadMore summary="Where a download is written until it is complete.">
                        <p>
                            <strong>Save directly to downloads</strong> writes download temporary files beside the final media
                            destination and reserves the final filename while downloading.
                        </p>
                        <p>
                            <strong>Save to temporary folder first</strong> keeps download and processing files in the configured
                            temporary folder and only publishes the completed media file at the end. This is useful when a media
                            server watches the destination and should not pick up partly downloaded files.
                        </p>
                        <p>Saving directly is a little faster. If errors happen in either mode, VODLoft restores from them.</p>
                    </ReadMore>
                )}
            />
        </>
    )
}


const METADATA_VARIABLES: readonly OutputTemplateVariable[] = [
    {name: 'description', description: "The episode's description as the site gives it"},
]

const metadataEditorExtensions = [
    ...outputTemplateSyntaxExtensions,
    EditorView.lineWrapping,
    EditorView.theme({
        '&': {fontSize: '16px'},
        '.cm-content': {fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace'},
    }),
]

/** A Jinja template with the output path editor's colours and completions, empty when it keeps the site's text. */
function MetadataTemplateEditor({form, name, id, label, placeholder, completions, multiline}: {
    form: UseFormReturn<any>
    name: 'episodeTitleTemplate' | 'episodeDescriptionTemplate'
    id: string
    label: string
    placeholder: string
    completions: Extension[]
    multiline: boolean
}) {
    const extensions = useMemo(() => [...metadataEditorExtensions, ...completions], [completions])
    const error = form.formState.errors[name]
    return (
        <Controller
            control={form.control}
            name={name}
            render={({field}) => (
                <CodeMirror
                    id={id}
                    className={`output-template-code-editor metadata-template-editor${multiline ? ' metadata-template-editor--multiline' : ''}`}
                    value={field.value ?? ''}
                    placeholder={placeholder}
                    extensions={extensions}
                    basicSetup={{
                        lineNumbers: false,
                        foldGutter: false,
                        highlightActiveLine: false,
                        highlightActiveLineGutter: false,
                        autocompletion: false,
                    }}
                    onChange={(value) => {
                        field.onChange(value.trim() === '' ? null : value)
                        form.clearErrors(name)
                    }}
                    onBlur={field.onBlur}
                    aria-label={label}
                    aria-invalid={!!error}
                    aria-describedby={`${id}-example`}
                />
            )}
        />
    )
}

/** Text cut at four lines, with Read more when there is more, as a long YouTube description has. */
function ClampedText({text, multiline}: {text: string, multiline: boolean}) {
    const ref = useRef<HTMLSpanElement>(null)
    const [expanded, setExpanded] = useState(false)
    const [overflows, setOverflows] = useState(false)
    useLayoutEffect(() => {
        const element = ref.current
        if (!element) return
        // Measured while cut, and again whenever the box changes width.
        const measure = () => setOverflows(element.classList.contains('metadata-template-example__text--clamped')
            ? element.scrollHeight > element.clientHeight + 1
            : true)
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(element)
        return () => observer.disconnect()
    }, [text, expanded])
    return (
        <>
            <span
                ref={ref}
                className={[
                    multiline ? 'metadata-template-example__text--multiline' : '',
                    expanded ? '' : 'metadata-template-example__text--clamped',
                ].filter(Boolean).join(' ') || undefined}
            >
                {text}
            </span>
            {overflows && (
                <button type="button" className="metadata-template-example__more" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
                    {expanded ? 'Show less' : 'Read more'}
                </button>
            )}
        </>
    )
}

/** What the template gives the example episode, or why it can't render. */
function MetadataExample({id, text, error, loading, multiline}: {
    id: string
    text: string | undefined
    error: string | null | undefined
    loading: boolean
    multiline: boolean
}) {
    return (
        <div id={id} className={`template-preview-output metadata-template-example${error ? ' has-error' : ''}`} aria-live="polite">
            <span className="template-preview-output-label">Example output</span>
            {error
                ? <span className="error">{error}</span>
                : text === undefined
                    ? <code>{loading ? 'Rendering…' : 'Pick an example episode under Output path.'}</code>
                    : text
                        ? <ClampedText text={text} multiline={multiline}/>
                        : <code>The site gives this episode none.</code>}
        </div>
    )
}

/** An episode's own title and description in its NFO and embedded metadata, as Jinja templates. */
function MetadataTextFields({form}: {form: UseFormReturn<any>}) {
    const {formState: {errors}} = form
    const variableQuery = useLocalMediaProfileTemplateVariables('collection')
    const variables = useMemo(
        () => [...getOutputTemplateVariables('collection', (variableQuery.data ?? []) as OutputTemplateVariable[]), ...METADATA_VARIABLES],
        [variableQuery.data],
    )
    const completions = useJinjaCompletions(variables, false)
    const example = useExampleEpisode()
    const metadata = example.metadata
    return (
        <>
            <div className="media-files-subheading">Title and description in the metadata</div>
            <div className="form-row">
                <label htmlFor="local-media-title-template">Title</label>
                <MetadataTemplateEditor
                    form={form} name="episodeTitleTemplate" id="local-media-title-template" label="Title"
                    placeholder="{{ title }}" completions={completions} multiline={false}
                />
                {errors.episodeTitleTemplate && <div className="error" role="alert">{String(errors.episodeTitleTemplate.message)}</div>}
                <MetadataExample
                    id="local-media-title-template-example" text={metadata?.title} error={metadata?.titleError}
                    loading={example.loading} multiline={false}
                />
            </div>
            <div className="form-row">
                <label htmlFor="local-media-description-template">Description</label>
                <MetadataTemplateEditor
                    form={form} name="episodeDescriptionTemplate" id="local-media-description-template" label="Description"
                    placeholder="{{ description }}" completions={completions} multiline
                />
                {errors.episodeDescriptionTemplate && <div className="error" role="alert">{String(errors.episodeDescriptionTemplate.message)}</div>}
                <MetadataExample
                    id="local-media-description-template-example" text={metadata?.description} error={metadata?.descriptionError}
                    loading={example.loading} multiline
                />
                <div className="help">
                    {example.label && <p className="metadata-template-example-source">The examples are for {example.label}, the example episode under Output path.</p>}
                    <ReadMore summary="{{ title }} and {{ description }} are the title and description the site gives each episode.">
                        <p>They take the same variables as the output path, such as <code>{'{{ title }}'}</code> and <code>{'{{ date }}'}</code>,
                            and <code>{'{{ description }}'}</code> for the site's description. Type <code>{'{{'}</code> to pick one.
                            A field you leave empty keeps the site's text too.
                            {' '}<code>{'{{ date }} - {{ title }}'}</code> puts the date before each title, as ytdl-sub does.
                            They change the NFO file and the title inside the media, not the file name.</p>
                    </ReadMore>
                </div>
            </div>
        </>
    )
}
