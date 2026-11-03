import {useEffect, useRef} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {ChosenCollectionCard} from './CollectionPreviewCard'
import type {CollectionCreatePayloadOut} from '../../types/schemas/collection'
import LocalMediaProfileCommonFields from '../LocalMediaProfile/LocalMediaProfileCommonFields'
import CollectionLocalMediaProfileFields from '../LocalMediaProfile/CollectionLocalMediaProfileFields'
import IndexingValuesEditorButton from '../LocalMediaProfile/IndexingValuesEditorButton'
import CollectionLocalMediaProfileOutputTemplate from '../LocalMediaProfile/CollectionLocalMediaProfileOutputTemplate'
import {useLocalMediaProfiles} from '../../lib/queries'
import {CollectionLocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import {
    LocalMediaProfileCreateUnionIn,
    LocalMediaProfileCreateUnionSchema,
    LocalMediaProfileUpdateUnionSchema,
    LocalMediaProfileUpsertIn,
    LocalMediaProfileUpsertOut,
    LocalMediaProfileUpsertSchema,
} from '../../types/schemas/collection_as_bundle'
import LocalMediaProfileCard from '../LocalMediaProfile/LocalMediaProfileCard'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import {isCollectionLocalMediaProfileAvailableFor, type CollectionLocalMediaProfileContext} from '../../types/local_media_profile'
/** Quality, subtitle language and yt-dlp option choices an existing profile keeps when this step picks it. */
/** Quality and subtitle language choices an existing profile keeps when this step picks it. */
const QUALITY_FIELDS = [
    'subtitleLanguages', 'subtitleLanguageMode', 'qualityGoal', 'videoCodecs', 'codecFallback',
    'container', 'audioCodec', 'audioFormat', 'audioLanguage',
] as const


type Props = {
    value: Partial<LocalMediaProfileUpsertIn>
    onChange: (v: Partial<LocalMediaProfileUpsertIn>) => void
    onSubmit: (v: LocalMediaProfileUpsertOut) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    collectionSlug?: string
    /** The collection chosen in the first step. */
    collection?: CollectionCreatePayloadOut
    collectionType: CollectionLocalMediaProfileContext
}

export default function LocalMediaProfileStep({value, onChange, onSubmit: onSubmitParent, onBack, onContinue, onCancel, collection, collectionType}: Props) {
    const profilesQuery = useLocalMediaProfiles()
    const profiles: CollectionLocalMediaProfileRead[] | undefined = profilesQuery.data?.filter(
        (profile): profile is CollectionLocalMediaProfileRead =>
            profile.type === 'collection' && isCollectionLocalMediaProfileAvailableFor(profile, collectionType),
    )
    const profilesError = profilesQuery.isError ? ((profilesQuery.error)?.message ?? 'Failed to load media profiles') : null
    const createDefaults = getZodDefaults(LocalMediaProfileCreateUnionSchema)
    const updateDefaults = getZodDefaults(LocalMediaProfileUpdateUnionSchema)

    const form = useForm<LocalMediaProfileUpsertIn>({
        resolver: zodResolver(LocalMediaProfileUpsertSchema),
        mode: 'onBlur',
        shouldFocusError: true,
        defaultValues: {...createDefaults, ...value},
    })
    const {watch, getValues, formState: {isSubmitting}} = form

    useEffect(() => {
        const subscription = watch(() => {
            onChange(getValues())
        })
        return () => subscription.unsubscribe()
    }, [watch, getValues, onChange])

    const snapshotRef = useRef<Partial<LocalMediaProfileCreateUnionIn> | null>(null)

    const watchedOp = watch('op')
    const watchedSlug = watch('slug')

    const handleSelect = (profile: CollectionLocalMediaProfileRead) => {
        const selected = watchedOp === 'update_by_slug' && watchedSlug === profile.slug
        if (selected) {
            form.reset({
                ...createDefaults,
                ...(snapshotRef.current ?? {}),
            } as LocalMediaProfileUpsertIn)
            snapshotRef.current = null
            return
        }

        if (watchedOp !== 'update_by_slug') {
            snapshotRef.current = {
                name: watch('name'),
                collectionScope: watch('collectionScope'),
                subtitleMode: watch('subtitleMode'),
                outputTemplate: watch('outputTemplate'),
                preferredFormat: watch('preferredFormat'),
                indexingValues: watch('indexingValues'),
                ...Object.fromEntries(QUALITY_FIELDS.map((name) => [name, watch(name)])),
            }
        }

        form.reset({
            ...updateDefaults,
            id: profile.id,
            slug: profile.slug,
            name: profile.name,
            collectionScope: profile.collectionScope,
            subtitleMode: profile.subtitleMode,
            outputTemplate: profile.outputTemplate,
            preferredFormat: profile.preferredFormat,
            indexingValues: profile.indexingValues,
            ...Object.fromEntries(QUALITY_FIELDS.map((name) => [name, profile[name]])),
        } as LocalMediaProfileUpsertIn)
    }

    const onSubmit = buildServerAwareSubmit(form, async (dataIn: LocalMediaProfileUpsertIn) => {
        const dataOut = LocalMediaProfileUpsertSchema.parse(dataIn)
        onSubmitParent(dataOut)
        onContinue()
    }, {
        fallbackField: 'name',
        rootClientValidationMessage: 'Please fix the highlighted fields.',
    })

    return (
        <form className="form form-fluid" onSubmit={onSubmit} noValidate>
            <div className="wizard-sticky-region">
                <div className="wizard-main">
                    <div className="form-row">
                        <label>Choose a media profile</label>
                        <div className="card-grid" role="list">
                            {profilesQuery.isPending ? (
                                <div role="listitem" className="card">Loading profiles...</div>
                            ) : !profiles || profiles.length === 0 ? (
                                <div role="listitem" className="card">{profilesError ?? 'No profiles found'}</div>
                            ) : (
                                profiles.map((profile) => {
                                    const selected = watchedOp === 'update_by_slug' && watchedSlug === profile.slug
                                    return (
                                        <LocalMediaProfileCard
                                            key={profile.slug}
                                            profile={profile}
                                            selected={selected}
                                            onClick={() => handleSelect(profile)}
                                        />
                                    )
                                })
                            )}
                        </div>
                    </div>

                    <hr className="divider" aria-hidden="true"/>
                    <div className="divider-label" aria-hidden="true">
                        {watchedOp === 'update_by_slug' ? 'Update current profile' : 'Or create a new profile'}
                    </div>

                    <LocalMediaProfileCommonFields
                        key={watchedOp === 'update_by_slug' ? watchedSlug : 'create_new'}
                        form={form}
                        mode="collection"
                        isCreating={watchedOp !== 'update_by_slug'}
                    />
                    <CollectionLocalMediaProfileFields form={form}/>
                    <div className="form-row">
                        <label>Indexing values</label>
                        <IndexingValuesEditorButton form={form}/>
                        <div className="help">
                            Configure optional named number sequences for use with <code>custom_index</code> in the output template.
                        </div>
                    </div>
                </div>

                {collection ? (
                    <aside className="wizard-aside" aria-label="Selected collection details">
                        <ChosenCollectionCard collection={collection}/>
                    </aside>
                ) : null}
            </div>

            <CollectionLocalMediaProfileOutputTemplate form={form}/>

            <div className="actions">
                <button type="button" className="btn" onClick={onBack}>Back</button>
                <input type="submit" className="btn btn-primary" value="Continue" disabled={isSubmitting}/>
                <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            </div>
        </form>
    )
}
