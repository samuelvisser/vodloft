import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
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

export default function EditCreatorPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: creator, error} = useCreator(slug)
    const [deleting, setDeleting] = useState(false)

    const form = useForm<CreatorUpdateIn, unknown, CreatorUpdateOut>({
        resolver: zodResolver(CreatorUpdateSchema),
        defaultValues: getZodDefaults(CreatorUpdateSchema),
    })
    const {register, reset, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!creator) return
        reset({title: creator.title, genre: creator.genre ?? '', contentRating: creator.contentRating ?? ''})
    }, [creator, reset])

    if (error) return <section className="view"><div className="form-error-card" role="alert">{error.message}</div></section>
    if (!creator) return <section className="view"><p>Loading…</p></section>

    const onSubmit = buildServerAwareSubmit<CreatorUpdateIn, CreatorUpdateOut>(form, (data) => fetch(
        `${apiUrl()}/creators/${encodeURIComponent(creator.slug)}`, {
            method: 'PATCH',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: data.title, genre: data.genre || null, contentRating: data.contentRating || null}),
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
        const response = await fetch(`${apiUrl()}/creators/${encodeURIComponent(creator.slug)}`, {method: 'DELETE', credentials: 'include'})
        if (!response.ok) {
            const data = await response.json().catch(() => null)
            toast.error(typeof data?.detail === 'string' ? data.detail : `The ${creator.creatorNames.singular} could not be deleted (HTTP ${response.status})`)
            return
        }
        setDeleting(false)
        queryClient.removeQueries({queryKey: ['creator', slug]})
        await Promise.all([
            queryClient.invalidateQueries({queryKey: ['creators']}),
            queryClient.invalidateQueries({queryKey: ['collections']}),
            queryClient.invalidateQueries({queryKey: ['collectionsView']}),
        ])
        toast.success(`${creator.title} was deleted`)
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
                onDismiss={() => setDeleting(false)}
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                confirmButton={{label: 'Delete', onClick: onConfirmDelete, className: 'btn btn-danger'}}
            >
                <p>
                    Delete {creator.title}? {creator.collections.length + creator.movies.length > 0
                        ? 'Their collections and movies stay in your library as they are, each on its own.'
                        : `Nothing else leaves your library.`}
                </p>
            </ConfirmDialog>
        </section>
    )
}
