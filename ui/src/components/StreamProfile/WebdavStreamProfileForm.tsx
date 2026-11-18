import {Controller, UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import ReadMore from '../../utils/ReadMore'
import SimpleSelect from '../common/SimpleSelect'
import {publicAddress} from '../../lib/api'
import {WebdavMetadataFilesReg, WebdavSeasonFoldersReg} from '../../types/stream_profile'
import type {SelectRegistry} from '../../utils/selectRegistry'
import StreamAddressField from './StreamAddressField'
import StreamDeliveryFields from './StreamDeliveryFields'

type Props = {
    form: UseFormReturn<any>
    isCreating?: boolean
    /** The address of the saved share. */
    sharePath?: string
    onRegenerateToken?: () => void | Promise<void>
    regeneratingToken?: boolean
    siteName?: string
}

/** The settings of a WebDAV share that media players open as a TV show, and its address. */
export default function WebdavStreamProfileForm({
    form,
    isCreating,
    sharePath,
    onRegenerateToken,
    regeneratingToken,
    siteName = 'its site',
}: Props) {
    const {control, formState: {errors}} = form

    return (
        <>
            {([
                ['seasonFolders', 'webdav-season-folders', 'Season folders', WebdavSeasonFoldersReg,
                    'How the episodes are sorted into folders.'],
                ['metadataFiles', 'webdav-metadata-files', 'Metadata files', WebdavMetadataFilesReg,
                    'What the share lists beside the episodes, for media players.'],
            ] as [string, string, string, SelectRegistry, string][]).map(([name, id, label, registry, summary]) => (
                <div className="form-row" key={name}>
                    <label htmlFor={id}>{label}</label>
                    <Controller
                        control={control}
                        name={name}
                        render={({field}) => (
                            <SimpleSelect
                                inputId={id}
                                registry={registry}
                                value={field.value}
                                onChange={field.onChange}
                                onBlur={field.onBlur}
                                aria-invalid={!!errors[name]}
                                aria-describedby={errors[name] ? `${id}-error` : `${id}-help`}
                            />
                        )}
                    />
                    {errors[name] && (
                        <div id={`${id}-error`} className="error" role="alert" aria-live="polite">
                            {String(errors[name]?.message)}
                        </div>
                    )}
                    <div className="help" id={`${id}-help`}>
                        <ReadMore summary={<span>{summary}</span>}>
                            {registry.options.map((option) => (
                                <p key={option.value}>
                                    <strong>{option.label}</strong> {registry.getHelp(option.value)}
                                </p>
                            ))}
                        </ReadMore>
                    </div>
                </div>
            ))}

            <div className="form-row">
                <label htmlFor="webdav-episode-extras">Support episode extras</label>
                <Controller
                    control={control}
                    name="episodeExtras"
                    render={({field}) => (
                        <Switch
                            id="webdav-episode-extras"
                            checked={!!field.value}
                            onChange={(checked) => field.onChange(checked)}
                            onColor="#0ea5e9"
                            offColor="#d1d5db"
                            uncheckedIcon={false}
                            checkedIcon={false}
                            aria-invalid={!!errors.episodeExtras}
                            aria-describedby={errors.episodeExtras ? 'webdav-episode-extras-error' : 'webdav-episode-extras-help'}
                        />
                    )}
                />
                {errors.episodeExtras && (
                    <div id="webdav-episode-extras-error" className="error" role="alert" aria-live="polite">
                        {String(errors.episodeExtras.message)}
                    </div>
                )}
                <div className="help" id="webdav-episode-extras-help">
                    <ReadMore summary={<span>List an episode&apos;s extras, such as its trailer, beside the episode.</span>}>
                        <p>
                            When enabled, an episode&apos;s extras are named after the episode&apos;s file with a suffix such
                            as <code>-trailer1</code> or <code>-other2</code>, so a media player that supports episode extras,
                            such as Plex, shows them with their episode.
                        </p>
                        <p>
                            When disabled, or when the episode itself is not in the share, they go in the show&apos;s
                            Trailers and Other folders, which most media players show as the show&apos;s extras.
                        </p>
                    </ReadMore>
                </div>
            </div>

            <StreamDeliveryFields
                form={form}
                app="media player"
                maxItemsLabel="Maximum episodes in the folder"
                maxItemsHelp={(
                    <ReadMore summary={<span>Only the newest episodes are in the share.</span>}>
                        <p>
                            The share only lists downloaded episodes. Media players seek in a whole file, which they
                            cannot do in a stream.
                        </p>
                        <p>Set to 0 to remove all limits.</p>
                    </ReadMore>
                )}
                offersLiveEpisodes={false}
                proxyChoice={false}
                siteName={siteName}
            />

            {!isCreating && sharePath && (
                <StreamAddressField
                    id="webdav-share-url"
                    label="Share URL"
                    what="share URL"
                    value={publicAddress(sharePath)}
                    onRegenerate={onRegenerateToken}
                    regenerating={regeneratingToken}
                    help={(
                        <ReadMore summary={<span>Add this address as a WebDAV share in Infuse, Kodi, VLC or your file manager.</span>}>
                            <p>
                                The share is read-only and opens without signing in: the address is the key. If an app
                                asks for a user name and password, leave them empty. Windows only connects to a share
                                over HTTPS.
                            </p>
                            <p>
                                Your account page has one share with all your shows. If an address ever leaks,
                                use <strong>Regenerate</strong> to give this share a new one; the old one stops
                                working at once.
                            </p>
                        </ReadMore>
                    )}
                />
            )}
        </>
    )
}
