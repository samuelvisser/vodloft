import {useEffect} from 'react'
import {useNavigate, useParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {apiUrl} from '../../lib/api'
import {useChannel} from '../../lib/queries'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import SimpleSelect from '../../components/common/SimpleSelect'
import PageHeader from '../../components/common/PageHeader'
import {newSectionActionReg} from '../../types/channel'
import {
    ChannelPageReadSchema, ChannelUpdateSchema, type ChannelUpdateIn, type ChannelUpdateOut,
} from '../../types/schemas/channel'
import './ChannelPages.css'

export default function EditChannelPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: channel, error} = useChannel(slug)

    const form = useForm<ChannelUpdateIn, unknown, ChannelUpdateOut>({
        resolver: zodResolver(ChannelUpdateSchema),
        defaultValues: getZodDefaults(ChannelUpdateSchema),
    })
    const {register, watch, setValue, reset, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!channel) return
        reset({
            newSections: channel.newSections, genre: channel.genre ?? '', contentRating: channel.contentRating ?? '',
        })
    }, [channel, reset])

    if (error) return <section className="view"><div className="form-error-card" role="alert">{error.message}</div></section>
    if (!channel) return <section className="view"><p>Loading…</p></section>

    const newSections = watch('newSections') ?? 'ask'

    const onSubmit = buildServerAwareSubmit<ChannelUpdateIn, ChannelUpdateOut>(form, (data) => fetch(
        `${apiUrl()}/channels/${encodeURIComponent(channel.slug)}`, {
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
            queryClient.setQueryData(['channel', slug], ChannelPageReadSchema.parse(page))
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            navigate(`/channel/${channel.slug}`)
        },
    })

    return (
        <section className="view channel-view" aria-labelledby="edit-channel-title">
            <PageHeader
                title="Edit channel" titleId="edit-channel-title"
                subtitle={<p className="view-description">{channel.title} · {channel.site.name} {channel.channelLabel}</p>}
            />
            <form className="form form-fluid channel-setup" onSubmit={onSubmit} noValidate>
                <div className="form-row channel-membership">
                    <label htmlFor="channel-new-sections">When the {channel.channelLabel} adds a playlist or show</label>
                    <SimpleSelect
                        inputId="channel-new-sections" registry={newSectionActionReg(channel.channelLabel)} value={newSections}
                        onChange={(value) => setValue('newSections', value as ChannelUpdateIn['newSections'], {shouldDirty: true})}
                    />
                    {errors.newSections && <div className="error" role="alert">{errors.newSections.message}</div>}
                    <div className="help">
                        {newSectionActionReg(channel.channelLabel).meta(newSections as never)?.help} VODLoft looks for new ones once a day.
                    </div>
                </div>

                <div className="form-row channel-membership">
                    <label htmlFor="channel-genre">Genre</label>
                    <input id="channel-genre" className="input" placeholder="Such as DIY, Woodworking" {...register('genre')}
                           aria-invalid={!!errors.genre}/>
                    {errors.genre && <div className="error" role="alert">{errors.genre.message}</div>}
                    <div className="help">Written to the NFO file of each collection of this {channel.channelLabel} that has no genre of its own.</div>
                </div>

                <div className="form-row channel-membership">
                    <label htmlFor="channel-rating">Content rating</label>
                    <input id="channel-rating" className="input" placeholder="Such as TV-G" {...register('contentRating')}
                           aria-invalid={!!errors.contentRating}/>
                    {errors.contentRating && <div className="error" role="alert">{errors.contentRating.message}</div>}
                </div>

                {errors.root && <div className="form-error-card" role="alert">{errors.root.message}</div>}
                <div className="actions">
                    <button type="button" className="btn" onClick={() => navigate(`/channel/${channel.slug}`)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !isDirty}>
                        {isSubmitting ? 'Saving…' : 'Save'}
                    </button>
                </div>
            </form>
        </section>
    )
}
