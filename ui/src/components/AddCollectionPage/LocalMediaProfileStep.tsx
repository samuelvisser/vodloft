import {useCallback, useEffect, useRef} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {ChosenCollectionCard} from './CollectionPreviewCard'
import type {CollectionCreatePayloadOut} from '../../types/schemas/collection'
import LocalMediaProfileForm from '../LocalMediaProfile/LocalMediaProfileForm'
import CollectionLocalMediaProfileOutputTemplate from '../LocalMediaProfile/CollectionLocalMediaProfileOutputTemplate'
import IndexingValuesEditorButton from '../LocalMediaProfile/IndexingValuesEditorButton'
import {useLocalMediaProfileSites, useLocalMediaProfiles} from '../../lib/queries'
import {CollectionLocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import {
    LocalMediaProfileChoiceIn,
    LocalMediaProfileChoiceOut,
    LocalMediaProfileChoiceSchema,
    LocalMediaProfileCreateUnionSchema,
} from '../../types/schemas/collection_as_bundle'
import LocalMediaProfileCard from '../LocalMediaProfile/LocalMediaProfileCard'
import ExistingFilesFields, {type ExistingFilesChoice} from './ExistingFilesFields'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import {isCollectionLocalMediaProfileAvailableFor, isLocalMediaProfileAvailableForSite, type CollectionLocalMediaProfileContext} from '../../types/local_media_profile'


/** The picked profile's output path and its examples, shown as they are: the profile is edited on its own page. */
function ChosenProfileOutputPath({profile, onCollectionRoot}: {
    profile: CollectionLocalMediaProfileRead
    onCollectionRoot: (path: string) => void
}) {
    const display = useForm<CollectionLocalMediaProfileRead>({defaultValues: profile})
    return (
        <>
            <div className="form-row">
                <p className="help">
                    This collection will use <strong>{profile.name}</strong> as it is. Other collections can use the
                    same profile, so changing it changes them too. To give this collection settings of its own,
                    unselect the profile and create a new one.
                </p>
                <div>
                    <a
                        className="btn"
                        href={`/edit-local-media-profile/${encodeURIComponent(profile.slug)}`}
                        target="_blank"
                        rel="noopener"
                    >
                        Edit media profile
                    </a>
                </div>
            </div>
            <div className="chosen-profile-output-path">
                <CollectionLocalMediaProfileOutputTemplate form={display} readOnly onCollectionRoot={onCollectionRoot}/>
            </div>
        </>
    )
}

type Props = {
    value: Partial<LocalMediaProfileChoiceIn>
    onChange: (v: Partial<LocalMediaProfileChoiceIn>) => void
    onSubmit: (v: LocalMediaProfileChoiceOut) => void
    onBack: () => void
    onContinue: () => void
    onCancel: () => void
    collectionSlug?: string
    /** The collection chosen in the first step. */
    collection?: CollectionCreatePayloadOut
    /** The Site the chosen collection is on. */
    siteKey?: string | null
    collectionType: CollectionLocalMediaProfileContext
    existingFiles: ExistingFilesChoice
    onExistingFilesChange: (value: ExistingFilesChoice) => void
}

export default function LocalMediaProfileStep({
    value, onChange, onSubmit: onSubmitParent, onBack, onContinue, onCancel, collection, collectionType, siteKey,
    existingFiles, onExistingFilesChange,
}: Props) {
    const profilesQuery = useLocalMediaProfiles()
    const {data: sites} = useLocalMediaProfileSites()
    const knownSiteKeys = sites?.sites.map((site) => site.key)
    const profiles: CollectionLocalMediaProfileRead[] | undefined = profilesQuery.data?.filter(
        (profile): profile is CollectionLocalMediaProfileRead =>
            profile.type === 'collection' && isCollectionLocalMediaProfileAvailableFor(profile, collectionType)
            && isLocalMediaProfileAvailableForSite(profile, siteKey, knownSiteKeys),
    )
    const profilesError = profilesQuery.isError ? ((profilesQuery.error)?.message ?? 'Failed to load media profiles') : null
    const createDefaults = getZodDefaults(LocalMediaProfileCreateUnionSchema)

    const form = useForm<LocalMediaProfileChoiceIn>({
        resolver: zodResolver(LocalMediaProfileChoiceSchema),
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

    // The existing files are looked for in the collection root, until the user picks another folder.
    const existingFilesRef = useRef(existingFiles)
    existingFilesRef.current = existingFiles
    const onCollectionRoot = useCallback((root: string) => {
        const current = existingFilesRef.current
        if (current.folderChosen || current.folder === root) return
        onExistingFilesChange({...current, folder: root})
    }, [onExistingFilesChange])

    // What the user typed for a new profile, kept while an existing profile is picked.
    const newProfileRef = useRef<Partial<LocalMediaProfileChoiceIn> | null>(null)

    const watchedOp = watch('op')
    const watchedSlug = watch('slug')
    const chosenProfile = watchedOp === 'use_existing' ? profiles?.find((profile) => profile.slug === watchedSlug) : undefined

    const handleSelect = (profile: CollectionLocalMediaProfileRead) => {
        if (watchedOp === 'use_existing' && watchedSlug === profile.slug) {
            form.reset({...createDefaults, ...(newProfileRef.current ?? {})} as LocalMediaProfileChoiceIn)
            newProfileRef.current = null
            return
        }
        if (watchedOp !== 'use_existing') newProfileRef.current = getValues()
        form.reset({op: 'use_existing', slug: profile.slug})
    }

    const onSubmit = buildServerAwareSubmit(form, async (dataIn: LocalMediaProfileChoiceIn) => {
        const dataOut = LocalMediaProfileChoiceSchema.parse(dataIn)
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
                                    const selected = watchedOp === 'use_existing' && watchedSlug === profile.slug
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

                    {watchedOp === 'use_existing' ? (
                        chosenProfile ? <ChosenProfileOutputPath key={chosenProfile.slug} profile={chosenProfile} onCollectionRoot={onCollectionRoot}/> : null
                    ) : (
                        <>
                            <hr className="divider" aria-hidden="true"/>
                            <div className="divider-label" aria-hidden="true">Or create a new profile</div>

                            <LocalMediaProfileForm
                                form={form}
                                mode="collection"
                                isCreating
                                onCollectionRoot={onCollectionRoot}
                                outputTemplateActions={<IndexingValuesEditorButton form={form} className="btn btn-small"/>}
                            />
                        </>
                    )}

                    <hr className="divider" aria-hidden="true"/>
                    <ExistingFilesFields value={existingFiles} onChange={onExistingFilesChange}/>
                </div>

                {collection ? (
                    <aside className="wizard-aside" aria-label="Selected collection details">
                        <ChosenCollectionCard collection={collection}/>
                    </aside>
                ) : null}
            </div>

            <div className="actions">
                <button type="button" className="btn" onClick={onBack}>Back</button>
                <input
                    type="submit"
                    className="btn btn-primary"
                    value="Continue"
                    disabled={isSubmitting || (existingFiles.enabled && !existingFiles.folder.trim())}
                />
                <button type="button" className="btn" onClick={onCancel}>Cancel</button>
            </div>
        </form>
    )
}
