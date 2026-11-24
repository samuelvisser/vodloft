import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import DialogSwitch from '../../components/common/DialogSwitch'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {Link, useNavigate, useParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {apiUrl} from '../../lib/api'
import {useCreator} from '../../lib/queries'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import PageHeader from '../../components/common/PageHeader'
import {capitalized, creatorKindText} from '../../types/creator'
import {CreatorPageReadSchema, CreatorUpdateSchema, type CreatorUpdateIn, type CreatorUpdateOut} from '../../types/schemas/creator'
import './CreatorPages.css'
import Breadcrumb from '../../components/common/Breadcrumb/Breadcrumb'
import {nameInText} from '../../lib/nameInText'
import OptionsEditor from '../../components/common/OptionsEditor/OptionsEditor'
import ReadMore from '../../utils/ReadMore'

export default function EditCreatorPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: creator, error} = useCreator(slug)
    const [deleting, setDeleting] = useState(false)
    // Deleting the creator keeps its collections, unless this says to delete those too.
    const [withCollections, setWithCollections] = useState(false)

    const form = useForm<CreatorUpdateIn, unknown, CreatorUpdateOut>({
        resolver: zodResolver(CreatorUpdateSchema),
        defaultValues: getZodDefaults(CreatorUpdateSchema),
    })
    const {register, reset, watch, setValue, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!creator) return
        reset({
            title: creator.title, genre: creator.genre ?? '', contentRating: creator.contentRating ?? '', ytdlpOptions: creator.ytdlpOptions,
        })
    }, [creator, reset])

    if (error) return <section className="view"><div className="form-error-card" role="alert">{error.message}</div></section>
    if (!creator) return <section className="view"><p>Loading…</p></section>

    const onSubmit = buildServerAwareSubmit<CreatorUpdateIn, CreatorUpdateOut>(form, (data) => fetch(
        `${apiUrl()}/creators/${encodeURIComponent(creator.slug)}`, {
            method: 'PATCH',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: data.title, genre: data.genre || null, contentRating: data.contentRating || null,
                ...(creator.takesYtdlpOptions ? {ytdlpOptions: data.ytdlpOptions} : {}),
            }),
        },
    ), {
        fallbackField: 'title',
        onSuccess: async (page) => {
            queryClient.setQueryData(['creator', slug], CreatorPageReadSchema.parse(page))
            // The creator's collections take its name as their author.
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collections']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
            ])
            navigate(`/creator/${creator.slug}`)
        },
    })

    const onConfirmDelete = async () => {
        const query = withCollections ? '?deleteCollections=true' : ''
        const response = await fetch(`${apiUrl()}/creators/${encodeURIComponent(creator.slug)}${query}`, {method: 'DELETE', credentials: 'include'})
        if (!response.ok) {
            const data = await response.json().catch(() => null)
            toast.error(typeof data?.detail === 'string' ? data.detail : `The ${creator.creatorNames.singular} could not be deleted (HTTP ${response.status})`)
            return
        }
        setDeleting(false)
        queryClient.removeQueries({queryKey: ['creator', slug]})
        if (withCollections) {
            for (const {slug: collectionSlug} of creator.collections) {
                removeEpisodePreviewFromStorage(collectionSlug)
                removeSeasonsFromStorage(collectionSlug)
                queryClient.removeQueries({queryKey: ['collection', collectionSlug]})
            }
        }
        await Promise.all([
            queryClient.invalidateQueries({queryKey: ['creators']}),
            queryClient.invalidateQueries({queryKey: ['collections']}),
            queryClient.invalidateQueries({queryKey: ['collectionsView']}),
            queryClient.invalidateQueries({queryKey: ['libraryCounts']}),
        ])
        toast.success(withCollections ? `${nameInText(creator.title)} and their collections were deleted` : `${nameInText(creator.title)} was deleted`)
        navigate('/library')
    }

    return (
        <section className="view creator-view" aria-labelledby="edit-creator-title">
            {/* One block, so the page's gap does not push the breadcrumb and the title apart. */}
            <div className="creator-edit-head">
                <Breadcrumb className="page-breadcrumb" items={[
                    {label: 'Library', to: '/library'},
                    {label: `${capitalized(creator.creatorNames.singular)} ${creator.title}`, to: `/creator/${creator.slug}`},
                ]}/>
                <PageHeader
                    title="Edit creator" titleId="edit-creator-title"
                    subtitle={<p className="view-description"><Link className="quiet-link" to={`/creator/${creator.slug}`}>{creator.title}</Link> · {creatorKindText(creator)}</p>}
                />
            </div>
            <form className="form form-fluid creator-setup" onSubmit={onSubmit} noValidate>
                <div className="form-row creator-membership">
                    <label htmlFor="creator-title">Name</label>
                    <input id="creator-title" className="input" {...register('title')} aria-invalid={!!errors.title}/>
                    {errors.title && <div className="error" role="alert">{errors.title.message}</div>}
                    <div className="help">
                        The author of each collection of this {creator.creatorNames.singular}. A name you give here stays, also
                        when the name on {creator.accounts[0]?.site.name ?? 'their site'} changes.
                    </div>
                </div>

                <div className="form-row creator-membership">
                    <label htmlFor="creator-genre">Genre</label>
                    <input id="creator-genre" className="input" placeholder="Such as DIY, Woodworking" {...register('genre')}
                           aria-invalid={!!errors.genre}/>
                    {errors.genre && <div className="error" role="alert">{errors.genre.message}</div>}
                    <div className="help">Written to the NFO file of each collection of this {creator.creatorNames.singular} that has no genre of its own.</div>
                </div>

                <div className="form-row creator-membership">
                    <label htmlFor="creator-rating">Content rating</label>
                    <input id="creator-rating" className="input" placeholder="Such as TV-G" {...register('contentRating')}
                           aria-invalid={!!errors.contentRating}/>
                    {errors.contentRating && <div className="error" role="alert">{errors.contentRating.message}</div>}
                </div>

                {creator.takesYtdlpOptions && (
                    <div className="form-row creator-membership">
                        <label htmlFor="creator-ytdlp-options">Your own yt-dlp options</label>
                        <OptionsEditor
                            id="creator-ytdlp-options"
                            value={watch('ytdlpOptions') ?? ''}
                            onChange={(value) => setValue('ytdlpOptions', value, {shouldDirty: true, shouldValidate: !!errors.ytdlpOptions})}
                            invalid={!!errors.ytdlpOptions}
                            describedBy={errors.ytdlpOptions ? 'creator-ytdlp-options-errors' : 'creator-ytdlp-options-help'}
                        />
                        {errors.ytdlpOptions && (
                            <div id="creator-ytdlp-options-errors" className="error" role="alert">{errors.ytdlpOptions.message}</div>
                        )}
                        <div className="help" id="creator-ytdlp-options-help">
                            <ReadMore summary={`Options for every collection of this ${creator.creatorNames.singular}, on top of the yt-dlp Source’s options in Settings. Most leave this empty.`}>
                                <p>These lines come after the yt-dlp options in Settings, under Sources, and before a collection’s own options.
                                    So for an option set in more than one place, the collection’s own wins, then this {creator.creatorNames.singular}’s.
                                    Each line is checked with yt-dlp’s own parser, and the same options are blocked as in Settings.
                                    Collections that don’t use yt-dlp, such as those from The Daily Wire, don’t use these options.</p>
                            </ReadMore>
                        </div>
                    </div>
                )}

                {errors.root && <div className="form-error-card" role="alert">{errors.root.message}</div>}
                <div className="actions">
                    <button type="button" className="btn btn-danger" style={{marginRight: 'auto'}} onClick={() => setDeleting(true)}>
                        <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
                        <span>Delete {creator.creatorNames.singular}</span>
                    </button>
                    <button type="button" className="btn" onClick={() => navigate(`/creator/${creator.slug}`)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !isDirty}>
                        {isSubmitting ? 'Saving…' : 'Save'}
                    </button>
                </div>
            </form>

            <ConfirmDialog
                open={deleting}
                title={`Delete ${creator.creatorNames.singular}`}
                onDismiss={() => { setDeleting(false); setWithCollections(false) }}
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                confirmButton={{label: 'Delete', onClick: onConfirmDelete, className: 'btn btn-danger'}}
            >
                <p>
                    Delete {nameInText(creator.title)}? {creator.collections.length + creator.movies.length === 0
                        ? 'Nothing else leaves your library.'
                        : withCollections
                            ? (creator.movies.length > 0 ? 'Their movies stay in your library as they are, each on its own.' : '')
                            : 'Their collections and movies stay in your library as they are, each on its own.'}
                </p>
                {creator.collections.length > 0 && (
                    <DialogSwitch
                        checked={withCollections} onChange={setWithCollections}
                        label={creator.collections.length === 1 ? 'Also delete their collection' : `Also delete their ${creator.collections.length} collections`}
                        help={withCollections
                            ? 'They are deleted with everything VODLoft indexed of them. Downloaded files stay on disk.'
                            : 'Off, they stay in your library as plain collections.'}
                    />
                )}
            </ConfirmDialog>
        </section>
    )
}
