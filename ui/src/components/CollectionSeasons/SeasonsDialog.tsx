import {useEffect, useId, useMemo, useRef, useState} from 'react'
import {Controller, useFieldArray, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Switch from 'react-switch'
import {Link} from 'react-router-dom'
import toast from 'react-hot-toast'

import {apiUrl} from '../../lib/api'
import {faIcon} from '../../icons/faIcon'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry, type SelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {
    CollectionSeasonsFormSchema, CollectionSeasonsReadSchema, LinkSeasonAddFormSchema, seasonsFormValues,
    type CollectionListRead, type CollectionSeasonsFormIn, type CollectionSeasonsFormOut, type CollectionSeasonsRead,
    type LinkSeasonAddFormIn, type LinkSeasonAddFormOut,
} from '../../types/schemas/collection_seasons'
import './SeasonsDialog.css'

type Props = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    onDismiss: () => void
}

/** What saving removes: ``asked`` when the ones with files stay until Home asks about them. */
type Leaving = {episodes: number, withFiles: number, asked?: boolean}

/** A creator's videos, or an artist's tracks. */
type Words = {creator: string, video: string, videos: string, creators: string}
const wordsFor = (music: boolean): Words => music
    ? {creator: 'artist', creators: 'artists', video: 'track', videos: 'tracks'}
    : {creator: 'creator', creators: 'creators', video: 'video', videos: 'videos'}

const capitalized = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)
const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`

async function readSeasons(response: Response): Promise<CollectionSeasonsRead> {
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : `Could not load the seasons (HTTP ${response.status})`)
    }
    return CollectionSeasonsReadSchema.parse(await response.json())
}

/** The registries of the dialog's selects, in the words of the collection's Site. */
function registries(names: CollectionSeasonsRead['names'], words: Words, view: CollectionSeasonsRead) {
    const outside = {
        leave_out: {label: 'Leave them out', help: `A ${names.one} only takes the ${words.videos} the collection's own link has.`},
        add: {label: 'Add them to the collection', help: `They join the collection in their ${names.one}'s season. Switching a ${names.one} or this setting off removes them again, files and all. When the ${words.creator} takes a downloaded one out, Home asks whether to keep it.`},
        only: {label: `Only what the ${names.many} have`, help: `The collection holds nothing but the ${words.videos} of its ${names.many}, also other ${words.creators}', and you can add links of your own, from any site. Its own ${words.videos} in no ${names.one} leave.`},
    }
    return {
        mode: createSelectRegistry(`LinkSeasonMode-${names.many}`, {
            all: {label: `Every ${names.one}`, help: `Every ${names.one}, also the ones to come, is a season.`},
            selected: {label: `Only the ${names.many} I pick`, help: `Only the ${names.many} switched on below are seasons.`},
        }),
        newLinks: createSelectRegistry(`NewLinkSeasons-${names.many}`, {
            ask: {label: 'Ask me', help: `VODLoft sends a message, and the new ${names.one} waits here for you to switch it on.`},
            add: {label: 'Make it a season', help: `A new ${names.one} becomes a season right away.`},
            ignore: {label: 'Leave it off', help: `A new ${names.one} stays off. You can switch it on here.`},
        }),
        layout: createSelectRegistry(`ListLayout-${names.many}`, {
            season_each: {label: `A season per ${names.one}`, help: `Each ${names.one} is a season, or shares one with the ${names.many} you put together below.`},
            by_year: {label: 'Together in seasons by year', help: `The ${names.many} still decide which ${words.videos} are in, but every ${words.video} goes to the season of its year, as do the ${words.videos} in no ${names.one}. Downloaded ${words.videos} stay where they are, marked Moved, until you move them.`},
        }),
        loose: createSelectRegistry(`LooseVideos-${names.looseSeason}`, {
            one_season: {label: `One season, ${names.looseSeason}`, help: `They share one season, shown before the ${names.many}.`},
            by_year: {label: 'A season per year', help: `They get a season per upload year, with the ${names.many} between them by date.`},
        }),
        outside: createSelectRegistry(
            `OutsideVideos-${names.many}-${view.listsPlaylists}-${view.linksOnlyOffered}`,
            // The choice is only offered for a creator's collection; holding only the playlists is offered where the
            // Source can hold a collection of links.
            (view.linksOnlyOffered ? outside : {leave_out: outside.leave_out, add: outside.add}) as typeof outside,
        ),
    }
}

