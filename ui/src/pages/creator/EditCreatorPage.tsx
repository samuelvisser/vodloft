import {useEffect, useRef, useState} from 'react'
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
import {refreshFrontendPuller} from '../../lib/puller'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import PageHeader from '../../components/common/PageHeader'
import {creatorKindText, joinedNames, newListActionReg} from '../../types/creator'
import NewListSettings from '../../components/common/NewListSettings'
import {
    CreatorPageReadSchema, CreatorUpdateSchema, newListsValues, withNewList, type CreatorUpdateIn, type CreatorUpdateOut,
    type NewSectionAction, type SectionPlaces,
} from '../../types/schemas/creator'
import CreatorSectionsEditor, {placedSections, placeKey, placeLabel, placeMove, placeOf} from './CreatorSectionsEditor'
import MoveSectionsDialog, {type PlaceChange} from './MoveSectionsDialog'
import './CreatorPages.css'
import Breadcrumb from '../../components/common/Breadcrumb/Breadcrumb'

export default function EditCreatorPage() {
    const {slug} = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const {data: creator, error} = useCreator(slug)
    const [deleting, setDeleting] = useState(false)
    // The feeds and lists that go elsewhere, while the dialog asks before saving them.
    const [moving, setMoving] = useState<PlaceChange[] | null>(null)
    const [moveError, setMoveError] = useState<string | null>(null)
    // Whether each collection numbers its episodes again, as the dialog says, for the save that moves.
    const renumber = useRef<Record<string, boolean> | null>(null)

    const form = useForm<CreatorUpdateIn, unknown, CreatorUpdateOut>({
        resolver: zodResolver(CreatorUpdateSchema),
        defaultValues: getZodDefaults(CreatorUpdateSchema),
    })
    const {register, watch, setValue, reset, formState: {errors, isSubmitting, isDirty}} = form

    useEffect(() => {
        if (!creator) return
        reset({
            title: creator.title, newLists: newListsValues(creator.newLists), genre: creator.genre ?? '', contentRating: creator.contentRating ?? '',
            places: {},
        })
    }, [creator, reset])

    if (error) return <section className="view"><div className="form-error-card" role="alert">{error.message}</div></section>
    if (!creator) return <section className="view"><p>Loading…</p></section>

    const newLists = watch('newLists') ?? {}

    const places = watch('places') ?? {}

    // What the user changed under where the feeds and lists go, in the words of their dropdowns.
    const placeChanges = (chosen: SectionPlaces): PlaceChange[] => placedSections(creator).flatMap((item) => {
        const place = chosen[placeKey(item.account, item.section.ref)]
        if (!place) return []
        return [{
            move: {accountId: item.account.id, ref: item.section.ref, ...placeMove(place)},
            title: item.section.title, names: item.section.names,
            from: placeLabel(creator, item, placeOf(item)), to: placeLabel(creator, item, place),
        }]
    })

    const save = (data: CreatorUpdateOut) => {
        const moves = renumber.current ? placeChanges(data.places).map((change) => change.move) : []
        return fetch(`${apiUrl()}/creators/${encodeURIComponent(creator.slug)}`, {
            method: 'PATCH',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: data.title, newLists: data.newLists, genre: data.genre || null, contentRating: data.contentRating || null,
                ...(moves.length > 0 ? {moves, renumber: renumber.current} : {}),
            }),
        })
    }
    const saved = async (page: unknown) => {
        const moved = renumber.current !== null
        renumber.current = null
        setMoving(null)
        queryClient.setQueryData(['creator', slug], CreatorPageReadSchema.parse(page))
        // The creator's collections take its name as their author.
        await Promise.all([
            // The moves run as operations, whose progress shows on the dropdowns at once.
            ...(moved ? [refreshFrontendPuller(queryClient)] : []),
            queryClient.invalidateQueries({queryKey: ['creators']}),
            queryClient.invalidateQueries({queryKey: ['collection']}),
            queryClient.invalidateQueries({queryKey: ['collections']}),
            queryClient.invalidateQueries({queryKey: ['collectionsView']}),
        ])
        // After a move the page stays, so the dropdowns of what moved show its progress.
        if (moved) toast.success(`Saved ${creator.title}; moving its ${joinedNames(moving?.map((change) => change.names) ?? []).plural}`)
        else navigate(`/creator/${creator.slug}`)
    }
    const options = {fallbackField: 'newLists' as const, fieldAlias: {moves: 'places', renumber: 'places'}, onSuccess: saved}

    // Moving feeds and lists asks first, in a dialog that saves the page.
    const onSubmit = buildServerAwareSubmit<CreatorUpdateIn, CreatorUpdateOut>(form, async (data) => {
        const changes = placeChanges(data.places)
        if (changes.length === 0) return save(data)
        setMoveError(null)
        setMoving(changes)
    }, options)
    const saveWithMoves = buildServerAwareSubmit<CreatorUpdateIn, CreatorUpdateOut>(form, async (data) => {
        const response = await save(data)
        if (!response.ok) {
            const body = await response.clone().json().catch(() => null)
            const detail = body?.detail
            renumber.current = null
            // A refusal of the moves stays in the dialog; one of another field shows under it on the page.
            if (typeof detail === 'string') {
                setMoveError(detail)
                return
            }
            setMoving(null)
        }
        return response
    }, options)

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
                    {label: creator.title, to: `/creator/${creator.slug}`},
                ]}/>
                <PageHeader
                    title="Edit creator" titleId="edit-creator-title"
                    subtitle={<p className="view-description"><Link className="quiet-link" to={`/creator/${creator.slug}`}>{creator.title}</Link> · {creatorKindText(creator)}</p>}
                />
            </div>
            <CreatorSectionsEditor creator={creator} part="new"/>
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

                <div className="creator-section-group">
                    <h2>When a new {creator.newListNames.singular} is added</h2>
                    <NewListSettings
                        kinds={creator.newLists} valueOf={(kind) => newLists[kind.siteKey ?? '']?.[kind.key]} fallback="ask"
                        idPrefix="creator-new-lists" registryFor={(kind) => newListActionReg(creator.creatorNames.singular, kind, creator.music)}
                        onChange={(kind, value) => setValue('newLists', withNewList(newLists, kind, value as NewSectionAction), {shouldDirty: true})}
                    />
                    {errors.newLists && <div className="error" role="alert">{(errors.newLists as {message?: string}).message}</div>}
                    <div className="help">VODLoft looks for new ones once a day.</div>
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

                <CreatorSectionsEditor
                    creator={creator} part="places" places={places}
                    onPlace={(key, place) => {
                        const next = {...places}
                        if (place === null || place === undefined) delete next[key]
                        else next[key] = place
                        setValue('places', next, {shouldDirty: true})
                    }}
                />
                {errors.places && <div className="error" role="alert">{(errors.places as {message?: string}).message}</div>}

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

            <CreatorSectionsEditor creator={creator} part="rest"/>

            <MoveSectionsDialog
                open={moving !== null}
                creatorSlug={creator.slug}
                changes={moving ?? []}
                onDismiss={() => setMoving(null)}
                onConfirm={async (again) => {
                    setMoveError(null)
                    renumber.current = again
                    await saveWithMoves()
                }}
                error={moveError}
            />

            <ConfirmDialog
                open={deleting}
                title={`Delete ${creator.creatorNames.singular}`}
                onDismiss={() => setDeleting(false)}
                icon={faIcon('fass', 'trash')}
                iconTone="danger"
                confirmButton={{label: 'Delete', onClick: onConfirmDelete, className: 'btn btn-danger'}}
            >
                <p>
                    Delete {creator.title}? {creator.collections.length > 0
                        ? `${creator.collections.length === 1 ? 'Its collection stays' : `Its ${creator.collections.length} collections stay`} in your library with their episodes and files, but VODLoft stops looking for new ${creator.newListNames.plural} of this ${creator.creatorNames.singular}.`
                        : `VODLoft stops looking for new ${creator.newListNames.plural} of this ${creator.creatorNames.singular}.`}
                </p>
            </ConfirmDialog>
        </section>
    )
}
