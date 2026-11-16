import type {ReactNode} from 'react'
import {Controller, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'

import {type LocalMediaProfileType} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'

function SwitchField({form, name, id, label, summary, children}: {
    form: UseFormReturn<any>
    name: string
    id: string
    label: string
    summary: ReactNode
    children: ReactNode
}) {
    const {control, formState: {errors}} = form
    const error = errors[name]
    return (
        <div className="form-row">
            <label htmlFor={id}>{label}</label>
            <Controller
                control={control}
                name={name}
                render={({field}) => (
                    <Switch
                        id={id}
                        checked={!!field.value}
                        onChange={(checked) => field.onChange(checked)}
                        onColor="#0ea5e9"
                        offColor="#d1d5db"
                        uncheckedIcon={false}
                        checkedIcon={false}
                        aria-invalid={!!error}
                        aria-describedby={error ? `${id}-error` : `${id}-help`}
                    />
                )}
            />
            {error && (
                <div id={`${id}-error`} className="error" role="alert" aria-live="polite">
                    {String(error.message)}
                </div>
            )}
            <div className="help" id={`${id}-help`}>
                <ReadMore summary={summary}>{children}</ReadMore>
            </div>
        </div>
    )
}

/** What a profile writes for media servers besides the media: show and season NFO files, and file dates. */
export default function MediaServerFileFields({form, mode}: { form: UseFormReturn<any>, mode: LocalMediaProfileType }) {
    return (
        <>
            {mode === 'collection' && (
                <SwitchField
                    form={form}
                    name="showNfo"
                    id="local-media-show-nfo"
                    label="Show and season NFO files"
                    summary="Write tvshow.nfo in the collection's folder and season.nfo in each season's folder."
                >
                    <p>
                        Jellyfin, Emby and Kodi read these files for the show's title, description and studio, and for
                        the name of each season, so a show looks right without the media server looking it up online.
                        Plex does not read NFO files.
                    </p>
                    <p>
                        A season gets a season.nfo when its episodes have a folder of their own, such as
                        <code> Season 01</code>. An NFO file you made or edited yourself is left as it is.
                    </p>
                </SwitchField>
            )}
            <SwitchField
                form={form}
                name="kodiSafeNfo"
                id="local-media-kodi-safe-nfo"
                label="Kodi-safe NFO files"
                summary="Replace emoji and other characters Kodi cannot show with □ inside NFO files."
            >
                <p>
                    Kodi's fonts cannot show emoji, so a title with one shows empty boxes or stops short. This only
                    changes the text inside the NFO files VODLoft writes; file names stay as they are.
                </p>
            </SwitchField>
            <SwitchField
                form={form}
                name="fileDateFromPublishDate"
                id="local-media-file-date"
                label="Date files by publish date"
                summary="Give each downloaded file the date it was published, instead of the date it was downloaded."
            >
                <p>
                    Players and file browsers that sort by date then show episodes in the order they aired, also when
                    older episodes were downloaded later. It applies to files downloaded from now on.
                </p>
                <p>
                    Some media servers use the file date for "Recently added". With this on, an old episode you
                    download today does not show up there.
                </p>
            </SwitchField>
        </>
    )
}
