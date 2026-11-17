import {Controller, type UseFormReturn, useWatch} from 'react-hook-form'

import {useLibraryDefaults} from '../../lib/settings'
import {type LocalMediaProfileType} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {FollowCheck, FollowsSettingsBadge, FollowsSettingsSelect} from './FollowsSettings'

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
    const writesNfo = isBeside(METADATA, effectiveMetadata) || (mode === 'collection' && !!showNfo)
    const fieldErrors = ['thumbnailMode', 'metadataMode', 'kodiSafeNfo', 'showNfo', 'downloadCollectionAssets', 'fileDateFromPublishDate']
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

            {writesNfo && (
                <div className="media-files-checks media-files-checks--indented">
                    <PlainCheck
                        form={form} name="kodiSafeNfo" id="local-media-kodi-safe-nfo" label="Kodi-safe NFO text"
                        description="Replace emoji and other characters Kodi cannot show with □. File names stay as they are."
                    />
                </div>
            )}

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
                                        description="Saved in the collection root that Output path shows. Artwork you added yourself is kept."
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
