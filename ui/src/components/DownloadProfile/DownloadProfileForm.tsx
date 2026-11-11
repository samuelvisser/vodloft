import {useEffect, useRef} from 'react'
import {Controller, UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import ReadMore from '../../utils/ReadMore'
import {useCollectionEpisodeTags, useSiteOptions} from "../../lib/queries";
import type {SeasonDetachedOut} from "../../types/schemas/season";
import WhichEpisodes from "./WhichEpisodes";
import UpgradeCheckCard from "./UpgradeCheckCard";

type Props = {
    form: UseFormReturn<any>
    /** How the collection identifies its episodes. Unknown until a collection is chosen. */
    episodeIdentifier?: string
    /** The collection's seasons, oldest first. */
    seasons?: readonly SeasonDetachedOut[]
    collectionRoot?: boolean
    /** The saved collection the profile is for. */
    collectionId?: number
    /** The Source of a collection that is not saved yet. */
    sourceKey?: string
    /** The link of a collection that is not saved yet, which decides the tags its episodes can get. */
    collectionUrl?: string
    /** The profile is not saved yet, so it starts with what its collection's Site suggests. */
    newProfile?: boolean
}

export default function DownloadProfileForm({form, episodeIdentifier, seasons, collectionRoot, collectionId, sourceKey, collectionUrl, newProfile}: Props) {
    const {control, formState: {errors}} = form
    collectionRoot ??= true

    const {data: tags} = useCollectionEpisodeTags({collectionId, sourceKey, url: collectionUrl})
    const {data: site} = useSiteOptions({collectionId, sourceKey, url: collectionUrl})

    // A new profile starts with what its Site's settings say, once per Site, leaving what the user already changed.
    const startedFor = useRef<string | null>(null)
    useEffect(() => {
        if (!newProfile || !site || startedFor.current === site.siteName) return
        startedFor.current = site.siteName
        for (const [name, value] of Object.entries(site.profileDefaults)) {
            if (!form.getFieldState(name).isDirty) form.setValue(name, structuredClone(value))
        }
    }, [newProfile, site, form])

    return (
        <>
            {collectionRoot && errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}

            {/* Enable automatic downloads */}
            <div className="form-row">
                <label htmlFor="enable-profile">Enable automatic downloads</label>
                <Controller
                    control={control}
                    name="enableProfile"
                    render={({field}) => (
                        <Switch
                            id="enable-profile"
                            checked={!!field.value}
                            onChange={(checked) => field.onChange(checked)}
                            onColor="#0ea5e9"
                            offColor="#d1d5db"
                            uncheckedIcon={false}
                            checkedIcon={false}
                            aria-invalid={!!errors.enableProfile}
                            aria-describedby={errors.enableProfile ? 'enable-profile-errors' : 'enable-profile-help'}
                        />
                    )}
                />
                {errors.enableProfile && (
                    <div id="enable-profile-errors" className="error" role="alert" aria-live="polite">
                        {errors.enableProfile.message as string}
                    </div>
                )}
                <div className="help" id="enable-profile-help">
                    <ReadMore summary={<span>Whether to automatically download episodes</span>}>
                        If you disable the download profile, the collection will still be indexed and you can still manually
                        download episodes in the collection.
                    </ReadMore>
                </div>
            </div>

            <WhichEpisodes
                form={form}
                episodeIdentifier={episodeIdentifier}
                tags={tags}
                seasons={seasons ?? []}
                collectionId={collectionId}
            />
            <UpgradeCheckCard form={form} collectionId={collectionId} sourceKey={sourceKey} collectionUrl={collectionUrl}/>
        </>
    )
}
