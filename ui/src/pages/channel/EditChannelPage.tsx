import {useEffect, useState} from 'react'
import {useNavigate, useParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {useChannel} from '../../lib/queries'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import SimpleSelect from '../../components/common/SimpleSelect'
import PageHeader from '../../components/common/PageHeader'
import {NewSectionActionReg} from '../../types/channel'
import {
    ChannelPageReadSchema, ChannelUpdateSchema, type ChannelOrderEntry, type ChannelUpdateIn, type ChannelUpdateOut,
} from '../../types/schemas/channel'
import './ChannelPages.css'

const PLACEMENT_WORDS = {site_seasons: 'by year', one_season: 'as a season', specials: 'as specials'} as const

function where(entry: ChannelOrderEntry) {
    if (entry.kind === 'feed' || entry.placement === 'site_seasons') {
        return entry.kind === 'feed' ? `${entry.collectionTitle}, by year` : `${entry.collectionTitle}, with its own seasons`
    }
    return `${entry.collectionTitle}, ${PLACEMENT_WORDS[entry.placement]}`
}

export default function EditChannelPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: channel, error} = useChannel(slug)
    const [dragging, setDragging] = useState<number | null>(null)

    const form = useForm<ChannelUpdateIn, unknown, ChannelUpdateOut>({
        resolver: zodResolver(ChannelUpdateSchema),
        defaultValues: getZodDefaults(ChannelUpdateSchema),
    })
    const {register, watch, setValue, reset, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!channel) return
        reset({
            newSections: channel.newSections, genre: channel.genre ?? '', contentRating: channel.contentRating ?? '',
            order: channel.order.map((entry) => entry.ref),
        })
    }, [channel, reset])

    if (error) return <section className="view"><div className="form-error-card" role="alert">{error.message}</div></section>
    if (!channel) return <section className="view"><p>Loading…</p></section>

    const order = watch('order') ?? []
    const newSections = watch('newSections') ?? 'ask'
    const entries = new Map(channel.order.map((entry) => [entry.ref, entry]))
    const move = (from: number, to: number) => {
        if (to < 0 || to >= order.length) return
        const next = [...order]
        const [item] = next.splice(from, 1)
        next.splice(to, 0, item)
        setValue('order', next, {shouldDirty: true})
    }

    const onSubmit = buildServerAwareSubmit<ChannelUpdateIn, ChannelUpdateOut>(form, (data) => fetch(
        `${apiUrl()}/channels/${encodeURIComponent(channel.slug)}`, {
            method: 'PATCH',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                newSections: data.newSections, genre: data.genre || null, contentRating: data.contentRating || null,
                order: data.order,
            }),
        },
    ), {
        fallbackField: 'order',
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
                {order.length > 1 && (
                    <div className="form-row">
                        <label id="channel-order-label">When a video is in more than one place</label>
                        <ol className="channel-order" aria-labelledby="channel-order-label">
                            {order.map((ref, index) => {
                                const entry = entries.get(ref)
                                if (!entry) return null
                                return (
                                    <li
                                        key={ref}
                                        className={`channel-order-item${dragging === index ? ' is-dragging' : ''}`}
                                        draggable
                                        onDragStart={(event) => {
                                            setDragging(index)
                                            event.dataTransfer.effectAllowed = 'move'
                                        }}
                                        onDragOver={(event) => {
                                            event.preventDefault()
                                            if (dragging !== null && dragging !== index) {
                                                move(dragging, index)
                                                setDragging(index)
                                            }
                                        }}
                                        onDragEnd={() => setDragging(null)}
                                    >
                                        <span className="channel-order-grip" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/></span>
                                        <span className="channel-order-number" aria-hidden="true">{index + 1}</span>
                                        <span className="channel-order-copy">
                                            <b>{entry.title}</b>
                                            <span>{where(entry)}{entry.videoCount > 0 ? ` · ${entry.videoCount} ${entry.videoCount === 1 ? 'video' : 'videos'}` : ''}</span>
                                        </span>
                                        <span className="channel-order-actions">
                                            <button type="button" aria-label={`Move ${entry.title} up`} disabled={index === 0} onClick={() => move(index, index - 1)}>
                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                            </button>
                                            <button type="button" aria-label={`Move ${entry.title} down`} disabled={index === order.length - 1} onClick={() => move(index, index + 1)}>
                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                            </button>
                                        </span>
                                    </li>
                                )
                            })}
                        </ol>
                        {errors.order && <div className="error" role="alert">{String(errors.order.message ?? errors.order.root?.message)}</div>}
                        <div className="help">
                            A video goes to the highest place it is in. A video that already has a file stays where it is, so
                            file names never change. Drag or use the arrows to reorder.
                        </div>
                    </div>
                )}

                <div className="form-row channel-membership">
                    <label htmlFor="channel-new-sections">When the {channel.channelLabel} adds a playlist or show</label>
                    <SimpleSelect
                        inputId="channel-new-sections" registry={NewSectionActionReg} value={newSections}
                        onChange={(value) => setValue('newSections', value as ChannelUpdateIn['newSections'], {shouldDirty: true})}
                    />
                    {errors.newSections && <div className="error" role="alert">{errors.newSections.message}</div>}
                    <div className="help">
                        {NewSectionActionReg.meta(newSections as never)?.help} VODLoft looks for new ones once a day.
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
