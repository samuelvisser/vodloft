import {useEffect, useId, useMemo, useRef, useState} from 'react'
import {Controller, useFieldArray, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Switch from 'react-switch'
import toast from '../../lib/toast'

import {apiUrl} from '../../lib/api'
import {faIcon} from '../../icons/faIcon'
import {removeEpisodePreviewFromStorage, removeSeasonsFromStorage} from '../../lib/cache'
import {episodeQueryKeys} from '../../lib/collectionQueryOptions'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry, type SelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import NewListSettings from '../common/NewListSettings'
import {capitalized, type ListKind} from '../../types/creator'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {BulkBar} from '../ProfileBulkEdit/BulkEditControls'
import {
    CollectionSeasonsFormSchema, CollectionSeasonsReadSchema, LinkSeasonAddFormSchema, seasonsFormValues,
    type CollectionListRead, type CollectionSeasonsFormIn, type CollectionSeasonsFormOut, type CollectionSeasonsRead,
    type LinkSeasonAddFormIn, type LinkSeasonAddFormOut, type NewLinkSeason, type ChannelSeason,
} from '../../types/schemas/collection_seasons'
import './SeasonsDialog.css'
import {collectionWords, CollectionWords, Noun, wordsOf} from '../../lib/collectionWords'

type Props = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    onDismiss: () => void
    /** Called after a save that left downloaded episodes in another season than the one they belong in now. */
    onMovesWaiting?: () => void
    /** What the collection calls its seasons and episodes, such as albums and music videos. */
    words?: CollectionWords
}

/** What saving removes: ``asked`` when the ones with files stay until Home asks about them. ``repeated`` counts the
 * episodes of videos in another season already, which leave once a video has one season only. */
type Leaving = {episodes: number, withFiles: number, asked?: boolean, repeated?: number}

/** A creator's videos, or an artist's tracks or music videos, and what the collection calls its seasons. In a Music
 * collection an artist's albums are albums here too, so ``here`` tells them apart where both are meant. */
type Words = {creator: string, channel: string, video: string, videos: string, creators: string, season: Noun, episode: Noun, inSeason: string, here: string}
const dialogWords = (collection: CollectionWords, view: CollectionSeasonsRead | undefined): Words => ({
    // What the collection calls its creator and what its lists hold, such as an artist's music videos.
    // Shown once the view is there, which brings the words.
    creator: view?.creatorNames.singular ?? '', creators: view?.creatorNames.plural ?? '', channel: view?.channelNames.singular ?? '',
    video: view?.mediaNames.singular ?? '', videos: view?.mediaNames.plural ?? '',
    season: collection.season, episode: collection.episode, inSeason: collection.inSeason,
    here: view && view.sectionListNames.singular === collection.season.singular ? ' here' : '',
})

/** What the collection's Site calls its lists, all its types of list together, such as "albums and playlists" on
 * SoundCloud, and the season of the videos in none of them. */
type ListNames = {singular: string, plural: string, a: string, looseSeason: string}
const namesOf = (view: CollectionSeasonsRead, looseSeason: string): ListNames => ({...view.sectionListNames, looseSeason})

const counted = (count: number, singular: string, plural: string) => `${count} ${count === 1 ? singular : plural}`

async function readSeasons(response: Response): Promise<CollectionSeasonsRead> {
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(typeof body?.detail === 'string' ? body.detail : `Could not load them (HTTP ${response.status})`)
    }
    return CollectionSeasonsReadSchema.parse(await response.json())
}

