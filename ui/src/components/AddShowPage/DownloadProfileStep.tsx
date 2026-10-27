import {useEffect, useMemo} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {ChosenShowCard} from './ShowPreviewCard'
import DownloadProfileForm from '../DownloadProfile/DownloadProfileForm'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import type {ShowCreatePayloadOut} from '../../types/schemas/show'
import {
    DownloadProfileBundleIn, DownloadProfileBundleOut, DownloadProfileBundleSchema
} from "../../types/schemas/show_as_bundle";
import {forEpisodeIdentifier} from "../../types/schemas/download_profile";
import {SeasonDetachedOut} from "../../types/schemas/season";
import {EpisodeIdentifierReg} from "../../types/show";


type Props = {
    value: Partial<DownloadProfileBundleIn>
    onChange: (v: Partial<DownloadProfileBundleIn>) => void
    onSubmit: (v: DownloadProfileBundleOut) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    /** The show chosen in the first step. */
    show?: ShowCreatePayloadOut
    seasons: SeasonDetachedOut[]
    continueLabel?: string
}

export default function DownloadProfileStep({value, onChange, onSubmit: onSubmitParent, onBack, onContinue, onCancel, show, seasons, continueLabel = 'Continue'}: Props) {
    const episodeIdentifier = show?.episodeIdentifier
    const isSeasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal

    // Until the user picks seasons, a seasonal show starts with its latest season.
    const latestSeason = seasons.length > 0 ? seasons[seasons.length - 1] : undefined
    const defaultValues: Partial<DownloadProfileBundleIn> = {
        ...value,
        seasons: !isSeasonal
            ? []
            : value.seasons === undefined
                ? (latestSeason ? [latestSeason] : [])
                : value.seasons,
    }

    const schema = useMemo(
        () => forEpisodeIdentifier(DownloadProfileBundleSchema, episodeIdentifier),
        [episodeIdentifier],
    )
    const form = useForm<DownloadProfileBundleIn>({
        resolver: zodResolver(schema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues,
    })
    const {watch, setValue} = form

    // Subscribe to ALL changes
    useEffect(() => {
        const subscription = watch((values) => {
            onChange(values as any); // push up on every change
        });
        return () => subscription.unsubscribe();
    }, [watch, onChange]);

    // If countdown is disabled, redownload final becomes irrelevant and is hidden
    const withCountdown = watch('downloadWithCountdown')
    useEffect(() => {
        if (!withCountdown) {
            setValue('redownloadFinal', true, {shouldDirty: true, shouldValidate: false})
        }
    }, [withCountdown, setValue])

    const onSubmit = buildServerAwareSubmit(form, async (dataOut: DownloadProfileBundleOut) => {
        onSubmitParent(dataOut)
        onContinue()
    })

    return (
        <div className="wizard-with-aside">
            <div className="wizard-main">
                <form className="form form-fluid" onSubmit={onSubmit} noValidate>
                    <DownloadProfileForm
                        form={form}
                        episodeIdentifier={episodeIdentifier}
                        seasons={seasons}
                        sourceKey={show?.sourceKey}
                        showUrl={show?.sharingUrl}
                    />

                    <div className="actions">
                        <button type="button" className="btn" onClick={onBack}>Back</button>
                        <input type="submit" className="btn btn-primary" value={continueLabel} />
                        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    </div>
                </form>
            </div>

            {show ? (
                <aside className="wizard-aside" aria-label="Selected show details">
                    <ChosenShowCard show={show}/>
                </aside>
            ) : null}
        </div>
    )
}
