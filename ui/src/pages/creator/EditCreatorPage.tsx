import {useEffect} from 'react'
import {useNavigate, useParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {apiUrl} from '../../lib/api'
import {useCreator} from '../../lib/queries'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import SimpleSelect from '../../components/common/SimpleSelect'
import PageHeader from '../../components/common/PageHeader'
import {newSectionActionReg} from '../../types/creator'
import {
    CreatorPageReadSchema, CreatorUpdateSchema, type CreatorUpdateIn, type CreatorUpdateOut,
} from '../../types/schemas/creator'
import './CreatorPages.css'

export default function EditCreatorPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: creator, error} = useCreator(slug)

    const form = useForm<CreatorUpdateIn, unknown, CreatorUpdateOut>({
        resolver: zodResolver(CreatorUpdateSchema),
        defaultValues: getZodDefaults(CreatorUpdateSchema),
    })
    const {register, watch, setValue, reset, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!creator) return
        reset({
            newSections: creator.newSections, genre: creator.genre ?? '', contentRating: creator.contentRating ?? '',
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
                newSections: data.newSections, genre: data.genre || null, contentRating: data.contentRating || null,
            }),
        },
    ), {
        fallbackField: 'newSections',
        onSuccess: async (page: unknown) => {
            queryClient.setQueryData(['creator', slug], CreatorPageReadSchema.parse(page))
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            navigate(`/creator/${creator.slug}`)
        },
    })

    return (
        <section className="view creator-view" aria-labelledby="edit-creator-title">
            <PageHeader
                title="Edit creator" titleId="edit-creator-title"
                subtitle={<p className="view-description">{creator.title} · {creator.site.name} {creator.creatorLabel}</p>}
            />
            <form className="form form-fluid creator-setup" onSubmit={onSubmit} noValidate>
                <div className="form-row creator-membership">
                    <label htmlFor="creator-new-sections">When the {creator.creatorLabel} adds a playlist or show</label>
                    <SimpleSelect
                        inputId="creator-new-sections" registry={newSectionActionReg(creator.creatorLabel)} value={newSections}
                        onChange={(value) => setValue('newSections', value as CreatorUpdateIn['newSections'], {shouldDirty: true})}
                    />
                    {errors.newSections && <div className="error" role="alert">{errors.newSections.message}</div>}
                    <div className="help">
                        {newSectionActionReg(creator.creatorLabel).meta(newSections as never)?.help} VODLoft looks for new ones once a day.
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
                    <button type="button" className="btn" onClick={() => navigate(`/creator/${creator.slug}`)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !isDirty}>
                        {isSubmitting ? 'Saving…' : 'Save'}
                    </button>
                </div>
            </form>
        </section>
    )
}
