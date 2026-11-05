import {useEffect} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {ChosenCollectionCard} from './CollectionPreviewCard'
import type {CollectionCreatePayloadOut} from '../../types/schemas/collection'
import StreamProfileForm, {StreamDownloadProfileDefault} from '../StreamProfile/StreamProfileForm'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {
    RssStreamProfileBundleIn,
    RssStreamProfileBundleOut,
    RssStreamProfileBundleSchema,
} from '../../types/schemas/collection_as_bundle'

type Props = {
    value: Partial<RssStreamProfileBundleIn>
    onChange: (value: Partial<RssStreamProfileBundleIn>) => void
    onSubmit: (value: RssStreamProfileBundleOut) => void
    onBack: () => void
    onFinish: () => void
    onCancel: () => void
    collectionSlug?: string
    /** The collection chosen in the first step. */
    collection?: CollectionCreatePayloadOut
    collectionTitle?: string
    downloadProfileDefaults?: StreamDownloadProfileDefault[]
    episodeTypesManuallyChanged?: boolean
    onEpisodeTypesManuallyChanged?: () => void
}

export default function StreamProfileStep({
    value,
    onChange,
    onSubmit: onSubmitParent,
    onBack,
    onFinish,
    onCancel,
    collectionSlug,
    collection,
    collectionTitle,
    downloadProfileDefaults,
    episodeTypesManuallyChanged,
    onEpisodeTypesManuallyChanged,
}: Props) {
    const form = useForm<RssStreamProfileBundleIn>({
        resolver: zodResolver(RssStreamProfileBundleSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: value as RssStreamProfileBundleIn,
    })
    const {watch, formState: {isSubmitting}} = form

    useEffect(() => {
        const subscription = watch((values) => onChange(values as Partial<RssStreamProfileBundleIn>))
        return () => subscription.unsubscribe()
    }, [watch, onChange])

    const onSubmit = buildServerAwareSubmit(form as any, async (dataIn: RssStreamProfileBundleIn) => {
        const dataOut = RssStreamProfileBundleSchema.parse(dataIn)
        onSubmitParent(dataOut)
        onFinish()
    }, {
        rootClientValidationMessage: 'Please fix the highlighted fields.',
    })

    return (
        <div className="wizard-with-aside">
            <div className="wizard-main">
                <form className="form form-fluid" onSubmit={onSubmit} noValidate>
                    <StreamProfileForm
                        form={form as any}
                        mode="rss"
                        collectionRoot
                        isCreating
                        downloadProfileDefaults={downloadProfileDefaults}
                        episodeTypesManuallyChanged={episodeTypesManuallyChanged}
                        onEpisodeTypesManuallyChanged={onEpisodeTypesManuallyChanged}
                        collectionSlug={collectionSlug}
                        collectionTitle={collectionTitle}
                        sourceKey={collection?.sourceKey}
                        collectionUrl={collection?.sharingUrl}
                        canOpenDownloadProfiles={false}
                    />
                    <div className="actions">
                        <button type="button" className="btn" onClick={onBack}>Back</button>
                        <input type="submit" className="btn btn-primary" value="Save collection" disabled={isSubmitting}/>
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