/** The registries of the dialog's selects, in the words of the collection's Site. */
function registries(names: ListNames, words: Words, view: CollectionSeasonsRead) {
    const outside = {
        leave_out: {label: 'Only include media already in the collection', help: `${capitalized(names.a)} only takes the ${words.videos} the collection's own link has.`},
        add: {label: 'Include media that is not in the collection', help: `They join the collection in their ${names.singular}'s ${words.season.singular}${words.here}. Switching a ${names.singular} or this setting off removes them again, files and all. When the ${words.creator} takes a downloaded one out, Home asks whether to keep it.`},
        only: {label: `Include only what the ${names.plural} contain`, help: `The collection holds nothing but the ${words.videos} of its ${names.plural}, also other ${words.creators}', and you can add links of your own, from any site. Its own ${words.videos} in no ${names.singular} leave.`},
    }
    return {
        mode: createSelectRegistry(`LinkSeasonMode-${names.plural}`, {
            all: {label: `Every ${names.singular}`, help: `Every ${names.singular}, also the ones to come, is ${words.season.a}${words.here}.`},
            selected: {label: `Only the ${names.plural} I pick`, help: `Only the ${names.plural} switched on below are ${words.season.plural}${words.here}.`},
        }),
        // One for each kind of list of the Site, such as a SoundCloud artist's albums and their playlists.
        newLinks: (kind: ListKind) => createSelectRegistry(`NewLinkSeasons-${kind.key}-${kind.names.singular}-${words.season.a}${words.here}`, {
            ask: {label: 'Ask me', help: `VODLoft sends a message, and the new ${kind.names.singular} waits here for you to switch it on.`},
            add: {label: `Make it ${words.season.a}${words.here}`, help: `A new ${kind.names.singular} becomes ${words.season.a}${words.here} right away.`},
            ignore: {label: 'Always skip it', help: `A new ${kind.names.singular} stays off. You can switch it on here.`},
        }),
        // What the channel's own season holds, by the name it then has.
        channel: createSelectRegistry(`ChannelSeason-${view.channelSeasonNames.everything}-${view.channelSeasonNames.unlisted}-${names.plural}`, {
            everything: {
                label: `Everything, as ${view.channelSeasonNames.everything}`,
                help: `Every ${words.video} of the feeds is in ${view.channelSeasonNames.everything}, also the ones in ${names.a} that is ${words.season.a}${words.here}.`,
            },
            unlisted: {
                label: `What is in no ${names.singular}, as ${view.channelSeasonNames.unlisted}`,
                help: `${capitalized(words.videos)} in ${names.a} that is ${words.season.a}${words.here} are only there.`,
            },
        } as Record<ChannelSeason, {label: string, help: string}>),
        layout: createSelectRegistry(`ListLayout-${names.plural}-${words.creator}-${words.season.a}`, {
            season_each: {label: words.here ? `Each ${names.singular} on its own` : `${capitalized(words.season.a)} per ${words.creator ? `${words.creator} ` : ''}${names.singular}`, help: `Each ${names.singular} is ${words.season.a}${words.here}, or shares one with the ${names.plural} you put together below.`},
            by_year: {label: `Together in ${words.season.plural} by year`, help: `The ${names.plural} still decide which ${words.videos} are in, but every ${words.video} goes to the ${words.season.singular} of its year, as do the ${words.videos} in no ${names.singular}. When you save, VODLoft offers to move the downloaded ones, files and all.`},
        }),
        loose: createSelectRegistry(`LooseVideos-${names.looseSeason}`, {
            one_season: {label: `One ${words.season.singular}, ${names.looseSeason}`, help: `They share one ${words.season.singular}, shown before the ${names.plural}.`},
            by_year: {label: `${capitalized(words.season.a)} per year`, help: `They get ${words.season.a} per upload year, with the ${names.plural} between them by date.`},
        }),
        // Whether a list is a season of its own, or only adds its videos to the collection's other seasons.
        placement: createSelectRegistry(`ListPlacement-${words.season.singular}-${words.videos}`, {
            season: {label: `${capitalized(words.season.a)} of its own`, help: `Its ${words.videos} are ${words.season.a} named after it.`},
            contents: {label: 'Contents only', help: `Its ${words.videos} join the other ${words.season.plural}, where ${words.videos} in no ${names.singular} go.`},
        }),
        // What the collection does with a video in several of its seasons, such as a track on several albums.
        repeat: createSelectRegistry(`RepeatVideos-${words.season.singular}-${words.inSeason}-${words.episode.singular}`, {
            one_season: {
                label: `Include it only ${words.inSeason} the first ${words.season.singular}`,
                help: `It gets one place, ${words.inSeason} the first of those ${words.season.plural} in the order below.`,
            },
            each_season: {
                label: `Include it ${words.inSeason} each ${words.season.singular}`,
                help: `It is ${words.inSeason} each of them, with files of its own, so every ${words.season.singular} is whole.`,
            },
        }),
        outside: createSelectRegistry(
            `OutsideVideos-${names.plural}-${view.listsPlaylists}-${view.linksOnlyOffered}`,
            // Holding only the playlists is offered where the Source can hold a collection of links.
            (view.linksOnlyOffered ? outside : {leave_out: outside.leave_out, add: outside.add}) as typeof outside,
        ),
    }
}

