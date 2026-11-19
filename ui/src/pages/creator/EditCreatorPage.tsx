import {useEffect, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from 'react-hot-toast'
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
import SimpleSelect from '../../components/common/SimpleSelect'
import PageHeader from '../../components/common/PageHeader'
import {creatorKindText, newSectionActionReg} from '../../types/creator'
import {
    CreatorPageReadSchema, CreatorUpdateSchema, type CreatorUpdateIn, type CreatorUpdateOut,
} from '../../types/schemas/creator'
import CreatorSectionsEditor from './CreatorSectionsEditor'
import './CreatorPages.css'

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
    const {register, watch, setValue, reset, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!creator) return
        reset({
            title: creator.title, newSections: creator.newSections, genre: creator.genre ?? '', contentRating: creator.contentRating ?? '',
        })
    }, [creator, reset])

    if (error) return <section className="view"><div className="form-error-card" role="alert">{error.message}</div></section>
    if (!creator) return <section className="view"><p>Loading…</p></section>

    const newSections = watch('newSections') ?? 'ask'

    const onSubmit = buildServerAwareSubmit<CreatorUpdateIn, CreatorUpdateOut>(form, (data) => fetch(
        `${apiUrl()}/creators/${encodeURIComponent(creator.slug)}`, {
            method: 'PATCH',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: data.title, newSections: data.newSections, genre: data.genre || null, contentRating: data.contentRating || null,
            }),
        },
    ), {
        fallbackField: 'newSections',
        onSuccess: async (page: unknown) => {
            queryClient.setQueryData(['creator', slug], CreatorPageReadSchema.parse(page))
            // The creator's collections take its name as their author.
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
            ])
            navigate(`/creator/${creator.slug}`)
        },
    })

    const onConfirmDelete = async () => {
        const response = await fetch(`${apiUrl()}/creators/${encodeURIComponent(creator.slug)}`, {method: 'DELETE', credentials: 'include'})
        if (!response.ok) {
            const data = await response.json().catch(() => null)
            toast.error(typeof data?.detail === 'string' ? data.detail : `The ${creator.creatorLabel} could not be deleted (HTTP ${response.status})`)
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
            <PageHeader
                title="Edit creator" titleId="edit-creator-title"
                subtitle={<p className="view-description"><Link className="quiet-link" to={`/creator/${creator.slug}`}>{creator.title}</Link> · {creatorKindText(creator)}</p>}
            />
            <CreatorSectionsEditor creator={creator} part="new"/>
            <form className="form form-fluid creator-setup" onSubmit={onSubmit} noValidate>
                <div className="form-row creator-membership">
                    <label htmlFor="creator-title">Name</label>
                    <input id="creator-title" className="input" {...register('title')} aria-invalid={!!errors.title}/>
                    {errors.title && <div className="error" role="alert">{errors.title.message}</div>}
                    <div className="help">
                        The author of each collection of this {creator.creatorLabel}. A name you give here stays, also
                        when the name on {creator.accounts[0]?.site.name ?? 'their site'} changes.
                    </div>
                </div>

                <div className="form-row creator-membership">
                    <label htmlFor="creator-new-sections">When the {creator.creatorLabel} adds {creator.sectionNames.one}</label>
                    <SimpleSelect
                        inputId="creator-new-sections" registry={newSectionActionReg(creator.creatorLabel, creator.accounts.map((account) => account.site))} value={newSections}
                        onChange={(value) => setValue('newSections', value as CreatorUpdateIn['newSections'], {shouldDirty: true})}
                    />
                    {errors.newSections && <div className="error" role="alert">{errors.newSections.message}</div>}
                    <div className="help">
                        {newSectionActionReg(creator.creatorLabel, creator.accounts.map((account) => account.site)).meta(newSections as never)?.help} VODLoft looks for new ones once a day.
                    </div>
                </div>

                <div className="form-row creator-membership">
                    <label htmlFor="creator-genre">Genre</label>
                    <input id="creator-genre" className="input" placeholder="Such as DIY, Woodworking" {...register('genre')}
                           aria-invalid={!!errors.genre}/>
                    {errors.genre && <div className="error" role="alert">{errors.genre.message}</div>}
                    <div className="help">Written to the NFO file of each collection of this {creator.creatorLabel} that has no genre of its own.</div>
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
                        <span>Delete {creator.creatorLabel}</span>
                    </button>
                    <button type="button" className="btn" onClick={() => navigate(`/creator/${creator.slug}`)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !isDirty}>
                        {isSubmitting ? 'Saving…' : 'Save'}
                    </button>
                </div>
            </form>

            <CreatorSectionsEditor creator={creator} part="rest"/>

            <ConfirmDialog
                open={deleting}
                title={`Delete ${creator.creatorLabel}`}
                onDismiss={() => setDeleting(false)}
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                confirmButton={{label: 'Delete', onClick: onConfirmDelete, className: 'btn btn-danger'}}
            >
                <p>
                    Delete {creator.title}? {creator.collections.length > 0
                        ? `${creator.collections.length === 1 ? 'Its collection stays' : `Its ${creator.collections.length} collections stay`} in your library with their episodes and files, but VODLoft stops looking for new ${creator.sectionNames.many} of this ${creator.creatorLabel}.`
                        : `VODLoft stops looking for new ${creator.sectionNames.many} of this ${creator.creatorLabel}.`}
                </p>
            </ConfirmDialog>
        </section>
    )
}