/** The Seasons dialog: rename and reorder a collection's seasons, and choose which of its creator's playlists are seasons. */
export default function SeasonsDialog({open, collectionSlug, collectionTitle, onDismiss}: Props) {
    const queryClient = useQueryClient()
    const titleId = `seasons-dialog-title-${useId()}`
    const endpoint = `${apiUrl()}/collections/${encodeURIComponent(collectionSlug)}/season-settings`
    const queryKey = ['collection', collectionSlug, 'seasonSettings']
    const {data: view, error} = useQuery({
        queryKey,
        enabled: open,
        queryFn: ({signal}) => fetch(endpoint, {signal, credentials: 'include'}).then(readSeasons),
    })
    const [refreshing, setRefreshing] = useState(false)
    const [confirm, setConfirm] = useState<Leaving | null>(null)
    const [dragging, setDragging] = useState<number | null>(null)
    const confirmed = useRef(false)

    const form = useForm<CollectionSeasonsFormIn, unknown, CollectionSeasonsFormOut>({
        resolver: zodResolver(CollectionSeasonsFormSchema),
        defaultValues: CollectionSeasonsFormSchema.parse({}),
    })
    const {control, register, watch, setValue, reset, formState: {errors, isSubmitting, isDirty}} = form
    const {fields, move} = useFieldArray({control, name: 'seasons', keyName: 'key'})

    const loadedFor = useRef<CollectionSeasonsRead | null>(null)
    useEffect(() => {
        if (!open) {
            loadedFor.current = null
            return
        }
        if (!view || loadedFor.current === view) return
        loadedFor.current = view
        reset(seasonsFormValues(view))
    }, [open, view, reset])

    /** Show what the server answered without resetting the form to it, which would undo the user's unsaved changes.
     * The cache keeps its own copy of the answer, so that copy is the one the form counts as loaded. */
    const keepLoaded = (fresh: CollectionSeasonsRead) => {
        loadedFor.current = queryClient.setQueryData<CollectionSeasonsRead>(queryKey, fresh) ?? fresh
    }

    const words = wordsFor(view?.music ?? false)
    const regs = useMemo(() => view ? registries(view.names, wordsFor(view.music), view) : null, [view])
    const linkSeasonsOn = watch('linkSeasonsOn') ?? false
    const mode = watch('linkSeasonMode') ?? 'all'
    const playlistChoices = watch('playlists') ?? []
    const looseVideos = watch('looseVideos') ?? 'one_season'
    const listLayout = watch('listLayout') ?? 'season_each'
    const outsideVideos = watch('outsideVideos') ?? 'leave_out'
    const newLinkSeasons = watch('newLinkSeasons') ?? 'ask'
    const customOrder = watch('customSeasonOrder') ?? false
    const removedLinks = watch('removedLinks') ?? []
    const only = outsideVideos === 'only'

    const leaving = (values: CollectionSeasonsFormOut): Leaving => {
        if (!view) return {episodes: 0, withFiles: 0}
        if (values.outsideVideos === 'only' && view.outsideVideos !== 'only') {
            // The playlists are listed again first; the downloaded ones then stay until Home asks about them.
            return {episodes: view.onlyLeavingCount, withFiles: view.onlyLeavingWithFiles, asked: true}
        }
        if (view.linkSeasons === 'off') return {episodes: 0, withFiles: 0}
        if (!values.linkSeasonsOn || (view.outsideVideos === 'add' && values.outsideVideos === 'leave_out')) {
            return {episodes: view.outsideCount, withFiles: view.outsideWithFiles}
        }
        const enabled = new Map(values.playlists.map((choice) => [choice.id, choice.enabled]))
        const removed = new Set(values.removedLinks)
        return view.playlists
            .filter((playlist) => (view.linkSeasons === 'all' || (playlist.enabled && playlist.status === 'known'))
                && (removed.has(playlist.id) || (values.linkSeasonMode === 'selected' && !enabled.get(playlist.id))))
            .reduce((sum, playlist) => ({
                episodes: sum.episodes + playlist.leavingCount, withFiles: sum.withFiles + playlist.leavingWithFiles,
            }), {episodes: 0, withFiles: 0})
    }

    const save = buildServerAwareSubmit<CollectionSeasonsFormIn, CollectionSeasonsFormOut, CollectionSeasonsRead>(form, (data) => fetch(endpoint, {
        method: 'PUT',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            seasons: data.seasons,
            customSeasonOrder: data.customSeasonOrder,
            linkSeasons: data.linkSeasonsOn || data.outsideVideos === 'only' ? data.linkSeasonMode : 'off',
            newLinkSeasons: data.newLinkSeasons,
            looseVideos: data.looseVideos,
            listLayout: data.listLayout,
            outsideVideos: data.outsideVideos,
            playlists: data.playlists,
            removedLinks: data.removedLinks,
        }),
    }), {
        parseSuccess: readSeasons,
        fallbackField: 'seasons',
        fieldAlias: {linkSeasons: 'linkSeasonsOn', removedLinks: 'playlists'},
        genericMessage: 'Could not save the seasons',
        onSuccess: async (saved) => {
            queryClient.setQueryData(queryKey, saved)
            // The seasons and the episodes in them changed.
            removeSeasonsFromStorage(collectionSlug)
            removeEpisodePreviewFromStorage(collectionSlug)
            queryClient.removeQueries({queryKey: episodeQueryKeys.forCollection(collectionSlug)})
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['seasons', collectionSlug]}),
                queryClient.invalidateQueries({queryKey: ['collection', collectionSlug]}),
            ])
            toast.success('Seasons saved')
            onDismiss()
        },
    })

    const onSubmit = form.handleSubmit((values) => {
        const going = leaving(values)
        if (going.episodes > 0 && !confirmed.current) {
            setConfirm(going)
            return
        }
        confirmed.current = false
        return save()
    })

    const refreshPlaylists = async () => {
        setRefreshing(true)
        try {
            const fresh = await fetch(`${endpoint}/links`, {method: 'POST', credentials: 'include'}).then(readSeasons)
            const choices = new Map((form.getValues('playlists') ?? []).map((choice) => [choice.id, choice]))
            keepLoaded(fresh)
            // What the user already switched on or off, or put together, stays.
            setValue('playlists', fresh.playlists.map((playlist) => ({
                id: playlist.id, enabled: choices.get(playlist.id)?.enabled ?? playlist.enabled,
                seasonId: choices.has(playlist.id) ? choices.get(playlist.id)!.seasonId : playlist.seasonId,
            })), {shouldDirty: true})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : 'Could not list the playlists')
        } finally {
            setRefreshing(false)
        }
    }

    const linkForm = useForm<LinkSeasonAddFormIn, unknown, LinkSeasonAddFormOut>({
        resolver: zodResolver(LinkSeasonAddFormSchema),
        defaultValues: LinkSeasonAddFormSchema.parse({}),
    })
    const addLink = buildServerAwareSubmit<LinkSeasonAddFormIn, LinkSeasonAddFormOut, CollectionSeasonsRead>(linkForm, (data) => fetch(`${endpoint}/added-links`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: data.url}),
    }), {
        parseSuccess: readSeasons,
        fallbackField: 'url',
        genericMessage: 'Could not add the link',
        onSuccess: (fresh) => {
            const choices = new Map((form.getValues('playlists') ?? []).map((choice) => [choice.id, choice]))
            keepLoaded(fresh)
            // The new link is saved already; what the user changed in the dialog stays.
            setValue('playlists', fresh.playlists.map((playlist) => ({
                id: playlist.id, enabled: choices.get(playlist.id)?.enabled ?? playlist.enabled,
                seasonId: choices.has(playlist.id) ? choices.get(playlist.id)!.seasonId : playlist.seasonId,
            })))
            setValue('seasons', fresh.seasons.map((season) => form.getValues('seasons')?.find((x) => x.id === season.id) ?? {id: season.id, name: season.name}))
            linkForm.reset({url: ''})
            toast.success('Link added. VODLoft is listing its videos.')
        },
    })
    const addingLink = linkForm.formState.isSubmitting

    if (!open) return null
    const names = view?.names
    const seasonsById = new Map((view?.seasons ?? []).map((season) => [season.id, season]))
    const moveSeason = (from: number, to: number) => {
        if (to < 0 || to >= fields.length) return
        move(from, to)
        setValue('customSeasonOrder', true, {shouldDirty: true})
    }
    const enabledCount = playlistChoices.filter((choice) => choice.enabled).length
    const allEnabled = playlistChoices.length > 0 && enabledCount === playlistChoices.length
    const setAll = (enabled: boolean) => setValue(
        'playlists', playlistChoices.map((choice) => ({...choice, enabled})), {shouldDirty: true},
    )
    const playlistsById = new Map((view?.playlists ?? []).map((playlist) => [playlist.id, playlist]))
    const addedLinks = (view?.playlists ?? []).filter((playlist) => playlist.addedByUser)
    const toggleRemoved = (id: number) => setValue(
        'removedLinks', removedLinks.includes(id) ? removedLinks.filter((x) => x !== id) : [...removedLinks, id], {shouldDirty: true},
    )
    // The lists in each season as the dialog has them now, and the seasons that hold lists, which others can join.
    const listsIn = (seasonId: number) => playlistChoices.filter((choice) => choice.seasonId === seasonId)
    const listSeasonIds = [...new Set((view?.playlists ?? []).map((playlist) => playlist.seasonId).filter((id): id is number => id !== null))]
    const joinRegistry = (seasonId: number) => createSelectRegistry(
        `JoinSeason-${seasonId}-${listSeasonIds.join('-')}`,
        Object.fromEntries([
            ['own', {label: 'On its own'}],
            ...listSeasonIds.filter((id) => id !== seasonId && listsIn(id).length > 0).map((id) => [
                String(id), {label: form.getValues('seasons')?.find((x) => x.id === id)?.name ?? seasonsById.get(id)?.name ?? 'Season'},
            ]),
        ]) as Record<string, {label: string}>,
    )
    // Where the lists of a season go when every one of them left it.
    const joinsName = (seasonId: number) => {
        const first = (view?.playlists ?? []).find((playlist) => playlist.seasonId === seasonId)
        const target = first ? playlistChoices.find((choice) => choice.id === first.id)?.seasonId : null
        if (!target) return 'a season of its own'
        return form.getValues('seasons')?.find((x) => x.id === target)?.name ?? 'another season'
    }
    const joinSeason = (from: number, to: number) => setValue('playlists', playlistChoices.map((choice) => (
        choice.seasonId === from ? {...choice, seasonId: to} : choice
    )), {shouldDirty: true})
    const ownSeason = (listId: number) => setValue('playlists', playlistChoices.map((choice) => (
        // A list that leaves a season it shared gets a season of its own when you save.
        choice.id === listId ? {...choice, seasonId: null} : choice
    )), {shouldDirty: true})

    return (
        <>
            <div className="modal-overlay" role="presentation" onClick={() => !isSubmitting && onDismiss()}>
                <div className="modal seasons-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}
                     onClick={(event) => event.stopPropagation()}>
                    <div className="modal-header">
                        <h2 id={titleId} className="modal-title">Seasons of {collectionTitle}</h2>
                    </div>
                    <form onSubmit={onSubmit} noValidate>
                        <div className="seasons-dialog-content">
                            {error && <div className="form-error-card" role="alert">{error.message}</div>}
                            {!view && !error && <p className="seasons-dialog-muted">Loading the seasons…</p>}
                            {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}

                            {view && names && regs && (
                                <>
                                    {view.linkSeasonsOffered && (
                                        <section className="seasons-dialog-section" aria-labelledby="seasons-dialog-links">
                                            <div className="seasons-dialog-switch-row">
                                                <div>
                                                    <h3 id="seasons-dialog-links">{capitalized(names.many)} as seasons</h3>
                                                    <p className="seasons-dialog-muted">
                                                        Each {names.one} becomes a season of its own, with its {words.videos} in the
                                                        order the {names.one} has them.
                                                    </p>
                                                </div>
                                                <Controller control={control} name="linkSeasonsOn" render={({field}) => (
                                                    <Switch
                                                        id="seasons-link-seasons" checked={!!field.value || only} onChange={field.onChange}
                                                        disabled={only}
                                                        aria-labelledby="seasons-dialog-links"
                                                        onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                                                    />
                                                )}/>
                                            </div>
                                            {errors.linkSeasonsOn && <div className="error" role="alert">{errors.linkSeasonsOn.message}</div>}

                                            {(linkSeasonsOn || only) && (
                                                <>
                                                    {view.listsPlaylists && !view.creatorSlug && <div className="form-row">
                                                        <label htmlFor="seasons-link-mode">Which {names.many}</label>
                                                        <SimpleSelect
                                                            inputId="seasons-link-mode" registry={regs.mode} value={mode}
                                                            onChange={(value) => setValue('linkSeasonMode', value as CollectionSeasonsFormIn['linkSeasonMode'], {shouldDirty: true})}
                                                        />
                                                        <div className="help">{regs.mode.getHelp(mode)}</div>
                                                    </div>}

                                                    {mode === 'selected' && view.listsPlaylists && (
                                                        <div className="form-row">
                                                            <div className="seasons-dialog-list-header">
                                                                <label className="seasons-dialog-check">
                                                                    <input
                                                                        type="checkbox" checked={allEnabled}
                                                                        ref={(input) => { if (input) input.indeterminate = enabledCount > 0 && !allEnabled }}
                                                                        onChange={(event) => setAll(event.target.checked)}
                                                                        disabled={playlistChoices.length === 0}
                                                                    />
                                                                    <span>{allEnabled ? 'Deselect all' : 'Select all'}</span>
                                                                </label>
                                                                {!view.creatorSlug && (
                                                                    <button type="button" className="btn btn-small" onClick={() => void refreshPlaylists()} disabled={refreshing || !view.listsPlaylists}>
                                                                        <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} spin={refreshing} aria-hidden="true"/>
                                                                        <span>{refreshing ? 'Looking…' : `Look for new ${names.many}`}</span>
                                                                    </button>
                                                                )}
                                                            </div>
                                                            {playlistChoices.length === 0 ? (
                                                                <p className="seasons-dialog-muted">
                                                                    VODLoft has not listed the {names.many} yet. Look for them to pick which are seasons.
                                                                </p>
                                                            ) : (
                                                                <ul className="seasons-dialog-links">
                                                                    {playlistChoices.map((choice, index) => {
                                                                        const playlist = playlistsById.get(choice.id)
                                                                        if (!playlist || playlist.addedByUser) return null
                                                                        return (
                                                                            <li key={choice.id}>
                                                                                <label className="seasons-dialog-check">
                                                                                    <input
                                                                                        type="checkbox" checked={choice.enabled}
                                                                                        onChange={(event) => setValue(`playlists.${index}.enabled`, event.target.checked, {shouldDirty: true})}
                                                                                    />
                                                                                    <span className="seasons-dialog-link-copy">
                                                                                        <b>{playlist.title}</b>
                                                                                        <span>
                                                                                            {playlist.status === 'new' && <span className="seasons-dialog-badge">New</span>}
                                                                                            {[
                                                                                                playlist.itemCount !== null ? plural(playlist.itemCount, words.video, `${words.videos}`) : null,
                                                                                                playlist.firstVideoAt ? `since ${new Date(playlist.firstVideoAt).getFullYear()}` : null,
                                                                                            ].filter(Boolean).join(' · ')}
                                                                                        </span>
                                                                                    </span>
                                                                                </label>
                                                                            </li>
                                                                        )
                                                                    })}
                                                                </ul>
                                                            )}
                                                            {errors.playlists && <div className="error" role="alert">{String(errors.playlists.message ?? errors.playlists.root?.message)}</div>}
                                                        </div>
                                                    )}

                                                    {view.creatorSlug && (
                                                        <p className="seasons-dialog-muted">
                                                            The creator <Link to={`/creator/${view.creatorSlug}`}>{view.creatorTitle}</Link> looks
                                                            for new {names.many} once a day and decides what happens with them. Change that
                                                            on the creator's <Link to={`/edit-creator/${view.creatorSlug}`}>Edit</Link> page.
                                                        </p>
                                                    )}

                                                    {mode === 'selected' && view.listsPlaylists && !view.creatorSlug && (
                                                        <div className="form-row">
                                                            <label htmlFor="seasons-new-links">When the {words.creator} adds {/^[aeiou]/.test(names.one) ? 'an' : 'a'} {names.one}</label>
                                                            <SimpleSelect
                                                                inputId="seasons-new-links" registry={regs.newLinks} value={newLinkSeasons}
                                                                onChange={(value) => setValue('newLinkSeasons', value as CollectionSeasonsFormIn['newLinkSeasons'], {shouldDirty: true})}
                                                            />
                                                            <div className="help">{regs.newLinks.getHelp(newLinkSeasons)} VODLoft looks once a day.</div>
                                                        </div>
                                                    )}

                                                    <div className="form-row">
                                                        <label htmlFor="seasons-layout">{capitalized(names.many)}</label>
                                                        <SimpleSelect
                                                            inputId="seasons-layout" registry={regs.layout} value={listLayout}
                                                            onChange={(value) => setValue('listLayout', value as CollectionSeasonsFormIn['listLayout'], {shouldDirty: true})}
                                                        />
                                                        <div className="help">{regs.layout.getHelp(listLayout)}</div>
                                                    </div>

                                                    {!only && listLayout !== 'by_year' && <div className="form-row">
                                                        <label htmlFor="seasons-loose">{capitalized(words.videos)} in no {names.one}</label>
                                                        <SimpleSelect
                                                            inputId="seasons-loose" registry={regs.loose} value={looseVideos}
                                                            onChange={(value) => setValue('looseVideos', value as CollectionSeasonsFormIn['looseVideos'], {shouldDirty: true})}
                                                        />
                                                        <div className="help">{regs.loose.getHelp(looseVideos)}</div>
                                                    </div>}

                                                    {view.listsPlaylists ? (
                                                        <div className="form-row">
                                                            <label htmlFor="seasons-outside">What the collection holds</label>
                                                            <SimpleSelect
                                                                inputId="seasons-outside" registry={regs.outside} value={outsideVideos}
                                                                onChange={(value) => setValue('outsideVideos', value as CollectionSeasonsFormIn['outsideVideos'], {shouldDirty: true})}
                                                            />
                                                            <div className="help">
                                                                {outsideVideos === 'only' ? '' : `${capitalized(words.videos)} of other ${words.creators} in these ${names.many}: `}
                                                                {regs.outside.getHelp(outsideVideos)}
                                                            </div>
                                                            {errors.outsideVideos && <div className="error" role="alert">{errors.outsideVideos.message}</div>}
                                                        </div>
                                                    ) : (
                                                        <p className="seasons-dialog-muted">
                                                            This collection has no link of its own, so it holds only what the links you add have.
                                                        </p>
                                                    )}

                                                    {only && (
                                                        <div className="form-row">
                                                            <label htmlFor="seasons-add-link">Your links</label>
                                                            {addedLinks.length > 0 && (
                                                                <ul className="seasons-dialog-links">
                                                                    {addedLinks.map((link) => {
                                                                        const removed = removedLinks.includes(link.id)
                                                                        return (
                                                                            <li key={link.id} className={`seasons-dialog-added${removed ? ' is-removed' : ''}`}>
                                                                                <span className="seasons-dialog-link-copy">
                                                                                    <b>{link.title}</b>
                                                                                    <span>{removed ? 'Removed when you save' : link.url}</span>
                                                                                </span>
                                                                                <button
                                                                                    type="button" className="btn btn-small"
                                                                                    aria-label={`${removed ? 'Keep' : 'Remove'} ${link.title}`}
                                                                                    onClick={() => toggleRemoved(link.id)}
                                                                                >
                                                                                    {removed ? 'Keep' : 'Remove'}
                                                                                </button>
                                                                            </li>
                                                                        )
                                                                    })}
                                                                </ul>
                                                            )}
                                                            {view.outsideVideos === 'only' ? (
                                                                <div className="seasons-dialog-add-link">
                                                                    <input
                                                                        id="seasons-add-link" className="input" type="url" inputMode="url"
                                                                        placeholder="https://… a playlist, channel or video"
                                                                        aria-invalid={!!linkForm.formState.errors.url}
                                                                        {...linkForm.register('url')}
                                                                        onKeyDown={(event) => {
                                                                            if (event.key === 'Enter') {
                                                                                event.preventDefault()
                                                                                void addLink()
                                                                            }
                                                                        }}
                                                                    />
                                                                    <button type="button" className="btn btn-small" onClick={() => void addLink()} disabled={addingLink}>
                                                                        <FontAwesomeIcon icon={faIcon('fass', 'plus')} aria-hidden="true"/>
                                                                        <span>{addingLink ? 'Adding…' : 'Add'}</span>
                                                                    </button>
                                                                </div>
                                                            ) : (
                                                                <p className="seasons-dialog-muted">Save first, then add links of your own here.</p>
                                                            )}
                                                            {linkForm.formState.errors.url && <div className="error" role="alert">{linkForm.formState.errors.url.message}</div>}
                                                            <div className="help">
                                                                Each link becomes a season of its own, from any site VODLoft can read. A link is added
                                                                right away; VODLoft then lists its {words.videos}.
                                                            </div>
                                                        </div>
                                                    )}
                                                </>
                                            )}
                                        </section>
                                    )}

                                    <section className="seasons-dialog-section" aria-labelledby="seasons-dialog-order">
                                        <div className="seasons-dialog-switch-row">
                                            <div>
                                                <h3 id="seasons-dialog-order">Seasons</h3>
                                                <p className="seasons-dialog-muted">
                                                    {customOrder
                                                        ? 'In your own order. A new season goes last.'
                                                        : `In VODLoft's order: by date${names.one === 'album' ? ', albums as the artist orders them' : ''}. Drag a season to put them in your own order.`}
                                                    {' '}Reordering renumbers the seasons. Files keep their names until you rename the collection's files.
                                                </p>
                                            </div>
                                            {customOrder && (
                                                <button type="button" className="btn btn-small" onClick={() => setValue('customSeasonOrder', false, {shouldDirty: true})}>
                                                    Automatic order
                                                </button>
                                            )}
                                        </div>
                                        <ol className="seasons-dialog-seasons">
                                            {fields.map((field, index) => {
                                                const season = seasonsById.get(field.id)
                                                const extra = season?.seasonType === 'EXTRA' || season?.seasonType === 'extra'
                                                return (
                                                    <li
                                                        key={field.key}
                                                        className={`seasons-dialog-season${dragging === index ? ' is-dragging' : ''}`}
                                                        draggable
                                                        onDragStart={(event) => {
                                                            setDragging(index)
                                                            event.dataTransfer.effectAllowed = 'move'
                                                        }}
                                                        onDragOver={(event) => {
                                                            event.preventDefault()
                                                            if (dragging !== null && dragging !== index) {
                                                                moveSeason(dragging, index)
                                                                setDragging(index)
                                                            }
                                                        }}
                                                        onDragEnd={() => setDragging(null)}
                                                    >
                                                        <span className="seasons-dialog-grip" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/></span>
                                                        <span className="seasons-dialog-number" aria-hidden="true">{extra ? '0' : customOrder ? index + 1 : season?.seasonNumber}</span>
                                                        <span className="seasons-dialog-season-copy">
                                                            <input
                                                                className="input" aria-label={`Name of season ${index + 1}`}
                                                                aria-invalid={!!errors.seasons?.[index]?.name}
                                                                {...register(`seasons.${index}.name`)}
                                                            />
                                                            <span>
                                                                {plural(season?.episodeCount ?? 0, 'episode', 'episodes')}
                                                                {season?.loose ? ` · ${capitalized(words.videos)} in no ${names.one}` : null}
                                                            </span>
                                                            {season && listLayout !== 'by_year' && listSeasonIds.includes(season.id) && (
                                                                <SeasonLists
                                                                    season={field.id} names={names} lists={listsIn(field.id)}
                                                                    titles={playlistsById} joinRegistry={joinRegistry(field.id)}
                                                                    onJoin={(to) => joinSeason(field.id, to)} onOwn={ownSeason}
                                                                    joinsName={joinsName(field.id)}
                                                                />
                                                            )}
                                                            {errors.seasons?.[index]?.name && <span className="error" role="alert">{errors.seasons[index]?.name?.message}</span>}
                                                        </span>
                                                        <span className="seasons-dialog-arrows">
                                                            <button type="button" aria-label={`Move season ${index + 1} up`} disabled={index === 0} onClick={() => moveSeason(index, index - 1)}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                                            </button>
                                                            <button type="button" aria-label={`Move season ${index + 1} down`} disabled={index === fields.length - 1} onClick={() => moveSeason(index, index + 1)}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                                            </button>
                                                        </span>
                                                    </li>
                                                )
                                            })}
                                        </ol>
                                        {fields.length === 0 && <p className="seasons-dialog-muted">This collection has no seasons yet.</p>}
                                        {errors.seasons?.message && <div className="error" role="alert">{errors.seasons.message}</div>}
                                        {errors.seasons?.root?.message && <div className="error" role="alert">{errors.seasons.root.message}</div>}
                                    </section>
                                </>
                            )}
                        </div>
                        <div className="modal-actions">
                            <button type="button" className="btn" onClick={onDismiss} disabled={isSubmitting}>Cancel</button>
                            <button type="submit" className="btn btn-primary" disabled={!view || isSubmitting || !isDirty}>
                                {isSubmitting ? 'Saving…' : 'Save seasons'}
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            <ConfirmDialog
                open={confirm !== null}
                title="Remove episodes from the collection?"
                icon={faIcon('fass', 'triangle-exclamation')}
                iconTone="danger"
                onDismiss={() => setConfirm(null)}
                confirmButton={{
                    label: 'Remove and save',
                    className: 'btn btn-danger',
                    onClick: async () => {
                        setConfirm(null)
                        confirmed.current = true
                        await onSubmit()
                    },
                }}
            >
                {confirm && names && confirm.asked && (
                    <>
                        <p>
                            {plural(confirm.episodes, 'episode', 'episodes')} {confirm.episodes === 1 ? 'is' : 'are'} in
                            none of the {names.many} that are seasons. Once VODLoft has listed the {names.many} again,
                            {confirm.episodes === 1 ? ' it leaves' : ' they leave'} the collection.
                        </p>
                        {confirm.withFiles > 0 && (
                            <p>
                                <strong>{plural(confirm.withFiles, 'of them has', 'of them have')} downloaded files.</strong>{' '}
                                Those stay, marked Removed, and Home asks whether to keep them.
                            </p>
                        )}
                    </>
                )}
                {confirm && names && !confirm.asked && (
                    <>
                        <p>
                            {plural(confirm.episodes, 'episode', 'episodes')} came from {names.many} and not from the collection's
                            own link. {confirm.episodes === 1 ? 'It leaves' : 'They leave'} the collection with this change.
                        </p>
                        {confirm.withFiles > 0 && (
                            <p><strong>{plural(confirm.withFiles, 'downloaded file is', 'downloaded files are')} deleted too.</strong></p>
                        )}
                        <p>
                            The other {words.videos} of these {names.many} stay, and move to the season a new {words.video} would
                            go to. Their files are renamed into that season.
                        </p>
                    </>
                )}
            </ConfirmDialog>
        </>
    )
}