/** The Seasons dialog: rename and reorder a collection's seasons, and choose which of its creator's playlists are seasons. */
export default function SeasonsDialog({open, collectionSlug, collectionTitle, onDismiss, onMovesWaiting, words: collectionWordsGiven}: Props) {
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

    // What the Site calls its lists, such as playlists on YouTube, also in a Music collection, whose seasons are albums.
    const linkSeasonsOn = watch('linkSeasonsOn') ?? false
    const mode = watch('linkSeasonMode') ?? 'all'
    const playlistChoices = watch('playlists') ?? []
    // Bulk edit of the lists: which ones are chosen, by id, while it is on.
    const [bulk, setBulk] = useState(false)
    const [chosen, setChosen] = useState<ReadonlySet<number>>(new Set())
    const looseVideos = watch('looseVideos') ?? 'one_season'
    const listLayout = watch('listLayout') ?? 'season_each'
    const outsideVideos = watch('outsideVideos') ?? 'leave_out'
    const newLists = watch('newLists') ?? {}
    const feeds = watch('feeds') ?? []
    const channelSeason = watch('channelSeason') ?? 'everything'
    // A feed the collection took before is switched off now.
    const feedsOff = !!view && view.feeds.some((feed) => feed.on && !feeds.includes(feed.ref))
    const customOrder = watch('customSeasonOrder') ?? false
    const repeatVideos = watch('repeatVideos') ?? 'one_season'
    const removedLinks = watch('removedLinks') ?? []
    // The channel season is called Channel while it holds the whole channel, as the form is set now, so the names
    // follow the form before it is saved.
    const holdsWholeChannel = !!view && view.kind === 'channel' && view.feeds.length > 0 && outsideVideos !== 'only'
        && feeds.length > 0 && channelSeason === 'everything'
    const looseSeason = view ? view.channelSeasonNames[holdsWholeChannel ? 'everything' : 'unlisted'] : undefined
    const names = useMemo(() => view ? namesOf(view, looseSeason!) : undefined, [view, looseSeason])
    const words = dialogWords(collectionWordsGiven ?? (view ? wordsOf(view.words) : collectionWords(null)), view)
    const {season} = words
    const regs = useMemo(() => view && names ? registries(names, words, view) : null, [view, names, words])
    const only = outsideVideos === 'only'

    const leaving = (values: CollectionSeasonsFormOut): Leaving => {
        if (!view) return {episodes: 0, withFiles: 0}
        const repeated = view.repeatVideos === 'each_season' && values.repeatVideos === 'one_season' ? view.repeatedCount : 0
        return {...leavingByLists(values), repeated}
    }

    const leavingByLists = (values: CollectionSeasonsFormOut): Leaving => {
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
            // Every feed on is all of them, also the ones the channel adds later.
            ...(view?.kind === 'channel' ? {
                feeds: view.feeds.every((feed) => data.feeds.includes(feed.ref)) ? null : data.feeds,
                channelSeason: data.channelSeason,
            } : {}),
            linkSeasons: data.linkSeasonsOn || data.outsideVideos === 'only' ? data.linkSeasonMode : 'off',
            newLists: data.newLists,
            looseVideos: data.looseVideos,
            repeatVideos: data.repeatVideos,
            listLayout: data.listLayout,
            outsideVideos: data.outsideVideos,
            playlists: data.playlists,
            removedLinks: data.removedLinks,
        }),
    }), {
        parseSuccess: readSeasons,
        fallbackField: 'seasons',
        fieldAlias: {linkSeasons: 'linkSeasonsOn', removedLinks: 'playlists'},
        genericMessage: `Could not save the ${season.plural}`,
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
            toast.success(`${season.Plural} saved`)
            // Downloaded episodes that belong in another season now wait for the Move dialog, which the save opens.
            const moves = await fetch(`${endpoint}/moved-episodes`, {credentials: 'include'})
                .then((response) => response.ok ? response.json() : {episodeSlugs: []})
                .catch(() => ({episodeSlugs: []}))
            await queryClient.invalidateQueries({queryKey: ['collection', collectionSlug, 'movedEpisodes']})
            onDismiss()
            if ((moves.episodeSlugs ?? []).length > 0) onMovesWaiting?.()
        },
    })

    const onSubmit = form.handleSubmit((values) => {
        const going = leaving(values)
        if ((going.episodes > 0 || (going.repeated ?? 0) > 0) && !confirmed.current) {
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
                asSeason: choices.get(playlist.id)?.asSeason ?? playlist.asSeason,
                seasonId: choices.has(playlist.id) ? choices.get(playlist.id)!.seasonId : playlist.seasonId,
            })), {shouldDirty: true})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
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
                asSeason: choices.get(playlist.id)?.asSeason ?? playlist.asSeason,
                seasonId: choices.has(playlist.id) ? choices.get(playlist.id)!.seasonId : playlist.seasonId,
            })))
            setValue('seasons', fresh.seasons.map((season) => form.getValues('seasons')?.find((x) => x.id === season.id) ?? {id: season.id, name: season.name}))
            linkForm.reset({url: ''})
            toast.success(`Link added. VODLoft is listing its ${fresh.mediaNames.plural}.`)
        },
    })
    const addingLink = linkForm.formState.isSubmitting

    if (!open) return null
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
    const bulkIds = playlistChoices.filter((choice) => !playlistsById.get(choice.id)?.addedByUser).map((choice) => choice.id)
    const allChosen = bulkIds.length > 0 && bulkIds.every((id) => chosen.has(id))
    const toggleChosen = (id: number) => setChosen((current) => {
        const next = new Set(current)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
    })
    const stopBulk = () => {
        setBulk(false)
        setChosen(new Set())
    }
    /** Change the chosen lists in the form; nothing is saved until the dialog is. */
    const changeChosen = (change: {enabled?: boolean, asSeason?: boolean}) => setValue(
        'playlists', playlistChoices.map((choice) => chosen.has(choice.id) ? {...choice, ...change} : choice), {shouldDirty: true},
    )
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
                String(id), {label: form.getValues('seasons')?.find((x) => x.id === id)?.name ?? seasonsById.get(id)?.name ?? season.Singular},
            ]),
        ]) as Record<string, {label: string}>,
    )
    // Where the lists of a season go when every one of them left it.
    const joinsName = (seasonId: number) => {
        const first = (view?.playlists ?? []).find((playlist) => playlist.seasonId === seasonId)
        const target = first ? playlistChoices.find((choice) => choice.id === first.id)?.seasonId : null
        if (!target) return `${season.a} of its own`
        return form.getValues('seasons')?.find((x) => x.id === target)?.name ?? `another ${season.singular}`
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
                        <h2 id={titleId} className="modal-title">{season.Plural} of {collectionTitle}</h2>
                    </div>
                    <form onSubmit={onSubmit} noValidate>
                        <div className="seasons-dialog-content">
                            {error && <div className="form-error-card" role="alert">{error.message}</div>}
                            {!view && !error && <p className="seasons-dialog-muted">Loading the {season.plural}…</p>}
                            {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}

                            {view && names && regs && (
                                <>
                                    {view.kind === 'channel' && view.feeds.length > 0 && (
                                        <section className="seasons-dialog-section" aria-labelledby="seasons-dialog-feeds">
                                            <h3 id="seasons-dialog-feeds">Feeds</h3>
                                            <p className="seasons-dialog-muted">
                                                The parts of the {words.channel} the collection takes its {words.videos} from.
                                            </p>
                                            <ul className="seasons-dialog-links">
                                                {view.feeds.map((feed) => (
                                                    <li key={feed.ref}>
                                                        <label className="seasons-dialog-check">
                                                            <input
                                                                type="checkbox" checked={feeds.includes(feed.ref)}
                                                                onChange={(event) => setValue('feeds', event.target.checked
                                                                    ? view.feeds.map((item) => item.ref).filter((ref) => ref === feed.ref || feeds.includes(ref))
                                                                    : feeds.filter((ref) => ref !== feed.ref), {shouldDirty: true})}
                                                            />
                                                            <span className="seasons-dialog-link-copy"><b>{capitalized(feed.names.plural)}</b></span>
                                                        </label>
                                                    </li>
                                                ))}
                                            </ul>
                                            {feedsOff && (
                                                <div className="help">
                                                    The {words.channel} is listed again when you save. Its {words.videos} that no feed or {names.singular} it
                                                    takes has leave; downloaded ones stay until Home asks whether to keep them.
                                                </div>
                                            )}
                                            {errors.feeds && <div className="error" role="alert">{String(errors.feeds.message ?? errors.feeds.root?.message)}</div>}

                                            <div className="form-row">
                                                <label htmlFor="seasons-channel-season">The {words.channel}'s own {season.singular}</label>
                                                <SimpleSelect
                                                    menuPortalTarget={document.body} menuPlacement="auto"
                                                    styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                    inputId="seasons-channel-season" registry={regs.channel} value={channelSeason}
                                                    onChange={(value) => setValue('channelSeason', value as ChannelSeason, {shouldDirty: true})}
                                                />
                                                <div className="help">{regs.channel.getHelp(channelSeason)}</div>
                                                {errors.channelSeason && <div className="error" role="alert">{errors.channelSeason.message}</div>}
                                            </div>
                                        </section>
                                    )}

                                    {view.linkSeasonsOffered && (
                                        <section className="seasons-dialog-section" aria-labelledby="seasons-dialog-links">
                                            <div className="seasons-dialog-switch-row">
                                                <div>
                                                    <h3 id="seasons-dialog-links">
                                                        {words.here || view.siteOrder ? `The ${words.creator}'s ${names.plural}` : `${capitalized(names.plural)} as ${season.plural}`}
                                                    </h3>
                                                    <p className="seasons-dialog-muted">
                                                        Each {names.singular} becomes {season.a}{words.here} of its own, with its {words.videos} in the
                                                        order the {names.singular} has them.
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
                                                    {view.listsPlaylists && <div className="form-row">
                                                        <label htmlFor="seasons-link-mode">Which {names.plural}</label>
                                                        <SimpleSelect
                                                            menuPortalTarget={document.body} menuPlacement="auto"
                                                            styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                            inputId="seasons-link-mode" registry={regs.mode} value={mode}
                                                            onChange={(value) => setValue('linkSeasonMode', value as CollectionSeasonsFormIn['linkSeasonMode'], {shouldDirty: true})}
                                                        />
                                                        <div className="help">{regs.mode.getHelp(mode)}</div>
                                                    </div>}

                                                    {mode === 'selected' && view.listsPlaylists && (
                                                        <div className="form-row">
                                                            <div className="seasons-dialog-list-header">
                                                                {bulk ? (
                                                                    <label className="seasons-dialog-check">
                                                                        <input
                                                                            type="checkbox" className="bulk-check" checked={allChosen}
                                                                            ref={(input) => { if (input) input.indeterminate = chosen.size > 0 && !allChosen }}
                                                                            onChange={() => setChosen(allChosen ? new Set() : new Set(bulkIds))}
                                                                            disabled={bulkIds.length === 0}
                                                                        />
                                                                        <span>{allChosen ? 'Deselect all' : 'Select all'}</span>
                                                                    </label>
                                                                ) : (
                                                                    <label className="seasons-dialog-check">
                                                                        <input
                                                                            type="checkbox" checked={allEnabled}
                                                                            ref={(input) => { if (input) input.indeterminate = enabledCount > 0 && !allEnabled }}
                                                                            onChange={(event) => setAll(event.target.checked)}
                                                                            disabled={playlistChoices.length === 0}
                                                                        />
                                                                        <span>{allEnabled ? 'Deselect all' : 'Select all'}</span>
                                                                    </label>
                                                                )}
                                                                <span className="seasons-dialog-list-tools">
                                                                <button
                                                                    type="button" className={`btn btn-small${bulk ? ' is-toggled' : ''}`} aria-pressed={bulk}
                                                                    onClick={() => bulk ? stopBulk() : setBulk(true)} disabled={bulkIds.length === 0}
                                                                >
                                                                    <FontAwesomeIcon icon={faIcon('fass', bulk ? 'check' : 'list-check')} aria-hidden="true"/>
                                                                    <span>{bulk ? 'Done' : 'Bulk edit'}</span>
                                                                </button>
                                                                <button type="button" className="btn btn-small" onClick={() => void refreshPlaylists()} disabled={refreshing || !view.listsPlaylists}>
                                                                    <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} spin={refreshing} aria-hidden="true"/>
                                                                    <span>{refreshing ? 'Looking…' : `Look for new ${names.plural}`}</span>
                                                                </button>
                                                                </span>
                                                            </div>
                                                            {playlistChoices.length === 0 ? (
                                                                <p className="seasons-dialog-muted">
                                                                    VODLoft has not listed the {names.plural} yet. Look for them to pick which are seasons.
                                                                </p>
                                                            ) : (
                                                                <ul className="seasons-dialog-links">
                                                                    {playlistChoices.map((choice, index) => {
                                                                        const playlist = playlistsById.get(choice.id)
                                                                        if (!playlist || playlist.addedByUser) return null
                                                                        return (
                                                                            <li key={choice.id} className={bulk && chosen.has(choice.id) ? 'is-selected' : undefined}>
                                                                                <label className="seasons-dialog-check">
                                                                                    {bulk ? (
                                                                                        <input
                                                                                            type="checkbox" className="bulk-check" checked={chosen.has(choice.id)}
                                                                                            aria-label={`Choose ${playlist.title}`} onChange={() => toggleChosen(choice.id)}
                                                                                        />
                                                                                    ) : (
                                                                                        <input
                                                                                            type="checkbox" checked={choice.enabled}
                                                                                            onChange={(event) => setValue(`playlists.${index}.enabled`, event.target.checked, {shouldDirty: true})}
                                                                                        />
                                                                                    )}
                                                                                    <span className="seasons-dialog-link-copy">
                                                                                        <b>{playlist.title}</b>
                                                                                        <span>
                                                                                            {playlist.status === 'new' && <span className="seasons-dialog-badge">New</span>}
                                                                                            {[
                                                                                                bulk ? (choice.enabled ? (only ? 'On' : regs.placement.getLabel(choice.asSeason ? 'season' : 'contents')) : 'Off') : null,
                                                                                                playlist.itemCount !== null ? counted(playlist.itemCount, words.video, `${words.videos}`) : null,
                                                                                                playlist.firstVideoAt ? `since ${new Date(playlist.firstVideoAt).getFullYear()}` : null,
                                                                                            ].filter(Boolean).join(' · ')}
                                                                                        </span>
                                                                                    </span>
                                                                                </label>
                                                                                {!bulk && choice.enabled && !only && (
                                                                                    <div className="seasons-dialog-link-placement">
                                                                                        <SimpleSelect
                                                                                            menuPortalTarget={document.body} menuPlacement="auto"
                                                                                            styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                                                            inputId={`seasons-placement-${choice.id}`} aria-label={`What ${playlist.title} is`}
                                                                                            registry={regs.placement} value={choice.asSeason ? 'season' : 'contents'}
                                                                                            onChange={(value) => setValue(`playlists.${index}.asSeason`, value !== 'contents', {shouldDirty: true})}
                                                                                        />
                                                                                    </div>
                                                                                )}
                                                                            </li>
                                                                        )
                                                                    })}
                                                                </ul>
                                                            )}
                                                            {errors.playlists && <div className="error" role="alert">{String(errors.playlists.message ?? errors.playlists.root?.message)}</div>}
                                                            {bulk && (
                                                                <BulkBar
                                                                    count={chosen.size} prompt={`Choose ${names.plural} to change`}
                                                                    onClear={() => setChosen(new Set())} onStop={stopBulk}
                                                                >
                                                                    <button type="button" className="btn" disabled={!chosen.size} onClick={() => changeChosen({enabled: true})}>
                                                                        <FontAwesomeIcon icon={faIcon('fass', 'toggle-on')} aria-hidden="true"/> Switch on
                                                                    </button>
                                                                    <button type="button" className="btn" disabled={!chosen.size} onClick={() => changeChosen({enabled: false})}>
                                                                        <FontAwesomeIcon icon={faIcon('fass', 'toggle-off')} aria-hidden="true"/> Switch off
                                                                    </button>
                                                                    {!only && (
                                                                        <>
                                                                            <button type="button" className="btn" disabled={!chosen.size} onClick={() => changeChosen({enabled: true, asSeason: true})}>
                                                                                <FontAwesomeIcon icon={faIcon('fass', 'layer-group')} aria-hidden="true"/> {regs.placement.getLabel('season')}
                                                                            </button>
                                                                            <button type="button" className="btn" disabled={!chosen.size} onClick={() => changeChosen({enabled: true, asSeason: false})}>
                                                                                <FontAwesomeIcon icon={faIcon('fass', 'list')} aria-hidden="true"/> Contents only
                                                                            </button>
                                                                        </>
                                                                    )}
                                                                </BulkBar>
                                                            )}
                                                            {bulk && <div className="help">The changes are saved with the rest of the dialog.</div>}
                                                        </div>
                                                    )}

                                                    {mode === 'selected' && view.listsPlaylists && (
                                                        <div className="form-row">
                                                            <label>When the {words.creator} adds {names.a}</label>
                                                            <NewListSettings
                                                                kinds={view.newLists} valueOf={(kind) => newLists[kind.key]}
                                                                fallback="ask" idPrefix="seasons-new-links" registryFor={regs.newLinks}
                                                                onChange={(kind, value) => setValue('newLists', {...newLists, [kind.key]: value as NewLinkSeason}, {shouldDirty: true})}
                                                            />
                                                            {errors.newLists && <div className="error" role="alert">{(errors.newLists as {message?: string}).message}</div>}
                                                            <div className="help">VODLoft looks once a day.</div>
                                                        </div>
                                                    )}

                                                    <div className="form-row">
                                                        <label htmlFor="seasons-layout">{capitalized(names.plural)}</label>
                                                        <SimpleSelect
                                                            menuPortalTarget={document.body} menuPlacement="auto"
                                                            styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                            inputId="seasons-layout" registry={regs.layout} value={listLayout}
                                                            onChange={(value) => setValue('listLayout', value as CollectionSeasonsFormIn['listLayout'], {shouldDirty: true})}
                                                        />
                                                        <div className="help">{regs.layout.getHelp(listLayout)}</div>
                                                    </div>

                                                    {!only && listLayout !== 'by_year' && <div className="form-row">
                                                        <label htmlFor="seasons-loose">{capitalized(words.videos)} in no {names.singular}</label>
                                                        <SimpleSelect
                                                            menuPortalTarget={document.body} menuPlacement="auto"
                                                            styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                            inputId="seasons-loose" registry={regs.loose} value={looseVideos}
                                                            onChange={(value) => setValue('looseVideos', value as CollectionSeasonsFormIn['looseVideos'], {shouldDirty: true})}
                                                        />
                                                        <div className="help">{regs.loose.getHelp(looseVideos)}</div>
                                                    </div>}

                                                    {view.listsPlaylists ? (
                                                        <div className="form-row">
                                                            <label htmlFor="seasons-outside">How {names.singular} content fits in the collection</label>
                                                            <SimpleSelect
                                                                menuPortalTarget={document.body} menuPlacement="auto"
                                                                styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                                inputId="seasons-outside" registry={regs.outside} value={outsideVideos}
                                                                onChange={(value) => setValue('outsideVideos', value as CollectionSeasonsFormIn['outsideVideos'], {shouldDirty: true})}
                                                            />
                                                            <div className="help">
                                                                {outsideVideos === 'only' ? '' : `${capitalized(words.videos)} of other ${words.creators} in these ${names.plural}: `}
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
                                                                        placeholder="https://…"
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
                                                                Each link becomes {words.season.a} of its own, from any site VODLoft can read. A link is added
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
                                                <h3 id="seasons-dialog-order">{season.Plural}</h3>
                                                <p className="seasons-dialog-muted">
                                                    {customOrder
                                                        ? `In your own order. A new ${season.singular} goes last.`
                                                        : `In VODLoft's order: by date${view.siteOrder ? `, ${season.plural} as the ${words.creator} orders them` : ''}. Drag ${season.a} to put them in your own order.`}
                                                    {' '}Reordering renumbers the {season.plural}. Files keep their names until you rename the collection's files.
                                                </p>
                                            </div>
                                            {customOrder && (
                                                <button type="button" className="btn btn-small" onClick={() => setValue('customSeasonOrder', false, {shouldDirty: true})}>
                                                    Automatic order
                                                </button>
                                            )}
                                        </div>
                                        {regs && (
                                            <div className="form-row">
                                                <label htmlFor="seasons-repeat">
                                                    When {words.episode.a} belongs {words.inSeason} several {season.plural}
                                                </label>
                                                <SimpleSelect
                                                    menuPortalTarget={document.body} menuPlacement="auto"
                                                    styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                    inputId="seasons-repeat" registry={regs.repeat} value={repeatVideos}
                                                    onChange={(value) => setValue('repeatVideos', value as CollectionSeasonsFormIn['repeatVideos'], {shouldDirty: true})}
                                                />
                                                <div className="help">{regs.repeat.getHelp(repeatVideos)}</div>
                                                {errors.repeatVideos && <div className="error" role="alert">{errors.repeatVideos.message}</div>}
                                            </div>
                                        )}
                                        <ol className="seasons-dialog-seasons">
                                            {fields.map((field, index) => {
                                                const season = seasonsById.get(field.id)
                                                const extra = season?.seasonType === 'extra'
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
                                                                className="input" aria-label={`Name of ${words.season.singular} ${index + 1}`}
                                                                aria-invalid={!!errors.seasons?.[index]?.name}
                                                                {...register(`seasons.${index}.name`)}
                                                            />
                                                            <span>
                                                                {counted(season?.episodeCount ?? 0, words.video, words.videos)}
                                                                {season?.loose ? ` · ${capitalized(words.videos)} in no ${names.singular}` : null}
                                                            </span>
                                                            {season && listLayout !== 'by_year' && listSeasonIds.includes(season.id) && (
                                                                <SeasonLists
                                                                    season={field.id} names={names} words={words} lists={listsIn(field.id)}
                                                                    titles={playlistsById} joinRegistry={joinRegistry(field.id)}
                                                                    onJoin={(to) => joinSeason(field.id, to)} onOwn={ownSeason}
                                                                    joinsName={joinsName(field.id)}
                                                                />
                                                            )}
                                                            {errors.seasons?.[index]?.name && <span className="error" role="alert">{errors.seasons[index]?.name?.message}</span>}
                                                        </span>
                                                        <span className="seasons-dialog-arrows">
                                                            <button type="button" aria-label={`Move ${words.season.singular} ${index + 1} up`} disabled={index === 0} onClick={() => moveSeason(index, index - 1)}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                                            </button>
                                                            <button type="button" aria-label={`Move ${words.season.singular} ${index + 1} down`} disabled={index === fields.length - 1} onClick={() => moveSeason(index, index + 1)}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                                            </button>
                                                        </span>
                                                    </li>
                                                )
                                            })}
                                        </ol>
                                        {fields.length === 0 && <p className="seasons-dialog-muted">This collection has no {season.plural} yet.</p>}
                                        {errors.seasons?.message && <div className="error" role="alert">{errors.seasons.message}</div>}
                                        {errors.seasons?.root?.message && <div className="error" role="alert">{errors.seasons.root.message}</div>}
                                    </section>
                                </>
                            )}
                        </div>
                        <div className="modal-actions">
                            <button type="button" className="btn" onClick={onDismiss} disabled={isSubmitting}>Cancel</button>
                            <button type="submit" className="btn btn-primary" disabled={!view || isSubmitting || !isDirty}>
                                {isSubmitting ? 'Saving…' : `Save ${season.plural}`}
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            <ConfirmDialog
                open={confirm !== null}
                title={`Remove ${words.videos} from the collection?`}
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
                {confirm && names && confirm.asked && confirm.episodes > 0 && (
                    <>
                        <p>
                            {counted(confirm.episodes, words.video, words.videos)} {confirm.episodes === 1 ? 'is' : 'are'} in
                            none of the {names.plural} that are {season.plural}{words.here}. Once VODLoft has listed the {names.plural} again,
                            {confirm.episodes === 1 ? ' it leaves' : ' they leave'} the collection.
                        </p>
                        {confirm.withFiles > 0 && (
                            <p>
                                <strong>{counted(confirm.withFiles, 'of them has', 'of them have')} downloaded files.</strong>{' '}
                                Those stay, marked Removed, and Home asks whether to keep them.
                            </p>
                        )}
                    </>
                )}
                {confirm && (confirm.repeated ?? 0) > 0 && (
                    <p>
                        {counted(confirm.repeated ?? 0, words.episode.singular, words.episode.plural)} of{' '}
                        {(confirm.repeated ?? 0) === 1 ? `${words.episode.a} that is` : `${words.episode.plural} that are`} {words.inSeason} another{' '}
                        {season.singular} too {(confirm.repeated ?? 0) === 1 ? 'leaves' : 'leave'} the collection. Downloaded ones stay
                        until Home asks whether to keep them.
                    </p>
                )}
                {confirm && names && !confirm.asked && confirm.episodes > 0 && (
                    <>
                        <p>
                            {counted(confirm.episodes, words.video, words.videos)} came from {names.plural} and not from the collection's
                            own link. {confirm.episodes === 1 ? 'It leaves' : 'They leave'} the collection with this change.
                        </p>
                        {confirm.withFiles > 0 && (
                            <p><strong>{counted(confirm.withFiles, 'downloaded file is', 'downloaded files are')} deleted too.</strong></p>
                        )}
                        <p>
                            The other {words.videos} of these {names.plural} stay, and move to the {season.singular} a new {words.video} would
                            go to. Their files are renamed into that {season.singular}.
                        </p>
                    </>
                )}
            </ConfirmDialog>
        </>
    )
}


/** The lists of one season in the Seasons dialog: which playlists it holds, and putting it together with another. */
function SeasonLists({season, names, words, lists, titles, joinRegistry, onJoin, onOwn, joinsName}: {
    season: number
    names: ListNames
    words: Words
    lists: {id: number, seasonId: number | null}[]
    titles: Map<number, CollectionListRead>
    joinRegistry: SelectRegistry
    onJoin: (to: number) => void
    onOwn: (listId: number) => void
    joinsName: string | null
}) {
    if (lists.length === 0) {
        return <span className="seasons-dialog-joins">Its {names.plural} move to {joinsName ?? `another ${words.season.singular}`} when you save.</span>
    }
    return (
        <span className="seasons-dialog-season-lists">
            <span className="seasons-dialog-list-names">
                {lists.map((list) => (
                    <span key={list.id} className="seasons-dialog-list-name">
                        <span>{capitalized(names.singular)} {titles.get(list.id)?.title ?? ''}</span>
                        {lists.length > 1 && (
                            <button type="button" className="btn btn-small" onClick={() => onOwn(list.id)}
                                    aria-label={`Give ${titles.get(list.id)?.title ?? `this ${names.singular}`} ${words.season.a} of its own`}>
                                Own {words.season.singular}
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
