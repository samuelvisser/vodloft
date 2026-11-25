import {Fragment, type ReactNode, useEffect, useId, useMemo, useRef, useState} from 'react'
import {Controller, useFieldArray, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {keepPreviousData, useQuery, useQueryClient} from '@tanstack/react-query'
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
import {capitalized} from '../../types/creator'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {useDismissOnEscape} from '../Modal/useDismissOnEscape'
import SegmentedOptions from '../SegmentedOptions/SegmentedOptions'
import {
    AddedLinkReadSchema, type AddedLinkRead, CollectionSeasonsFormSchema, LinkSeasonAddFormSchema, SeasonsPreviewReadSchema, seasonsFormValues, type SeasonsPreviewRead,
    type CollectionListRead, type CollectionSeasonsFormIn, type CollectionSeasonsFormOut, type CollectionSeasonsRead,
    type LinkSeasonAddFormIn, type LinkSeasonAddFormOut, type NewLinkSeason, type CollectionSeasonRead,
} from '../../types/schemas/collection_seasons'
import './SeasonsDialog.css'
import {dialogWords, namesOf, readSeasons, registries, type SourceRole, type Words} from './seasonsSettings'
import {collectionWords, CollectionWords, wordsOf} from '../../lib/collectionWords'
import {nameInText} from '../../lib/nameInText'

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

/** What saving removes: ``afterListing`` when they leave once VODLoft has listed the lists again. ``repeated`` counts the
 * episodes of videos in another season already, which leave once a video has one season only. */
type Leaving = {episodes: number, withFiles: number, afterListing?: boolean, repeated?: number}

const counted = (count: number, singular: string, plural: string) => `${count} ${count === 1 ? singular : plural}`

/** Names in a sentence: A, B and C. */
function listed(names: string[]): string {
    return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
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
    // The boxes of What's in the collection that are folded shut: the lists start shut while they are off.
    const [shut, setShut] = useState<{feeds: boolean, lists: boolean}>({feeds: false, lists: false})
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
        const first = loadedFor.current === null
        loadedFor.current = view
        // A fresh answer while the dialog is open, such as the seasons a link got once VODLoft listed its videos,
        // keeps what the user changed already.
        if (first) setShut({feeds: false, lists: view.linkSeasons === 'off' && view.hasOwnLink})
        if (first || !isDirty) reset(seasonsFormValues(view))
        else keepChoices(view)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, view, reset])

    /** Show what the server answered without resetting the form to it, which would undo the user's unsaved changes.
     * The cache keeps its own copy of the answer, so that copy is the one the form counts as loaded. */
    const keepLoaded = (fresh: CollectionSeasonsRead) => {
        loadedFor.current = queryClient.setQueryData<CollectionSeasonsRead>(queryKey, fresh) ?? fresh
    }
    /** Take the lists and seasons of a fresh answer into the form, keeping what the user changed in the dialog. */
    const keepChoices = (fresh: CollectionSeasonsRead) => {
        const choices = new Map((form.getValues('playlists') ?? []).map((choice) => [choice.id, choice]))
        setValue('playlists', fresh.playlists.map((playlist) => ({
            id: playlist.id, enabled: choices.get(playlist.id)?.enabled ?? playlist.enabled,
            asSeason: choices.get(playlist.id)?.asSeason ?? playlist.asSeason,
            seasonId: choices.has(playlist.id) ? choices.get(playlist.id)!.seasonId : playlist.seasonId,
            isDefault: choices.get(playlist.id)?.isDefault ?? playlist.isDefault,
        })))
        setValue('seasons', fresh.seasons.map((season) => form.getValues('seasons')?.find((x) => x.id === season.id) ?? {id: season.id, name: season.name}))
    }

    const linkSeasonsOn = watch('linkSeasonsOn') ?? false
    const playlistChoices = watch('playlists') ?? []
    const looseVideos = watch('looseVideos') ?? 'one_season'
    const outsideVideos = watch('outsideVideos') ?? 'leave_out'
    const newLists = watch('newLists') ?? {}
    const feeds = watch('feeds') ?? []
    const feedSeasons = watch('feedSeasons') ?? {}
    // A feed the collection took before is switched off now.
    const feedsOff = !!view && view.feeds.some((feed) => feed.on && !feeds.includes(feed.ref))
    const customOrder = watch('customSeasonOrder') ?? false
    const repeatVideos = watch('repeatVideos') ?? 'one_season'
    const removedLinks = watch('removedLinks') ?? []
    const newLinks = watch('addedLinks') ?? []
    const removedSeasons = watch('removedSeasons') ?? []
    // The feeds of the collection's channel, when its own link is one.
    const channelFeeds = view && view.kind === 'channel' && view.hasOwnLink ? view.feeds : []
    // The collection holds only what its lists and links have: it has no link of its own, or every feed of its
    // channel is off while its lists are on.
    const only = !!view && (!view.hasOwnLink
        || (channelFeeds.length > 0 ? view.linkSeasonsOffered && linkSeasonsOn && feeds.length === 0 : outsideVideos === 'only'))
    // What the collection does with the videos of other creators in its lists, when it has videos of its own.
    const guests = outsideVideos === 'only' ? 'leave_out' : outsideVideos
    const listsOn = linkSeasonsOn || only
    /** What each source is now: a season of its own, part of the collection, or off. */
    const roleOfList = (choice: {id: number, enabled: boolean, asSeason?: boolean}): SourceRole =>
        !listsOn || !choice.enabled || removedLinks.includes(choice.id) ? 'off' : choice.asSeason !== false ? 'season' : 'part'
    // What a list is set to, also while the lists are switched off, when the box shows it dimmed.
    const setRoleOfList = (choice: {id: number, enabled: boolean, asSeason?: boolean}): SourceRole =>
        !choice.enabled || removedLinks.includes(choice.id) ? 'off' : choice.asSeason !== false ? 'season' : 'part'
    const roleOfFeed = (ref: string): SourceRole => !feeds.includes(ref) ? 'off' : ref in feedSeasons ? 'season' : 'part'
    const anyListSeason = playlistChoices.some((choice) => roleOfList(choice) === 'season')
    const anyPart = channelFeeds.some((feed) => roleOfFeed(feed.ref) === 'part')
        || playlistChoices.some((choice) => roleOfList(choice) === 'part')
    // A channel collection's own videos can be in one season of their own, the channel season, as the form is set now.
    const channelSeasonOffered = !!view && view.kind === 'channel' && view.listsPlaylists && view.hasOwnLink
        && !only && feeds.length > 0
    const byYear = looseVideos === 'by_year'
    // With no list a season of its own, the channel season holds the whole channel, whichever way it was set.
    const holdsWholeChannel = channelSeasonOffered && !byYear && (looseVideos === 'everything' || !anyListSeason)
    const looseSeason = view ? view.channelSeasonNames[holdsWholeChannel ? 'everything' : 'one_season'] : undefined
    const names = useMemo(() => view ? namesOf(view, looseSeason!) : undefined, [view, looseSeason])
    const words = dialogWords(collectionWordsGiven ?? (view ? wordsOf(view.words) : collectionWords(null)), view)
    const {season} = words
    const regs = useMemo(() => view && names ? registries(names, words, view) : null, [view, names, words])
    // Where what is part of the collection goes, which a collection made from one list always chooses.
    const showRest = !!view && (view.madeFromList || ((channelSeasonOffered || only) && anyPart))
    // Whether the channel season also holds what has a season of its own, which only lists can have besides it.
    const showAlsoHolds = channelSeasonOffered && !byYear && anyListSeason && anyPart
    // Only lists that are a season of their own put a video in several seasons.
    const showRepeat = listsOn && anyListSeason

    const leaving = (values: CollectionSeasonsFormOut): Leaving => {
        if (!view) return {episodes: 0, withFiles: 0}
        const repeated = view.repeatVideos === 'each_season' && values.repeatVideos === 'one_season' ? view.repeatedCount : 0
        return {...leavingByLists(values), repeated}
    }

    const leavingByLists = (values: CollectionSeasonsFormOut): Leaving => {
        if (!view) return {episodes: 0, withFiles: 0}
        if (only && view.outsideVideos !== 'only') {
            // The lists are listed again first; then what none of them has leaves, downloaded ones with their files.
            return {episodes: view.onlyLeavingCount, withFiles: view.onlyLeavingWithFiles, afterListing: true}
        }
        if (view.linkSeasons === 'off') return {episodes: 0, withFiles: 0}
        if (!listsOn || (view.outsideVideos === 'add' && values.outsideVideos === 'leave_out')) {
            return {episodes: view.outsideCount, withFiles: view.outsideWithFiles}
        }
        const enabled = new Map(values.playlists.map((choice) => [choice.id, choice.enabled]))
        const removed = new Set(values.removedLinks)
        return view.playlists
            .filter((playlist) => playlist.enabled && playlist.status === 'known'
                && (removed.has(playlist.id) || !enabled.get(playlist.id)))
            .reduce((sum, playlist) => ({
                episodes: sum.episodes + playlist.leavingCount, withFiles: sum.withFiles + playlist.leavingWithFiles,
            }), {episodes: 0, withFiles: 0})
    }

    /** What saving the dialog sends. */
    const requestBody = (data: CollectionSeasonsFormOut) => ({
        seasons: data.seasons,
        customSeasonOrder: data.customSeasonOrder,
        // Every feed on is all of them, also the ones the channel adds later.
        ...(view?.kind === 'channel' ? {
            feeds: view.feeds.length > 0 && view.feeds.every((feed) => data.feeds.includes(feed.ref)) ? null : data.feeds,
            feedSeasons: Object.fromEntries(Object.entries(data.feedSeasons).filter(([ref]) => data.feeds.includes(ref))),
        } : {}),
        linkSeasons: data.linkSeasonsOn || only ? 'on' : 'off',
        newLists: data.newLists,
        looseVideos: data.looseVideos,
        repeatVideos: data.repeatVideos,
        outsideVideos: only ? 'only' : data.outsideVideos === 'only' ? 'leave_out' : data.outsideVideos,
        playlists: data.playlists,
        removedLinks: data.removedLinks,
        addedLinks: data.linkSeasonsOn || only ? data.addedLinks.map((link) => link.url) : [],
        removedSeasons: data.removedSeasons,
    })

    // The seasons saving the dialog would leave, as the server works them out, so the list below shows a change
    // as soon as it is made. The names play no part in it, so typing one asks nothing.
    const formValues = watch()
    const previewBody = useMemo(() => {
        if (!view || !isDirty) return null
        const parsed = CollectionSeasonsFormSchema.safeParse(formValues)
        if (!parsed.success) return null
        const named = new Map(view.seasons.map((x) => [x.id, x.name]))
        return JSON.stringify(requestBody({
            ...parsed.data, seasons: parsed.data.seasons.map((x) => ({id: x.id, name: named.get(x.id) ?? x.name})),
        }))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [view, isDirty, JSON.stringify(formValues)])
    const [askedPreview, setAskedPreview] = useState<string | null>(null)
    useEffect(() => {
        const timer = setTimeout(() => setAskedPreview(previewBody), 300)
        return () => clearTimeout(timer)
    }, [previewBody])
    const {data: previewed} = useQuery<SeasonsPreviewRead | null>({
        queryKey: [...queryKey, 'preview', askedPreview],
        enabled: open && !!askedPreview,
        staleTime: Infinity,
        gcTime: 0,
        placeholderData: keepPreviousData,
        queryFn: ({signal}) => fetch(`${endpoint}/preview`, {
            signal, method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: askedPreview!,
        }).then(async (response) => response.ok ? SeasonsPreviewReadSchema.parse(await response.json()) : null),
    })
    const after: CollectionSeasonRead[] | null = previewBody && previewed ? previewed.seasons : null

    const save = buildServerAwareSubmit<CollectionSeasonsFormIn, CollectionSeasonsFormOut, CollectionSeasonsRead>(form, (data) => fetch(endpoint, {
        method: 'PUT',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestBody(data)),
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
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['collection', collectionSlug, 'movedEpisodes']}),
                // The collection stored how many wait, which Home and the Library show.
                queryClient.invalidateQueries({queryKey: ['collectionHealth']}),
                queryClient.invalidateQueries({queryKey: ['collections']}),
            ])
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
            if (!form.formState.isDirty) {
                // Nothing changed yet, so the lists are simply what the dialog starts from.
                loadedFor.current = queryClient.setQueryData<CollectionSeasonsRead>(queryKey, fresh) ?? fresh
                reset(seasonsFormValues(fresh))
                return
            }
            keepLoaded(fresh)
            // What the user already switched on or off, or put together, stays.
            setValue('playlists', fresh.playlists.map((playlist) => ({
                id: playlist.id, enabled: choices.get(playlist.id)?.enabled ?? playlist.enabled,
                asSeason: choices.get(playlist.id)?.asSeason ?? playlist.asSeason,
                seasonId: choices.has(playlist.id) ? choices.get(playlist.id)!.seasonId : playlist.seasonId,
                isDefault: choices.get(playlist.id)?.isDefault ?? playlist.isDefault,
            })), {shouldDirty: true})
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setRefreshing(false)
        }
    }

    // Choosing what each list is needs the lists, so the dialog looks for them itself when it has none yet.
    const listedOnOpen = useRef(false)
    const creatorListCount = playlistChoices.filter((choice) => !view?.playlists.find((x) => x.id === choice.id)?.addedByUser).length
    useEffect(() => {
        if (!open) {
            listedOnOpen.current = false
            return
        }
        if (!view || listedOnOpen.current || !view.listsPlaylists) return
        if (listsOn && creatorListCount === 0) {
            listedOnOpen.current = true
            void refreshPlaylists()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, view, listsOn, creatorListCount])

    const linkForm = useForm<LinkSeasonAddFormIn, unknown, LinkSeasonAddFormOut>({
        resolver: zodResolver(LinkSeasonAddFormSchema),
        defaultValues: LinkSeasonAddFormSchema.parse({}),
    })
    const addLink = buildServerAwareSubmit<LinkSeasonAddFormIn, LinkSeasonAddFormOut, AddedLinkRead>(linkForm, (data) => fetch(`${endpoint}/added-links`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: data.url}),
    }), {
        parseSuccess: async (response) => AddedLinkReadSchema.parse(await response.json()),
        fallbackField: 'url',
        genericMessage: 'Could not add the link',
        onSuccess: (found) => {
            // VODLoft only looked the link up: it is saved, and listed, with the rest of the dialog.
            const pending = form.getValues('addedLinks') ?? []
            if (pending.some((link) => link.url === found.url)) {
                linkForm.setError('url', {message: `You added ${found.title} already`})
                return
            }
            setValue('addedLinks', [...pending, found], {shouldDirty: true})
            linkForm.reset({url: ''})
        },
    })
    const addingLink = linkForm.formState.isSubmitting

    // Escape does what Cancel does, also with unsaved changes, and nothing while saving, when Cancel is off too.
    useDismissOnEscape(onDismiss, !isSubmitting, open)

    if (!open) return null
    const seasonsById = new Map((view?.seasons ?? []).map((season) => [season.id, season]))
    const moveSeason = (from: number, to: number) => {
        if (to < 0 || to >= fields.length) return
        move(from, to)
        setValue('customSeasonOrder', true, {shouldDirty: true})
    }
    const playlistsById = new Map((view?.playlists ?? []).map((playlist) => [playlist.id, playlist]))
    const seasonName = (id: number) => form.getValues('seasons')?.find((x) => x.id === id)?.name ?? seasonsById.get(id)?.name ?? season.Singular

    // Each source's choice. A feed that is a season of its own again gets back the season it had.
    const setListRoles = (ids: ReadonlySet<number>, role: SourceRole) => setValue('playlists', playlistChoices.map((choice) => (
        ids.has(choice.id) ? {...choice, enabled: role !== 'off', asSeason: role === 'off' ? choice.asSeason : role === 'season'} : choice
    )), {shouldDirty: true})
    const setFeedRoles = (refs: ReadonlySet<string>, role: SourceRole) => {
        if (!view) return
        setValue('feeds', view.feeds.map((feed) => feed.ref)
            .filter((ref) => refs.has(ref) ? role !== 'off' : feeds.includes(ref)), {shouldDirty: true})
        const next = Object.fromEntries(Object.entries(feedSeasons).filter(([ref]) => !refs.has(ref)))
        if (role === 'season') {
            for (const ref of refs) next[ref] = feedSeasons[ref] ?? view.feeds.find((feed) => feed.ref === ref)?.seasonId ?? null
        }
        setValue('feedSeasons', next, {shouldDirty: true})
    }
    const roleOptions = (seasonsToo: boolean) => (['season', 'part', 'off'] as const)
        .filter((role) => seasonsToo || role !== 'season')
        .map((role) => ({value: role, label: regs?.role.getLabel(role) ?? role}))
    /** The choice that sets every source of a group at once, which shows a choice only while they all have it. */
    const allOptions = (seasonsToo: boolean) => (['season', 'part', 'off'] as const)
        .filter((role) => seasonsToo || role !== 'season')
        .map((role) => ({value: role, label: role === 'season' ? `Own ${season.singular}` : role === 'part' ? 'Part' : 'Off'}))
    const same = (roles: SourceRole[]) => roles.length && roles.every((role) => role === roles[0]) ? roles[0] : null

    // The seasons that sources are in, which other sources can join: lists, and the feeds that are a season.
    type Source = {key: string, title: string, home: boolean, own: () => void}
    const sourcesIn = (seasonId: number): Source[] => [
        ...channelFeeds.filter((feed) => roleOfFeed(feed.ref) === 'season' && feedSeasons[feed.ref] === seasonId).map((feed) => ({
            key: `feed-${feed.ref}`, title: capitalized(feed.names.plural), home: feed.seasonId === seasonId,
            own: () => setValue('feedSeasons', {...feedSeasons, [feed.ref]: null}, {shouldDirty: true}),
        })),
        ...playlistChoices.filter((choice) => roleOfList(choice) === 'season' && choice.seasonId === seasonId).map((choice) => ({
            key: `list-${choice.id}`, title: playlistsById.get(choice.id)?.title ?? '', home: playlistsById.get(choice.id)?.seasonId === seasonId,
            // A list that leaves a season it shared gets a season of its own when you save.
            own: () => setValue('playlists', playlistChoices.map((x) => x.id === choice.id ? {...x, seasonId: null} : x), {shouldDirty: true}),
        })),
    ]
    const sourceSeasonIds = [...new Set([
        ...(view?.playlists ?? []).map((playlist) => playlist.seasonId),
        ...channelFeeds.map((feed) => feed.seasonId),
    ].filter((id): id is number => id !== null))]
    // A source's season leaves the list below as soon as no source in it is a season any more, as saving would leave it.
    const stillSeasons = new Set<number | null>([
        ...playlistChoices.filter((choice) => roleOfList(choice) === 'season').map((choice) => choice.seasonId),
        ...channelFeeds.filter((feed) => roleOfFeed(feed.ref) === 'season').map((feed) => feedSeasons[feed.ref]),
    ])
    const going = new Set(sourceSeasonIds.filter((id) => !seasonsById.get(id)?.loose && !stillSeasons.has(id)))
    const joinRegistry = (seasonId: number) => {
        const targets = sourceSeasonIds.filter((id) => id !== seasonId && sourcesIn(id).length > 0)
        return createSelectRegistry(
            `JoinSeason-${seasonId}-${targets.join('-')}-${targets.map(seasonName).join('-')}`,
            Object.fromEntries([
                ['own', {label: `Join another ${season.singular}…`}],
                ...targets.map((id) => [String(id), {label: `Together with ${seasonName(id)}`}]),
            ]) as Record<string, {label: string}>,
        )
    }
    // Where the sources of a season go when every one of them left it.
    const joinsName = (seasonId: number) => {
        const list = (view?.playlists ?? []).find((playlist) => playlist.seasonId === seasonId)
        const feed = channelFeeds.find((x) => x.seasonId === seasonId)
        const target = list ? playlistChoices.find((choice) => choice.id === list.id)?.seasonId
            : feed ? feedSeasons[feed.ref] : null
        return target ? seasonName(target) : `${season.a} of its own`
    }
    const joinSeason = (from: number, to: number) => {
        setValue('playlists', playlistChoices.map((choice) => choice.seasonId === from ? {...choice, seasonId: to} : choice), {shouldDirty: true})
        setValue('feedSeasons', Object.fromEntries(Object.entries(feedSeasons).map(([ref, id]) => [ref, id === from ? to : id])), {shouldDirty: true})
    }
    /** Where a source is now, when it shares a season with others. */
    const sharedIn = (seasonId: number | null | undefined, title: string) => {
        if (seasonId === null || seasonId === undefined || sourcesIn(seasonId).length < 2) return null
        const name = seasonName(seasonId)
        return name === title ? null : `In ${name}`
    }

    let shown = 0
    const toggleSeasonRemoved = (id: number) => setValue(
        'removedSeasons', removedSeasons.includes(id) ? removedSeasons.filter((x) => x !== id) : [...removedSeasons, id], {shouldDirty: true},
    )
    // What saving leaves, once the server has worked it out: each season as it will be, by id. A deleted season the
    // settings make again comes back under its own slug, and the seasons the settings add are new.
    const afterById = new Map((after ?? []).map((x) => [x.id, x]))
    const removedBySlug = new Map(removedSeasons.flatMap((id) => {
        const removed = seasonsById.get(id)
        return removed ? [[removed.slug, id] as const] : []
    }))
    const madeAgain = new Map((after ?? [])
        .filter((x) => !seasonsById.has(x.id) && removedBySlug.has(x.slug))
        .map((x) => [removedBySlug.get(x.slug)!, x]))
    const afterSave = (id: number) => afterById.get(id) ?? madeAgain.get(id)
    // Seasons the save adds, each shown before the season it comes before, or last.
    const added = new Map<number | null, CollectionSeasonRead[]>()
    let waiting: CollectionSeasonRead[] = []
    for (const x of after ?? []) {
        if (seasonsById.has(x.id) || madeAgain.has(removedBySlug.get(x.slug) ?? -1)) {
            const id = seasonsById.has(x.id) ? x.id : removedBySlug.get(x.slug)!
            if (waiting.length) added.set(id, waiting)
            waiting = []
        } else {
            waiting.push(x)
        }
    }
    if (waiting.length) added.set(null, waiting)
    /** Saving deletes the season: a list's season that no list is a season of any more, one you delete that the settings
     * don't make again, or one the settings leave empty. */
    const leavesOnSave = (id: number) => going.has(id) || (after ? !afterSave(id) : removedSeasons.includes(id))
    const staying = fields.map((field) => !leavesOnSave(field.id))
    // An order only means something with more than one season.
    const seasonsAfterSave = staying.filter(Boolean).length + [...added.values()].reduce((sum, list) => sum + list.length, 0)
    const leavingSeasons = fields.flatMap((field, index) => staying[index] ? [] : [{field, index}])
    /** A season saving adds, which the list shows where it will be. */
    const addedRow = (x: CollectionSeasonRead) => (
        <li key={`new-${x.id}`} className="seasons-dialog-season is-new">
            <span className="seasons-dialog-grip" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/></span>
            <span className="seasons-dialog-number" aria-hidden="true">{x.seasonType === 'extra' ? '0' : x.seasonNumber}</span>
            <span className="seasons-dialog-season-copy">
                <input className="input" value={x.name} readOnly aria-label={`Name of the new ${words.season.singular} ${x.name}`}/>
                <span>New when you save · {counted(x.episodeCount, words.video, words.videos)}</span>
            </span>
        </li>
    )
    const comingBack = removedSeasons
        .map((id) => seasonsById.get(id))
        .filter((removed): removed is CollectionSeasonRead => !!removed && (after ? !!afterSave(removed.id) : removed.episodeCount > 0 && (
            removed.year !== null ? byYear
                : removed.loose ? !byYear && (anyPart || holdsWholeChannel)
                    : stillSeasons.has(removed.id)
        )))
    const yearsComingBack = comingBack.some((removed) => removed.year !== null)
    const oneSeason = () => setValue('looseVideos', 'one_season', {shouldDirty: true})
    const addedLinks = (view?.playlists ?? []).filter((playlist) => playlist.addedByUser)
    // A collection without a link of its own always has one default link. When the user removes it, the first link
    // that stays takes over, as the backend does on saving.
    const defaultLinkId = view && !view.hasOwnLink
        ? playlistChoices.find((choice) => choice.isDefault && !removedLinks.includes(choice.id))?.id
            ?? addedLinks.find((link) => !removedLinks.includes(link.id))?.id
        : undefined
    const chooseDefault = (id: number) => setValue(
        'playlists', playlistChoices.map((choice) => ({...choice, isDefault: choice.id === id})), {shouldDirty: true},
    )
    const toggleRemoved = (id: number) => setValue(
        'removedLinks', removedLinks.includes(id) ? removedLinks.filter((x) => x !== id) : [...removedLinks, id], {shouldDirty: true},
    )
    // The creator's lists, by the kind of list they are, such as an artist's albums and their playlists.
    const creatorLists = playlistChoices.flatMap((choice) => {
        const playlist = playlistsById.get(choice.id)
        return playlist && !playlist.addedByUser ? [{choice, playlist}] : []
    })
    const kindGroups = !view || !names ? [] : view.newLists.length <= 1
        ? [{key: 'lists', title: capitalized(names.plural), rows: creatorLists}]
        : [
            ...view.newLists.map((kind) => ({
                key: kind.key, title: capitalized(kind.names.plural),
                rows: creatorLists.filter((row) => row.playlist.typeKey === kind.key),
            })),
            // Lists VODLoft has not listed again since it knows their kind.
            {key: 'other', title: capitalized(names.plural), rows: creatorLists.filter((row) => !view.newLists.some((kind) => kind.key === row.playlist.typeKey))},
        ].filter((group) => group.rows.length > 0)
    const userLinks = addedLinks.flatMap((playlist) => {
        const choice = playlistChoices.find((x) => x.id === playlist.id)
        return choice ? [{choice, playlist}] : []
    })
    // What the channel season is called while it holds everything, as it would be named now.
    const looseId = view?.seasons.find((x) => x.loose)?.id
    const holdsName = looseVideos === 'everything' && looseId !== undefined ? seasonName(looseId) : view?.channelSeasonNames.everything ?? ''
    const feedsAsSeasons = !!view && view.listsPlaylists

    /** One source: its name, what it has, and what it is in the collection. */
    const sourceRow = (row: {key: string, title: string, details: (string | null)[], role: SourceRole, onRole: (role: SourceRole) => void,
                             seasonsToo?: boolean, badge?: string, actions?: ReactNode}) => (
        <li key={row.key} className={`seasons-dialog-source${row.role === 'off' ? ' is-off' : ''}`}>
            <span className="seasons-dialog-link-copy">
                <b>{row.title}</b>
                {(row.badge || row.details.some(Boolean)) && (
                    <span>
                        {row.badge && <span className="seasons-dialog-badge">{row.badge}</span>}
                        {row.details.filter(Boolean).join(' · ')}
                    </span>
                )}
            </span>
            {row.actions}
            <SegmentedOptions
                name={`seasons-role-${row.key}`} className="seasons-dialog-role" ariaLabel={`What ${row.title} is`}
                value={row.role} options={roleOptions(row.seasonsToo ?? true)} onChange={(value) => row.onRole(value as SourceRole)}
            />
        </li>
    )
    const listRow = ({choice, playlist}: {choice: {id: number, enabled: boolean, asSeason?: boolean, seasonId: number | null}, playlist: CollectionListRead},
                     actions?: ReactNode, details?: (string | null)[]) => sourceRow({
        key: `list-${playlist.id}`, title: playlist.title, role: setRoleOfList(choice),
        badge: playlist.status === 'new' ? 'New' : undefined,
        details: details ?? [
            playlist.itemCount !== null ? counted(playlist.itemCount, words.video, words.videos) : null,
            playlist.firstVideoAt ? `since ${new Date(playlist.firstVideoAt).getFullYear()}` : null,
            roleOfList(choice) === 'season' ? sharedIn(choice.seasonId, playlist.title) : null,
        ],
        onRole: (role) => setListRoles(new Set([playlist.id]), role),
        actions,
    })
    /** The button that folds a box of sources shut or open. */
    const foldButton = (box: 'feeds' | 'lists', title: string) => (
        <button
            type="button" className="seasons-dialog-fold" aria-expanded={!shut[box]}
            aria-label={`${shut[box] ? 'Show' : 'Hide'} ${title}`} title={shut[box] ? 'Show' : 'Hide'}
            onClick={() => setShut((current) => ({...current, [box]: !current[box]}))}
        >
            <FontAwesomeIcon icon={faIcon('fass', shut[box] ? 'chevron-down' : 'chevron-up')} aria-hidden="true"/>
        </button>
    )
    /** What the sources of a folded box are, counted by choice, such as "2 part of the collection · 1 off". */
    const summary = (roles: SourceRole[]) => (['season', 'part', 'off'] as const)
        .map((role) => [role, roles.filter((x) => x === role).length] as const)
        .filter(([, count]) => count > 0)
        .map(([role, count]) => `${count} ${role === 'season' ? (count === 1 ? `${season.singular} of its own` : `${season.plural} of their own`) : role === 'part' ? 'part of the collection' : 'off'}`)
        .join(' · ')
    /** The choice for every source in a group, shown above them once there is more than one. */
    const allOf = (label: string, roles: SourceRole[], onRole: (role: SourceRole) => void, seasonsToo = true) => roles.length > 1 && (
        <span className="seasons-dialog-all">
            <span>{label}</span>
            <SegmentedOptions
                name={`seasons-all-${label}`} className="seasons-dialog-role" ariaLabel={label}
                value={same(roles)} options={allOptions(seasonsToo)} onChange={(value) => onRole(value as SourceRole)}
            />
        </span>
    )

    return (
        <>
            <div className="modal-overlay" role="presentation" onClick={() => !isSubmitting && onDismiss()}>
                <div className="modal seasons-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}
                     onClick={(event) => event.stopPropagation()}>
                    <div className="modal-header">
                        <h2 id={titleId} className="modal-title">{season.Plural} of {nameInText(collectionTitle)}</h2>
                    </div>
                    <form onSubmit={onSubmit} noValidate>
                        <div className="seasons-dialog-content">
                            {error && <div className="form-error-card" role="alert">{error.message}</div>}
                            {!view && !error && <p className="seasons-dialog-muted">Loading the {season.plural}…</p>}
                            {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}

                            {view && names && regs && (
                                <>
                                    {(channelFeeds.length > 0 || view.linkSeasonsOffered) && (
                                        <section className="seasons-dialog-section" aria-labelledby="seasons-dialog-sources">
                                            <div>
                                                <h3 id="seasons-dialog-sources">What's in the collection</h3>
                                                <p className="seasons-dialog-muted">Everything that brings {words.videos}, with one choice each.</p>
                                            </div>

                                            {channelFeeds.length > 0 && (
                                                <div className={`seasons-dialog-box${shut.feeds ? ' is-shut' : ''}`}>
                                                    <div className="seasons-dialog-box-head">
                                                        <div className="seasons-dialog-box-title-row">
                                                            <div className="seasons-dialog-box-name" onClick={() => setShut((current) => ({...current, feeds: !current.feeds}))}>
                                                                <h4>From the {words.channel}</h4>
                                                                <p className="seasons-dialog-muted">
                                                                    {shut.feeds ? summary(channelFeeds.map((feed) => roleOfFeed(feed.ref))) : `The parts of the ${words.channel} page.`}
                                                                </p>
                                                            </div>
                                                            {foldButton('feeds', `the parts of the ${words.channel}`)}
                                                        </div>
                                                        {!shut.feeds && allOf('All', channelFeeds.map((feed) => roleOfFeed(feed.ref)),
                                                            (role) => setFeedRoles(new Set(channelFeeds.map((feed) => feed.ref)), role), feedsAsSeasons)}
                                                    </div>
                                                    {!shut.feeds && <ul className="seasons-dialog-sources">
                                                        {channelFeeds.map((feed) => sourceRow({
                                                            key: `feed-${feed.ref}`, title: capitalized(feed.names.plural), role: roleOfFeed(feed.ref),
                                                            details: [roleOfFeed(feed.ref) === 'season' ? sharedIn(feedSeasons[feed.ref], capitalized(feed.names.plural)) : null],
                                                            onRole: (role) => setFeedRoles(new Set([feed.ref]), role), seasonsToo: feedsAsSeasons,
                                                        }))}
                                                    </ul>}
                                                    {only && (
                                                        <div className="help seasons-dialog-box-note">
                                                            Every part is off, so the collection holds only what its {names.plural} and links have.
                                                        </div>
                                                    )}
                                                    {feedsOff && !only && (
                                                        <div className="help seasons-dialog-box-note">
                                                            The {words.channel} is listed again when you save. Its {words.videos} that no part or {names.singular} it
                                                            takes has leave, downloaded ones with their files.
                                                        </div>
                                                    )}
                                                    {errors.feeds && <div className="error seasons-dialog-box-note" role="alert">{String(errors.feeds.message ?? errors.feeds.root?.message)}</div>}
                                                    {errors.feedSeasons && <div className="error seasons-dialog-box-note" role="alert">{String(errors.feedSeasons.message ?? errors.feedSeasons.root?.message)}</div>}
                                                </div>
                                            )}

                                            {view.linkSeasonsOffered && (
                                                <div className={`seasons-dialog-box${listsOn ? '' : ' is-off'}${shut.lists ? ' is-shut' : ''}`}>
                                                    <div className="seasons-dialog-box-head">
                                                        <div className="seasons-dialog-box-title-row">
                                                        <div className="seasons-dialog-with-switch">
                                                            {view.hasOwnLink && (
                                                                <Controller control={control} name="linkSeasonsOn" render={({field}) => (
                                                                    <Switch
                                                                        id="seasons-link-seasons" checked={!!field.value || only}
                                                                        onChange={(on) => {
                                                                            field.onChange(on)
                                                                            // Switched on, the lists show what they will be.
                                                                            if (on) setShut((current) => ({...current, lists: false}))
                                                                        }}
                                                                        disabled={only} aria-labelledby="seasons-dialog-links"
                                                                        onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                                                                        height={18} width={34} handleDiameter={14}
                                                                    />
                                                                )}/>
                                                            )}
                                                            <div className="seasons-dialog-box-name" onClick={() => setShut((current) => ({...current, lists: !current.lists}))}>
                                                                <h4 id="seasons-dialog-links">
                                                                    {view.listsPlaylists ? `${capitalized(view.sectionListNames.plural)} and links` : capitalized(names.plural)}
                                                                </h4>
                                                                <p className="seasons-dialog-muted">
                                                                    {!view.hasOwnLink
                                                                        ? `This collection has no link of its own, so it holds only what the links you add have, from any site VODLoft can read.`
                                                                        : listsOn
                                                                            ? `Lists of ${words.videos}, which can hold ${words.videos} of other ${words.creators}.`
                                                                            : `Off: the collection holds only what is on the ${words.channel} page.`}
                                                                    {listsOn && shut.lists && ` ${summary([...creatorLists, ...userLinks].map((row) => setRoleOfList(row.choice)))}`}
                                                                </p>
                                                            </div>
                                                        </div>
                                                        {foldButton('lists', view.listsPlaylists ? `the ${view.sectionListNames.plural} and links` : `the ${names.plural}`)}
                                                        </div>
                                                        {listsOn && !shut.lists && view.listsPlaylists && (
                                                            <button type="button" className="btn btn-small" onClick={() => void refreshPlaylists()} disabled={refreshing}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'arrows-rotate')} spin={refreshing} aria-hidden="true"/>
                                                                <span>{refreshing ? 'Looking…' : `Look for new ${names.plural}`}</span>
                                                            </button>
                                                        )}
                                                    </div>
                                                    {errors.linkSeasonsOn && <div className="error seasons-dialog-box-note" role="alert">{errors.linkSeasonsOn.message}</div>}

                                                    {!shut.lists && (
                                                        // While the lists are off, they show what each would be, dimmed, until switched on.
                                                        <div className="seasons-dialog-box-body" inert={!listsOn}>
                                                            {view.listsPlaylists && creatorLists.length === 0 && (
                                                                <p className="seasons-dialog-muted seasons-dialog-box-note" role="status">
                                                                    {refreshing ? (
                                                                        <><FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin aria-hidden="true"/> Looking for the {names.plural}…</>
                                                                    ) : `VODLoft has not listed the ${names.plural} yet.`}
                                                                </p>
                                                            )}
                                                            {kindGroups.map((group) => (
                                                                <Fragment key={group.key}>
                                                                    <div className="seasons-dialog-kind">
                                                                        <span>{group.title}</span>
                                                                        {allOf(`All ${group.title.toLowerCase()}`, group.rows.map((row) => setRoleOfList(row.choice)),
                                                                            (role) => setListRoles(new Set(group.rows.map((row) => row.choice.id)), role))}
                                                                    </div>
                                                                    <ul className="seasons-dialog-sources">{group.rows.map((row) => listRow(row))}</ul>
                                                                </Fragment>
                                                            ))}

                                                            <div className="seasons-dialog-kind">
                                                                <span>Your links</span>
                                                                {allOf('All links', userLinks.filter((row) => !removedLinks.includes(row.playlist.id)).map((row) => setRoleOfList(row.choice)),
                                                                    (role) => setListRoles(new Set(userLinks.map((row) => row.choice.id)), role))}
                                                            </div>
                                                            <ul className="seasons-dialog-sources">
                                                                {userLinks.map((row) => {
                                                                    const link = row.playlist
                                                                    const removed = removedLinks.includes(link.id)
                                                                    const actions = (
                                                                        <span className="seasons-dialog-source-actions">
                                                                            {!removed && !view.hasOwnLink && (
                                                                                defaultLinkId === link.id
                                                                                    ? <span className="seasons-dialog-default">Default</span>
                                                                                    : (
                                                                                        <button type="button" className="btn btn-small" aria-label={`Use ${link.title} as default`}
                                                                                                onClick={() => chooseDefault(link.id)}>
                                                                                            Use as default
                                                                                        </button>
                                                                                    )
                                                                            )}
                                                                            <button type="button" className="btn btn-small" aria-label={`${removed ? 'Keep' : 'Remove'} ${link.title}`}
                                                                                    onClick={() => toggleRemoved(link.id)}>
                                                                                {removed ? 'Keep' : 'Remove'}
                                                                            </button>
                                                                        </span>
                                                                    )
                                                                    if (removed) return (
                                                                        <li key={`list-${link.id}`} className="seasons-dialog-source is-removed">
                                                                            <span className="seasons-dialog-link-copy"><b>{link.title}</b><span>Removed when you save</span></span>
                                                                            {actions}
                                                                        </li>
                                                                    )
                                                                    return listRow(row, actions, [
                                                                        link.url,
                                                                        roleOfList(row.choice) === 'season' && !link.seasonName && row.choice.enabled
                                                                            ? `No ${words.season.singular} yet: it gets one once VODLoft has listed its ${words.videos}` : null,
                                                                        roleOfList(row.choice) === 'season' ? sharedIn(row.choice.seasonId, link.title) : null,
                                                                    ])
                                                                })}
                                                                {newLinks.map((link) => (
                                                                    <li key={link.url} className="seasons-dialog-source">
                                                                        <span className="seasons-dialog-link-copy">
                                                                            <b>{link.title}</b>
                                                                            <span>{link.url} · Added when you save, as {words.season.a} of its own; VODLoft then lists its {words.videos}</span>
                                                                        </span>
                                                                        <button type="button" className="btn btn-small" aria-label={`Remove ${link.title}`}
                                                                                onClick={() => setValue('addedLinks', newLinks.filter((x) => x.url !== link.url), {shouldDirty: true})}>
                                                                            Remove
                                                                        </button>
                                                                    </li>
                                                                ))}
                                                            </ul>
                                                            <div className="seasons-dialog-add-link seasons-dialog-box-note">
                                                                <input
                                                                    id="seasons-add-link" className="input" type="url" inputMode="url"
                                                                    placeholder="https://… a link from any site" aria-label="Add a link"
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
                                                            {linkForm.formState.errors.url && <div className="error seasons-dialog-box-note" role="alert">{linkForm.formState.errors.url.message}</div>}
                                                            {errors.playlists && <div className="error seasons-dialog-box-note" role="alert">{String(errors.playlists.message ?? errors.playlists.root?.message)}</div>}

                                                            {(view.listsPlaylists || !only) && (
                                                                <div className="seasons-dialog-box-settings">
                                                                    <div className="seasons-dialog-box-title">For these lists</div>
                                                                    {view.listsPlaylists && (
                                                                        <div className="form-row">
                                                                            <label>When the {words.creator} adds {view.sectionListNames.a}</label>
                                                                            <NewListSettings
                                                                                kinds={view.newLists} valueOf={(kind) => newLists[kind.key]}
                                                                                fallback="ask" idPrefix="seasons-new-links" registryFor={regs.newLinks}
                                                                                onChange={(kind, value) => setValue('newLists', {...newLists, [kind.key]: value as NewLinkSeason}, {shouldDirty: true})}
                                                                            />
                                                                            {errors.newLists && <div className="error" role="alert">{(errors.newLists as {message?: string}).message}</div>}
                                                                            <div className="help">VODLoft looks once a day.</div>
                                                                        </div>
                                                                    )}
                                                                    {!only && (
                                                                        <div className="form-row">
                                                                            <label htmlFor="seasons-outside">
                                                                                {capitalized(words.videos)} of other {words.creators} in these {names.plural} and links
                                                                            </label>
                                                                            <SimpleSelect
                                                                                inputId="seasons-outside" registry={regs.guests} value={guests}
                                                                                onChange={(value) => setValue('outsideVideos', value as CollectionSeasonsFormIn['outsideVideos'], {shouldDirty: true})}
                                                                            />
                                                                            <div className="help">{regs.guests.getHelp(guests)}</div>
                                                                            {errors.outsideVideos && <div className="error" role="alert">{errors.outsideVideos.message}</div>}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
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
                                            {customOrder && seasonsAfterSave > 1 && (
                                                <button type="button" className="btn btn-small" onClick={() => setValue('customSeasonOrder', false, {shouldDirty: true})}>
                                                    Automatic order
                                                </button>
                                            )}
                                        </div>
                                        {regs && showRest && (
                                            <div className="form-row">
                                                <span className="label" id="seasons-rest-label">What is part of the collection goes in</span>
                                                <SegmentedOptions
                                                    name="seasons-rest" ariaLabelledBy="seasons-rest-label" className="seasons-dialog-rest"
                                                    value={byYear ? 'by_year' : 'one_season'}
                                                    options={regs.rest.options.map((option) => ({value: option.value, label: option.label}))}
                                                    onChange={(value) => setValue('looseVideos', value === 'by_year' ? 'by_year'
                                                        : view.looseVideos === 'everything' ? 'everything' : 'one_season', {shouldDirty: true})}
                                                />
                                                {byYear && <div className="help">{regs.rest.getHelp('by_year')}</div>}
                                                {errors.looseVideos && <div className="error" role="alert">{errors.looseVideos.message}</div>}
                                            </div>
                                        )}
                                        {showAlsoHolds && (
                                            <label className="seasons-dialog-check">
                                                <input
                                                    type="checkbox" checked={looseVideos === 'everything'}
                                                    onChange={(event) => setValue('looseVideos', event.target.checked ? 'everything' : 'one_season', {shouldDirty: true})}
                                                />
                                                <span>
                                                    {holdsName} also holds the {words.videos} that have {season.a} of their own
                                                </span>
                                            </label>
                                        )}
                                        {regs && showRepeat && (
                                            <div className="form-row">
                                                <label htmlFor="seasons-repeat">
                                                    When {words.episode.a} belongs {words.inSeason} several {season.plural}
                                                </label>
                                                <SimpleSelect
                                                    inputId="seasons-repeat" registry={regs.repeat} value={repeatVideos}
                                                    onChange={(value) => setValue('repeatVideos', value as CollectionSeasonsFormIn['repeatVideos'], {shouldDirty: true})}
                                                />
                                                <div className="help">{regs.repeat.getHelp(repeatVideos)}</div>
                                                {errors.repeatVideos && <div className="error" role="alert">{errors.repeatVideos.message}</div>}
                                            </div>
                                        )}
                                        {comingBack.length > 0 && (
                                            <div className="seasons-dialog-warning" role="status">
                                                <FontAwesomeIcon icon={faIcon('fass', 'circle-info')} aria-hidden="true"/>
                                                <div>
                                                    <p>
                                                        {/* Named as saving names them, such as Channel for a deleted Videos that will hold the whole channel. */}
                                                        Your settings put {words.videos} in {comingBack.length === 1 ? `${season.a} called` : `${season.plural} called`}
                                                        {' '}{listed(comingBack.map((removed) => afterSave(removed.id)?.name ?? removed.name))}. When you save,
                                                        {comingBack.length === 1 ? ' it comes' : ' they come'} back here.
                                                    </p>
                                                    {/* Only where the setting decides the seasons: a collection made from one list, or one whose lists are seasons. */}
                                                    {yearsComingBack && showRest && (
                                                        <button type="button" className="btn btn-small" onClick={oneSeason}>
                                                            Put them in one {season.singular} instead
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                        {listsOn && newLinks.length > 0 && (
                                            <div className="seasons-dialog-warning" role="status">
                                                <FontAwesomeIcon icon={faIcon('fass', 'circle-info')} aria-hidden="true"/>
                                                <p>
                                                    When you save, {listed(newLinks.map((link) => link.title))}
                                                    {newLinks.length === 1 ? ` becomes ${season.a}` : ` each become ${season.a}`} here, once VODLoft
                                                    has listed {newLinks.length === 1 ? 'its' : 'their'} {words.videos}.
                                                </p>
                                            </div>
                                        )}
                                        <ol className="seasons-dialog-seasons">
                                            {fields.map((field, index) => {
                                                const season = seasonsById.get(field.id)
                                                const extra = season?.seasonType === 'extra'
                                                // What saving does to the season: a list's season that no list is a season of any more goes, as
                                                // one you delete does, and so does one the settings leave empty.
                                                const next = after ? afterSave(field.id) : undefined
                                                const deleted = removedSeasons.includes(field.id)
                                                // A season that goes is listed below the others instead, where it can't be moved.
                                                if (leavesOnSave(field.id)) return (added.get(field.id) ?? []).length
                                                    ? <Fragment key={field.key}>{(added.get(field.id) ?? []).map(addedRow)}</Fragment> : null
                                                shown += 1
                                                const up = staying.lastIndexOf(true, index - 1)
                                                const down = staying.indexOf(true, index + 1)
                                                const counts = season?.episodeCount ?? 0
                                                const number = next ? (next.seasonType === 'extra' ? '0' : next.seasonNumber)
                                                    : extra ? '0' : customOrder ? shown : season?.seasonNumber
                                                return (
                                                    <Fragment key={field.key}>
                                                    {(added.get(field.id) ?? []).map(addedRow)}
                                                    <li
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
                                                        <span className="seasons-dialog-number" aria-hidden="true">{number}</span>
                                                        <span className="seasons-dialog-season-copy">
                                                            <input
                                                                className="input" aria-label={`Name of ${words.season.singular} ${index + 1}`}
                                                                aria-invalid={!!errors.seasons?.[index]?.name}
                                                                {...register(`seasons.${index}.name`)}
                                                            />
                                                            <span>
                                                                {deleted ? `Deleted, and made again${next && next.name !== season?.name ? ` as ${next.name}` : ''} by your settings when you save · ` : null}
                                                                {counted(counts, words.video, words.videos)}
                                                                {next && next.episodeCount !== counts ? `, ${counted(next.episodeCount, words.video, words.videos)} when you save` : null}
                                                                {season?.loose ? (holdsWholeChannel ? ` · Everything from the ${words.channel}` : ' · The rest of the collection') : null}
                                                            </span>
                                                            {season && sourceSeasonIds.includes(season.id) && (
                                                                <SeasonSources
                                                                    season={field.id} words={words} sources={sourcesIn(field.id)}
                                                                    joinRegistry={joinRegistry(field.id)}
                                                                    onJoin={(to) => joinSeason(field.id, to)} joinsName={joinsName(field.id)}
                                                                />
                                                            )}
                                                            {errors.seasons?.[index]?.name && <span className="error" role="alert">{errors.seasons[index]?.name?.message}</span>}
                                                        </span>
                                                        <span className="seasons-dialog-arrows">
                                                            {season?.removable && (
                                                                <button
                                                                    type="button" aria-label={`${deleted ? 'Keep' : 'Delete'} ${form.getValues(`seasons.${index}.name`) || words.season.singular}`}
                                                                    title={deleted ? 'Keep' : 'Delete'} onClick={() => toggleSeasonRemoved(field.id)}
                                                                >
                                                                    <FontAwesomeIcon icon={faIcon('fass', deleted ? 'rotate-left' : 'trash')}/>
                                                                </button>
                                                            )}
                                                            <button type="button" aria-label={`Move ${words.season.singular} ${index + 1} up`} disabled={up < 0} onClick={() => moveSeason(index, up)}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                                            </button>
                                                            <button type="button" aria-label={`Move ${words.season.singular} ${index + 1} down`} disabled={down < 0} onClick={() => moveSeason(index, down)}>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                                            </button>
                                                        </span>
                                                    </li>
                                                    </Fragment>
                                                )
                                            })}
                                            {(added.get(null) ?? []).map(addedRow)}
                                        </ol>
                                        {leavingSeasons.length > 0 && (
                                            <div className="seasons-dialog-leaving">
                                                <h4>Deleted when you save</h4>
                                                <ul>
                                                    {leavingSeasons.map(({field, index}) => {
                                                        const gone = seasonsById.get(field.id)
                                                        const deleted = removedSeasons.includes(field.id)
                                                        const name = form.getValues(`seasons.${index}.name`) || gone?.name || words.season.singular
                                                        return (
                                                            <li key={field.key}>
                                                                <span className="seasons-dialog-link-copy">
                                                                    <b>{name}</b>
                                                                    <span>
                                                                        {counted(gone?.episodeCount ?? 0, words.video, words.videos)}
                                                                        {deleted ? '' : going.has(field.id) ? ` · No ${names.singular} in it is ${words.season.a} in VODLoft any more` : ' · The settings leave it empty'}
                                                                    </span>
                                                                </span>
                                                                {deleted && gone?.removable && (
                                                                    <button type="button" className="btn btn-small" aria-label={`Keep ${name}`} onClick={() => toggleSeasonRemoved(field.id)}>
                                                                        <FontAwesomeIcon icon={faIcon('fass', 'rotate-left')} aria-hidden="true"/> Keep
                                                                    </button>
                                                                )}
                                                            </li>
                                                        )
                                                    })}
                                                </ul>
                                            </div>
                                        )}
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
                {confirm && names && confirm.afterListing && confirm.episodes > 0 && (
                    <>
                        <p>
                            {counted(confirm.episodes, words.video, words.videos)} {confirm.episodes === 1 ? 'is' : 'are'} in
                            none of the {names.plural} that are {season.plural} in VODLoft. Once VODLoft has listed the {names.plural} again,
                            {confirm.episodes === 1 ? ' it leaves' : ' they leave'} the collection.
                        </p>
                        {confirm.withFiles > 0 && (
                            <p>
                                <strong>{counted(confirm.withFiles, 'of them has', 'of them have')} downloaded files,
                                which are deleted too.</strong>
                            </p>
                        )}
                    </>
                )}
                {confirm && (confirm.repeated ?? 0) > 0 && (
                    <p>
                        {counted(confirm.repeated ?? 0, words.episode.singular, words.episode.plural)} of{' '}
                        {(confirm.repeated ?? 0) === 1 ? `${words.episode.a} that is` : `${words.episode.plural} that are`} {words.inSeason} another{' '}
                        {season.singular} too {(confirm.repeated ?? 0) === 1 ? 'leaves' : 'leave'} the collection. The files of
                        downloaded ones are deleted too.
                    </p>
                )}
                {confirm && names && !confirm.afterListing && confirm.episodes > 0 && (
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


/** The sources of one season in the Seasons dialog: the lists and feeds it holds, and putting it together with another. */
function SeasonSources({season, words, sources, joinRegistry, onJoin, joinsName}: {
    season: number
    words: Words
    sources: {key: string, title: string, home: boolean, own: () => void}[]
    joinRegistry: SelectRegistry
    onJoin: (to: number) => void
    joinsName: string
}) {
    if (sources.length === 0) {
        return <span className="seasons-dialog-joins">What is in it moves to {joinsName} when you save.</span>
    }
    // The source whose season it is stays; the ones that joined it can have one of their own again.
    const home = sources.find((source) => source.home) ?? sources[0]
    return (
        <span className="seasons-dialog-season-lists">
            {sources.length > 1 && (
                <span className="seasons-dialog-list-names">
                    {sources.filter((source) => source !== home).map((source) => (
                        <span key={source.key} className="seasons-dialog-list-name">
                            <span>Joined: <b>{source.title}</b></span>
                            <button type="button" className="btn btn-small" onClick={source.own}
                                    aria-label={`Give ${source.title} ${words.season.a} of its own again`}>
                                {capitalized(words.season.a)} of its own again
                            </button>
                        </span>
                    ))}
                </span>
            )}
            {joinRegistry.options.length > 1 && (
                <span className="seasons-dialog-join">
                    <SimpleSelect
                        inputId={`seasons-join-${season}`} aria-label={`Put ${sources.map((source) => source.title).join(' and ')} together with another ${words.season.singular}`}
                        registry={joinRegistry} value="own"
                        onChange={(value) => { if (value && value !== 'own') onJoin(Number(value)) }}
                    />
                </span>
            )}
        </span>
    )
}