/** The lists of one season in the Seasons dialog: which playlists it holds, and putting it together with another. */
function SeasonLists({season, names, lists, titles, joinRegistry, onJoin, onOwn, joinsName}: {
    season: number
    names: CollectionSeasonsRead['names']
    lists: {id: number, seasonId: number | null}[]
    titles: Map<number, CollectionListRead>
    joinRegistry: SelectRegistry
    onJoin: (to: number) => void
    onOwn: (listId: number) => void
    joinsName: string | null
}) {
    if (lists.length === 0) {
        return <span className="seasons-dialog-joins">Its {names.many} move to {joinsName ?? 'another season'} when you save.</span>
    }
    return (
        <span className="seasons-dialog-season-lists">
            <span className="seasons-dialog-list-names">
                {lists.map((list) => (
                    <span key={list.id} className="seasons-dialog-list-name">
                        <span>{capitalized(names.one)} {titles.get(list.id)?.title ?? ''}</span>
                        {lists.length > 1 && (
                            <button type="button" className="btn btn-small" onClick={() => onOwn(list.id)}
                                    aria-label={`Give ${titles.get(list.id)?.title ?? `this ${names.one}`} a season of its own`}>
                                Own season
                            </button>
                        )}
                    </span>
                ))}
            </span>
            {joinRegistry.options.length > 1 && (
                <span className="seasons-dialog-join">
                    <label htmlFor={`seasons-join-${season}`}>Together with</label>
                    <SimpleSelect
                        inputId={`seasons-join-${season}`} registry={joinRegistry} value="own"
                        menuPortalTarget={document.body} menuPlacement="auto"
                        styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                        onChange={(value) => { if (value && value !== 'own') onJoin(Number(value)) }}
                    />
                </span>
            )}
        </span>
    )
}
