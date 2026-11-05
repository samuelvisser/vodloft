import {useEffect} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {ChosenCollectionCard} from './CollectionPreviewCard'
import DownloadProfileForm from '../DownloadProfile/DownloadProfileForm'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import type {CollectionCreatePayloadOut} from '../../types/schemas/collection'
import {
    DownloadProfileBundleIn, DownloadProfileBundleOut, DownloadProfileBundleSchema
} from "../../types/schemas/collection_as_bundle";
import {SeasonDetachedOut} from "../../types/schemas/season";


type Props = {
    value: Partial<DownloadProfileBundleIn>
    onChange: (v: Partial<DownloadProfileBundleIn>) => void
    onSubmit: (v: DownloadProfileBundleOut) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    /** The collection chosen in the first step. */
    collection?: CollectionCreatePayloadOut
    seasons: SeasonDetachedOut[]
    continueLabel?: string
}

export default function DownloadProfileStep({value, onChange, onSubmit: onSubmitParent, onBack, onContinue, onCancel, collection, seasons, continueLabel = 'Continue'}: Props) {
    const episodeIdentifier = collection?.episodeIdentifier

    const form = useForm<DownloadProfileBundleIn>({
        resolver: zodResolver(DownloadProfileBundleSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: value,
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
                        sourceKey={collection?.sourceKey}
                        collectionUrl={collection?.sharingUrl}
                        newProfile
                    />

                    <div className="actions">
                        <button type="button" className="btn" onClick={onBack}>Back</button>
                        <input type="submit" className="btn btn-primary" value={continueLabel} />
                        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
                    </div>
                </form>
            </div>

            {collection ? (
                <aside className="wizard-aside" aria-label="Selected collection details">
                    <ChosenCollectionCard collection={collection}/>
                </aside>
            ) : null}
        </div>
    )
}
