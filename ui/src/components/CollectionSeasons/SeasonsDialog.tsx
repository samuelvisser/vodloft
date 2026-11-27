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
import ChoiceBar from '../common/ChoiceBar'
import {useDismissOnEscape} from '../Modal/useDismissOnEscape'
import SegmentedOptions from '../SegmentedOptions/SegmentedOptions'
import {
    AddedLinkReadSchema, type AddedLinkRead, CollectionSeasonsFormSchema, LinkSeasonAddFormSchema, SeasonsPreviewReadSchema, seasonsFormValues, type SeasonsPreviewRead,
    type CollectionListRead, type CollectionSeasonsFormIn, type CollectionSeasonsFormOut, type CollectionSeasonsRead,
    type LinkSeasonAddFormIn, type LinkSeasonAddFormOut, type NewLinkSeason, type CollectionSeasonRead,
    SeasonsListingsReadSchema, SeasonsReviewReadSchema,
} from '../../types/schemas/collection_seasons'
import './SeasonsDialog.css'
import {dialogWords, namesOf, newToken, readSeasons, registries, type SourceRole, useNarrow, type Words} from './seasonsSettings'
import SeasonsReview, {SavingProgress} from './SeasonsReview'
import {useSavingSteps} from './savingProgress'
import type {ProgressStep} from '../../types/progress'
import type {CauseRow} from '../ReconcileDialog/MoveCauses'
import {collectionWords, CollectionWords, wordsOf} from '../../lib/collectionWords'
import {nameInText} from '../../lib/nameInText'
import type {Names} from '../../types/schemas/source'

/** A badge of a season: what it is made of, such as what is part of the collection, a kind of list or a feed. */
type BadgeTone = 'collection' | 'list' | 'feed'
type Badge = {key: string, label: string, tone: BadgeTone}

type Props = {
    open: boolean
    collectionSlug: string
    collectionTitle: string
    onDismiss: () => void
    /** What the collection calls its seasons and episodes, such as albums and music videos. */
    words?: CollectionWords
}


async function failure(response: Response, fallback: string): Promise<Error> {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    return new Error(typeof detail === 'string' ? detail : Array.isArray(detail) && detail[0]?.msg ? String(detail[0].msg) : fallback)
}

const counted = (count: number, singular: string, plural: string) => `${count} ${count === 1 ? singular : plural}`

/** Names in a sentence: A, B and C. */
function listed(names: string[]): string {
    return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** The Seasons dialog: rename and reorder a collection's seasons, and choose which of its creator's playlists are seasons. */
export default function SeasonsDialog({open, collectionSlug, collectionTitle, onDismiss, words: collectionWordsGiven}: Props) {
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
    const [dragging, setDragging] = useState<number | null>(null)
    const dragFrom = useRef<number | null>(null)
    const narrow = useNarrow()
    // On a phone, the settings for the lists and for the seasons fold to one summary row each.
    // The seasons opened to rename them or change what they are made of; all start closed.
    const [openSeasons, setOpenSeasons] = useState<ReadonlySet<number>>(new Set())
    const [openSettings, setOpenSettings] = useState<{lists: boolean, seasons: boolean}>({lists: false, seasons: false})
    // The settings as the review shows them; while there are none, the dialog is at its first step.
    const [reviewing, setReviewing] = useState<CollectionSeasonsFormOut | null>(null)
    const [renumber, setRenumber] = useState(true)
    // The lists the dialog asked VODLoft to list for its review. A list switched off again stays in: its listing
    // carries on, and what it found is kept until the dialog closes.
    const [asked, setAsked] = useState<{lists: number[], links: string[]}>({lists: [], links: []})
    const [token, setToken] = useState(newToken)
    useEffect(() => {
        if (!open) return
        const mine = newToken()
        setToken(mine)
        setReviewing(null)
        setRenumber(true)
        setAsked({lists: [], links: []})
        setOpenSettings({lists: false, seasons: false})
        // Closed: what it listed is not needed any more.
        return () => {
            void fetch(`${endpoint}/listings?token=${mine}`, {method: 'DELETE', credentials: 'include', keepalive: true}).catch(() => undefined)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, endpoint])

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
    // The channel season is named after what it holds, such as Channel or Videos: what changes that renames it, unless
    // the user gave it a name of their own.
    const looseNamed = useRef(looseSeason)
    useEffect(() => {
        const was = looseNamed.current
        looseNamed.current = looseSeason
        if (!view || !looseSeason || !was || was === looseSeason) return
        const named = form.getValues('seasons') ?? []
        const at = named.findIndex((x) => view.seasons.find((y) => y.id === x.id)?.loose)
        if (at >= 0 && named[at].name.trim() === was) setValue(`seasons.${at}.name`, looseSeason, {shouldDirty: true})
    }, [looseSeason, view]) // eslint-disable-line react-hooks/exhaustive-deps
    const words = dialogWords(collectionWordsGiven ?? (view ? wordsOf(view.words) : collectionWords(null)), view)
    const {season} = words
    const regs = useMemo(() => view && names ? registries(names, words, view) : null, [view, names, words])
    // Where what is part of the collection goes, which a collection made from one list always chooses.
    const showRest = !!view && (view.madeFromList || ((channelSeasonOffered || only) && anyPart))
    // Whether the channel season also holds what has a season of its own, which only lists can have besides it.
    const showAlsoHolds = channelSeasonOffered && !byYear && anyListSeason && anyPart
    // Only lists that are a season of their own put a video in several seasons.
    const showRepeat = listsOn && anyListSeason

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
        addedLinks: data.linkSeasonsOn || only
            ? data.addedLinks.map((link) => ({url: link.url, title: link.title, asSeason: link.asSeason})) : [],
        removedSeasons: data.removedSeasons,
        // What the dialog listed for its review, which the review plans with and saving takes along.
        listingToken: token,
    })

    // A list switched on that VODLoft has not listed, and a link added, are listed right away in the background, so
    // the review can say exactly what saving moves without making the user wait for it there.
    useEffect(() => {
        if (!open || !view) return
        const known = new Map(view.playlists.map((playlist) => [playlist.id, playlist]))
        const lists = listsOn ? playlistChoices
            .filter((choice) => choice.enabled && !removedLinks.includes(choice.id) && known.has(choice.id) && !known.get(choice.id)!.listed)
            .map((choice) => choice.id) : []
        const links = listsOn ? newLinks.map((link) => link.url) : []
        const moreLists = lists.filter((id) => !asked.lists.includes(id))
        const moreLinks = links.filter((url) => !asked.links.includes(url))
        if (moreLists.length || moreLinks.length) {
            setAsked({lists: [...asked.lists, ...moreLists], links: [...asked.links, ...moreLinks]})
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, view, listsOn, JSON.stringify(playlistChoices), JSON.stringify(newLinks), JSON.stringify(removedLinks)])
    const {data: listings} = useQuery({
        queryKey: [...queryKey, 'listings', token, asked],
        enabled: open && asked.lists.length + asked.links.length > 0,
        gcTime: 0,
        placeholderData: keepPreviousData,
        // Asking again never lists anything twice: it says how far each listing is.
        queryFn: async ({signal}) => {
            const response = await fetch(`${endpoint}/listings`, {
                signal, method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({token, listIds: asked.lists, links: asked.links}),
            })
            if (!response.ok) throw await failure(response, 'Could not list them')
            return SeasonsListingsReadSchema.parse(await response.json())
        },
        refetchInterval: (query) => query.state.data?.listings.some((listing) => listing.state === 'listing') ? 2000 : false,
    })
    const listingOf = (id: number) => listings?.listings.find((listing) => listing.listId === id)
    const listingOfLink = (url: string) => listings?.listings.find((listing) => listing.link === url)

    // The review: what saving these settings does. It waits while VODLoft still lists a list it needs. It starts as
    // soon as a change is made on the first step, so it is usually ready, or well on its way, once the user gets there.
    const formNow = watch()
    const aheadOf = useMemo(() => {
        if (!view || !isDirty) return null
        const parsed = CollectionSeasonsFormSchema.safeParse(formNow)
        return parsed.success ? JSON.stringify(requestBody(parsed.data)) : null
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [view, isDirty, JSON.stringify(formNow)])
    const [ahead, setAhead] = useState<string | null>(null)
    useEffect(() => {
        const timer = setTimeout(() => setAhead(aheadOf), 500)
        return () => clearTimeout(timer)
    }, [aheadOf])
    const reviewBody = reviewing ? JSON.stringify(requestBody(reviewing)) : ahead
    const {data: review, error: reviewError} = useQuery({
        queryKey: [...queryKey, 'review', reviewBody],
        enabled: open && !!reviewBody,
        gcTime: 0,
        queryFn: async ({signal}) => {
            const response = await fetch(`${endpoint}/review`, {
                signal, method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: reviewBody!,
            })
            if (!response.ok) throw await failure(response, 'VODLoft could not look up what saving does.')
            return SeasonsReviewReadSchema.parse(await response.json())
        },
        refetchInterval: (query) => query.state.data?.busy ? 2000 : false,
    })
    const reviewReady = !!review && !review.busy
    const moves = reviewReady && (review.moves?.parts.length ?? 0) > 0

    // The seasons saving the dialog would leave, as the server works them out, so the list below shows a change
    // as soon as it is made. The names play no part in it, so typing one asks nothing.
    const formValues = watch()
    const previewBody = useMemo(() => {
        // Also before any change: downloads that wait to move, such as after a creator moved a video, already move
        // when you save, so the list shows that from the start rather than after the first change.
        if (!view) return null
        const parsed = CollectionSeasonsFormSchema.safeParse(formValues)
        if (!parsed.success) return null
        const named = new Map(view.seasons.map((x) => [x.id, x.name]))
        return JSON.stringify(requestBody({
            ...parsed.data, seasons: parsed.data.seasons.map((x) => ({id: x.id, name: named.get(x.id) ?? x.name})),
        }))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [view, JSON.stringify(formValues)])
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
        body: JSON.stringify({...requestBody(data), renumber}),
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
            toast.success(moves ? `${season.Plural} saved, moving the downloads` : `${season.Plural} saved`)
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['collection', collectionSlug, 'movedEpisodes']}),
                queryClient.invalidateQueries({queryKey: ['collectionHealth']}),
                queryClient.invalidateQueries({queryKey: ['collections']}),
            ])
            onDismiss()
        },
    })

    // Next opens the review; the review's Save does what it showed. A refusal of a setting goes back to it.
    const onSubmit = form.handleSubmit(async (values) => {
        if (!reviewing) {
            setReviewing(values)
            return
        }
        await save()
        const {errors: refused} = form.formState
        if (Object.keys(refused).some((field) => field !== 'root')) setReviewing(null)
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
            // A season of its own, unless the user makes it part of the collection.
            setValue('addedLinks', [...pending, {...found, asSeason: true}], {shouldDirty: true})
            linkForm.reset({url: ''})
        },
    })
    const addingLink = linkForm.formState.isSubmitting

    // Escape does what Cancel does, also with unsaved changes, and nothing while saving, when Cancel is off too.
    useDismissOnEscape(onDismiss, !isSubmitting, open)

    // What saving is doing, while it saves.
    const savingSteps = useSavingSteps(collectionSlug, token, isSubmitting && !!reviewing)

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
    /** The choices of what a source is, in a word each, with what each means in full. */
    const roleOptions = (allowed: SourceRole[]) => allowed.map((role) => ({
        value: role, label: role === 'season' ? 'Own' : role === 'part' ? 'Part' : 'Off', title: regs?.role.getLabel(role) ?? role,
    }))
    /** The choice of what one source is, all in view beside its name. */
    const roleControl = (title: string, value: SourceRole, onRole: (role: SourceRole) => void, allowed: SourceRole[]) => (
        <ChoiceBar ariaLabel={`What ${title} is`} value={value} options={roleOptions(allowed)} onChange={onRole}/>
    )

    /** What kind of list a list is, for its season's badge: a link the user gave, or the type of list it is at its Site. */
    const listKind = (playlist: CollectionListRead | undefined): Names => !view ? {singular: '', plural: '', a: ''}
        : playlist?.addedByUser ? view.linkNames
            : view.listTypes.find((type) => type.key === playlist?.typeKey)?.names ?? view.listTypes[0]?.names ?? view.sectionListNames
    // The seasons that sources are in, which other sources can join: lists, and the feeds that are a season.
    type Source = {key: string, title: string, home: boolean, own: () => void, kind: Names, tone: BadgeTone}
    // The season a source splits off to: the one it had before it joined another, while no other source took it since.
    const homeOf = (seasonId: number | null | undefined): number | null => seasonId !== null && seasonId !== undefined && seasonsById.has(seasonId)
        && !removedSeasons.includes(seasonId) && sourcesIn(seasonId).length === 0 ? seasonId : null
    const sourcesIn = (seasonId: number): Source[] => [
        ...channelFeeds.filter((feed) => roleOfFeed(feed.ref) === 'season' && feedSeasons[feed.ref] === seasonId).map((feed) => ({
            key: `feed-${feed.ref}`, title: capitalized(feed.names.plural), home: feed.seasonId === seasonId,
            own: () => setValue('feedSeasons', {...feedSeasons, [feed.ref]: homeOf(feed.seasonId)}, {shouldDirty: true}),
            kind: feed.names, tone: 'feed' as const,
        })),
        ...playlistChoices.filter((choice) => roleOfList(choice) === 'season' && choice.seasonId === seasonId).map((choice) => ({
            key: `list-${choice.id}`, title: playlistsById.get(choice.id)?.title ?? '', home: playlistsById.get(choice.id)?.seasonId === seasonId,
            // A list that leaves a season it shared goes back to its own season, or gets a new one when you save.
            own: () => setValue('playlists', playlistChoices.map((x) => x.id === choice.id ? {...x, seasonId: homeOf(playlistsById.get(choice.id)?.seasonId)} : x), {shouldDirty: true}),
            kind: listKind(playlistsById.get(choice.id)), tone: 'list' as const,
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

    /** The kinds of source a season holds, each once: what is part of the collection, and the kinds of list and feed
     * it is made of, such as Playlist, or Playlists for more than one. */
    const badgesOf = (id: number): Badge[] => {
        const x = seasonsById.get(id)
        if (!view || !x || x.seasonType === 'extra') return []
        const collection: Badge = {key: 'collection', label: capitalized(view.collectionNames.singular), tone: 'collection'}
        const kinds = (sources: {kind: Names, tone: BadgeTone}[]): Badge[] => {
            const tally = new Map<string, {kind: Names, tone: BadgeTone, count: number}>()
            for (const source of sources) {
                const at = tally.get(source.kind.plural) ?? {kind: source.kind, tone: source.tone, count: 0}
                tally.set(source.kind.plural, {...at, count: at.count + 1})
            }
            return [...tally.values()].map(({kind, tone, count}) => ({
                key: kind.plural, label: capitalized(count > 1 ? kind.plural : kind.singular), tone,
            }))
        }
        if (x.loose) return [collection]
        if (x.year !== null) {
            // A year holds what is part of the collection from that year: its own videos, and those of the lists that
            // are part of it.
            const parts = listsOn ? playlistChoices.filter((choice) => roleOfList(choice) === 'part') : []
            const own = view.kind !== 'channel' || channelFeeds.some((feed) => roleOfFeed(feed.ref) === 'part')
            return [...(own ? [collection] : []), ...kinds(parts.map((choice) => ({kind: listKind(playlistsById.get(choice.id)), tone: 'list' as const})))]
        }
        return kinds(sourcesIn(id))
    }

    const toggleSeason = (id: number) => setOpenSeasons((current) => {
        const next = new Set(current)
        if (!next.delete(id)) next.add(id)
        return next
    })

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
                <b>{x.name}</b>
                <span className="seasons-dialog-season-about">
                    <span className="seasons-dialog-badge">New</span>
                    <span>{counted(x.episodeCount, words.video, words.videos)} when you save</span>
                </span>
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
    const feedsAsSeasons = !!view && view.listsPlaylists

    /** On a phone, a group of settings folds to one row that says what they are set to. */
    const settingsFold = (key: 'lists' | 'seasons', title: string, summary: string[], body: ReactNode) => !narrow ? body : (
        <div className={`seasons-dialog-settings-fold${openSettings[key] ? ' is-open' : ''}`}>
            <button
                type="button" className="seasons-dialog-settings-summary" aria-expanded={openSettings[key]}
                onClick={() => setOpenSettings((current) => ({...current, [key]: !current[key]}))}
            >
                <span><b>{title}</b><span className="seasons-dialog-muted">{summary.filter(Boolean).join(' · ')}</span></span>
                <FontAwesomeIcon icon={faIcon('fass', openSettings[key] ? 'chevron-up' : 'chevron-down')} aria-hidden="true"/>
            </button>
            {openSettings[key] && body}
        </div>
    )

    /** How far the dialog's listing of a list for its review is. */
    const listingNote = (listing: {state: string, count: number} | undefined) => !listing ? null
        : listing.state === 'listing' ? `Listing its ${words.videos} for the review…`
            : listing.state === 'listed' ? `Listed for the review: ${counted(listing.count, words.video, words.videos)}`
                : `Could not list it now: VODLoft lists it after saving`
    /** The list is set otherwise than it is saved. */
    const changedRole = (choice: {id: number, enabled: boolean, asSeason?: boolean}) => {
        const saved = playlistsById.get(choice.id)
        return !!saved && setRoleOfList(choice) !== setRoleOfList({id: saved.id, enabled: saved.enabled, asSeason: saved.asSeason})
    }
    const roleLabel = (role: SourceRole) => regs?.role.getLabel(role) ?? role
    /** What the user changed that the review's settings do not name: the names and order of the seasons, the links
     * they add and remove, and what happens with a new list. */
    const formChanges = (values: CollectionSeasonsFormOut): CauseRow[] => {
        if (!view) return []
        const rows: CauseRow[] = []
        for (const x of values.seasons) {
            const was = seasonsById.get(x.id)
            if (was && was.name !== x.name.trim()) rows.push({key: `name-${x.id}`, setting: `${season.Singular} ${was.seasonNumber}`, before: was.name, after: x.name.trim()})
        }
        const reordered = values.seasons.some((x, index) => view.seasons[index]?.id !== x.id)
        if (values.customSeasonOrder !== view.customSeasonOrder || (values.customSeasonOrder && reordered)) {
            rows.push({key: 'order', setting: 'Order', before: view.customSeasonOrder ? 'Your own' : "VODLoft's", after: values.customSeasonOrder ? (reordered ? 'Your new order' : 'Your own') : "VODLoft's"})
        }
        for (const link of values.addedLinks) {
            rows.push({key: `link-${link.url}`, setting: link.title, before: 'New link', after: roleLabel(link.asSeason ? 'season' : 'part')})
        }
        for (const id of values.removedLinks) {
            rows.push({key: `removed-${id}`, setting: playlistsById.get(id)?.title ?? 'Link', before: 'Link', after: 'Removed'})
        }
        if (regs) {
            for (const kind of view.newLists) {
                const now = values.newLists[kind.key]
                if (now && now !== kind.action) {
                    const registry = regs.newLinks(kind)
                    rows.push({key: `new-${kind.key}`, setting: `When the ${words.creator} adds ${kind.names.a}`, before: registry.getLabel(kind.action), after: registry.getLabel(now)})
                }
            }
        }
        return rows
    }
    // What the dialog lists for its review, one step each, as the review shows them while it waits.
    const listingSteps: ProgressStep[] = (listings?.listings ?? []).flatMap((listing) => {
        const title = listing.listId !== null ? playlistsById.get(listing.listId)?.title : newLinks.find((link) => link.url === listing.link)?.title
        if (!title) return []
        return [{
            id: `${listing.listId ?? listing.link}`, label: title, percent: null,
            state: listing.state === 'listing' ? 'running' as const : listing.state === 'listed' ? 'completed' as const : 'failed' as const,
        }]
    })

    /** One source: its name, what it has, and what it is in the collection. */
    const sourceRow = (row: {key: string, title: string, details: (string | null)[], role: SourceRole, onRole: (role: SourceRole) => void,
                             seasonsToo?: boolean, badge?: string, changed?: boolean, actions?: ReactNode}) => (
        <li key={row.key} className={`seasons-dialog-source${row.role === 'off' ? ' is-off' : ''}`}>
            <span className="seasons-dialog-link-copy">
                <b>{row.title}</b>
                {(row.badge || row.changed || row.details.some(Boolean)) && (
                    <span>
                        {row.badge && <span className="seasons-dialog-badge">{row.badge}</span>}
                        {row.changed && <span className="seasons-dialog-badge is-changed">Changed</span>}
                        {row.details.filter(Boolean).join(' · ')}
                    </span>
                )}
            </span>
            {row.actions}
            {roleControl(row.title, row.role, row.onRole, row.seasonsToo === false ? ['part', 'off'] : ['season', 'part', 'off'])}
        </li>
    )
    const listRow = ({choice, playlist}: {choice: {id: number, enabled: boolean, asSeason?: boolean, seasonId: number | null}, playlist: CollectionListRead},
                     actions?: ReactNode, details?: (string | null)[]) => sourceRow({
        key: `list-${playlist.id}`, title: playlist.title, role: setRoleOfList(choice),
        badge: playlist.status === 'new' ? 'New' : undefined,
        changed: changedRole(choice),
        details: [
            ...(details ?? [
                playlist.itemCount !== null ? counted(playlist.itemCount, words.video, words.videos) : null,
                playlist.firstVideoAt ? `since ${new Date(playlist.firstVideoAt).getFullYear()}` : null,
                roleOfList(choice) === 'season' ? sharedIn(choice.seasonId, playlist.title) : null,
            ]),
            listingNote(listingOf(playlist.id)),
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
    /** The head of a group of sources, which reads apart from them: with more than one, its choices set them all. */
    const totals = (title: string, all: string, roles: SourceRole[], onRole: (role: SourceRole) => void, seasonsToo = true) => (
        <div className="seasons-dialog-totals">
            <span className="seasons-dialog-totals-copy">
                <b>{roles.length > 1 ? all : title}</b>
                {roles.length > 1 && <span>Tap one to set them all</span>}
            </span>
            {roles.length > 1 && (
                <ChoiceBar
                    tiles ariaLabel={`Set ${all.toLowerCase()}`} options={roleOptions(seasonsToo ? ['season', 'part', 'off'] : ['part', 'off'])}
                    value={roles.every((role) => role === roles[0]) ? roles[0] : null} onChange={onRole}
                />
            )}
        </div>
    )

    return (
        <>
            <div className="modal-overlay" role="presentation" onClick={() => !isSubmitting && onDismiss()}>
                <div className={`modal seasons-dialog${narrow ? ' is-sheet' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}
                     onClick={(event) => event.stopPropagation()}>
                    <div className="modal-header seasons-dialog-header">
                        <h2 id={titleId} className="modal-title">{season.Plural} of {nameInText(collectionTitle)}</h2>
                        <ol className="seasons-dialog-steps" aria-label="Steps">
                            <li className={reviewing ? 'is-done' : 'is-current'} aria-current={reviewing ? undefined : 'step'}>
                                <span aria-hidden="true">{reviewing ? <FontAwesomeIcon icon={faIcon('fass', 'check')}/> : '1'}</span>
                                {season.Plural}
                            </li>
                            <li className={reviewing ? 'is-current' : undefined} aria-current={reviewing ? 'step' : undefined}>
                                <span aria-hidden="true">2</span>
                                Review what changes
                            </li>
                        </ol>
                    </div>
                    <form onSubmit={onSubmit} noValidate>
                        <div className="seasons-dialog-content">
                            {error && <div className="form-error-card" role="alert">{error.message}</div>}
                            {!view && !error && <p className="seasons-dialog-muted">Loading the {season.plural}…</p>}
                            {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}

                            {view && names && reviewing && isSubmitting && <SavingProgress steps={savingSteps}/>}
                            {view && names && reviewing && (
                                <SeasonsReview
                                    view={view} review={review} failed={reviewError ? reviewError.message : null}
                                    changes={formChanges(reviewing)} words={words}
                                    listName={view.creatorListNames.plural}
                                    listing={(listings?.listings ?? []).some((listing) => listing.state === 'listing')}
                                    listings={listingSteps}
                                    renumber={renumber} onRenumber={setRenumber} onBack={() => setReviewing(null)} folded={narrow}
                                />
                            )}
                            {view && names && regs && !reviewing && (
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
                                                    </div>
                                                    {!shut.feeds && totals(`Parts of the ${words.channel}`, `All parts of the ${words.channel}`,
                                                        channelFeeds.map((feed) => roleOfFeed(feed.ref)),
                                                        (role) => setFeedRoles(new Set(channelFeeds.map((feed) => feed.ref)), role), feedsAsSeasons)}
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
                                                                    {totals(group.title, `All ${group.title.toLowerCase()}`, group.rows.map((row) => setRoleOfList(row.choice)),
                                                                        (role) => setListRoles(new Set(group.rows.map((row) => row.choice.id)), role))}
                                                                    <ul className="seasons-dialog-sources">{group.rows.map((row) => listRow(row))}</ul>
                                                                </Fragment>
                                                            ))}

                                                            {totals('Your links', 'All your links', userLinks.filter((row) => !removedLinks.includes(row.playlist.id)).map((row) => setRoleOfList(row.choice)),
                                                                (role) => setListRoles(new Set(userLinks.map((row) => row.choice.id)), role))}
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
                                                                            <span>
                                                                                <span className="seasons-dialog-badge">New</span>
                                                                                {[link.url, 'Added when you save', listingNote(listingOfLink(link.url))].filter(Boolean).join(' · ')}
                                                                            </span>
                                                                        </span>
                                                                        <button type="button" className="btn btn-small" aria-label={`Remove ${link.title}`}
                                                                                onClick={() => setValue('addedLinks', newLinks.filter((x) => x.url !== link.url), {shouldDirty: true})}>
                                                                            Remove
                                                                        </button>
                                                                        {/* A link you add is in the collection: off would be the same as not adding it. */}
                                                                        {roleControl(link.title, link.asSeason === false ? 'part' : 'season', (role) => setValue(
                                                                            'addedLinks', newLinks.map((x) => x.url === link.url ? {...x, asSeason: role === 'season'} : x), {shouldDirty: true},
                                                                        ), ['season', 'part'])}
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

                                                            {(view.listsPlaylists || !only) && settingsFold('lists', 'Settings for these lists', [
                                                                ...(view.listsPlaylists ? view.newLists.map((kind) => `New ${kind.names.plural}: ${regs.newLinks(kind).getLabel(newLists[kind.key] ?? 'ask')}`) : []),
                                                                !only ? `Other ${words.creators}: ${regs.guests.getLabel(guests)}` : '',
                                                            ], (
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
                                                            ))}
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
                                        {(showRest || showAlsoHolds || showRepeat) && settingsFold('seasons', `${season.Singular} settings`, [
                                            showRest ? regs.rest.getLabel(byYear ? 'by_year' : 'one_season') : '',
                                            showAlsoHolds && looseVideos === 'everything' ? `${view.channelSeasonNames.everything} holds everything` : '',
                                            showRepeat ? regs.repeat.getLabel(repeatVideos) : '',
                                        ], (
                                            <div className="seasons-dialog-season-settings">
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
                                                    {/* Named the same whichever way it is set: ticked, the season is called Channel. */}
                                                    {view.channelSeasonNames.everything} also holds the {words.videos} that have {season.a} of their own
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
                                            </div>
                                        ))}
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
                                        {listsOn && newLinks.some((link) => link.asSeason !== false) && (
                                            <div className="seasons-dialog-warning" role="status">
                                                <FontAwesomeIcon icon={faIcon('fass', 'circle-info')} aria-hidden="true"/>
                                                <p>
                                                    When you save, {listed(newLinks.filter((link) => link.asSeason !== false).map((link) => link.title))}
                                                    {newLinks.filter((link) => link.asSeason !== false).length === 1 ? ` becomes ${season.a}` : ` each become ${season.a}`} here.
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
                                                // A season with a name the user has to fix stays open.
                                                const opened = openSeasons.has(field.id) || !!errors.seasons?.[index]?.name
                                                const nameNow = form.getValues(`seasons.${index}.name`) || season?.name || words.season.singular
                                                const about = (
                                                    <span className="seasons-dialog-season-about">
                                                        {badgesOf(field.id).map((badge) => (
                                                            <span key={badge.key} className={`seasons-dialog-kind-badge is-${badge.tone}`}>{badge.label}</span>
                                                        ))}
                                                        <span>
                                                            {deleted ? `Deleted, and made again${next && next.name !== season?.name ? ` as ${next.name}` : ''} by your settings when you save · ` : null}
                                                            {counted(counts, words.video, words.videos)}
                                                            {next && next.episodeCount !== counts ? `, ${counted(next.episodeCount, words.video, words.videos)} when you save` : null}
                                                        </span>
                                                    </span>
                                                )
                                                return (
                                                    <Fragment key={field.key}>
                                                    {(added.get(field.id) ?? []).map(addedRow)}
                                                    <li className={`seasons-dialog-season${dragging === index ? ' is-dragging' : ''}`} data-season-index={index}>
                                                        {/* Dragged by its handle, with a mouse and on a touch screen alike. */}
                                                        <span
                                                            className="seasons-dialog-grip" aria-hidden="true"
                                                            onPointerDown={(event) => {
                                                                event.preventDefault()
                                                                event.currentTarget.setPointerCapture(event.pointerId)
                                                                dragFrom.current = index
                                                                setDragging(index)
                                                            }}
                                                            onPointerMove={(event) => {
                                                                if (dragFrom.current === null) return
                                                                const over = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-season-index]')
                                                                const to = over ? Number(over.getAttribute('data-season-index')) : NaN
                                                                if (!Number.isNaN(to) && to !== dragFrom.current && staying[to]) {
                                                                    moveSeason(dragFrom.current, to)
                                                                    dragFrom.current = to
                                                                    setDragging(to)
                                                                }
                                                            }}
                                                            onPointerUp={() => { dragFrom.current = null; setDragging(null) }}
                                                            onPointerCancel={() => { dragFrom.current = null; setDragging(null) }}
                                                        >
                                                            <FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/>
                                                        </span>
                                                        <span className="seasons-dialog-number" aria-hidden="true">{number}</span>
                                                        {opened ? (
                                                            <span className="seasons-dialog-season-copy">
                                                                <span className="seasons-dialog-season-name">
                                                                    <input
                                                                        id={`seasons-name-${field.id}`}
                                                                        className="input" aria-label={`Name of ${words.season.singular} ${index + 1}`}
                                                                        aria-invalid={!!errors.seasons?.[index]?.name}
                                                                        {...register(`seasons.${index}.name`)}
                                                                    />
                                                                    <button
                                                                        type="button" className="seasons-dialog-fold" aria-expanded="true"
                                                                        aria-label={`Close ${nameNow}`} title="Close" onClick={() => toggleSeason(field.id)}
                                                                    >
                                                                        <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')} aria-hidden="true"/>
                                                                    </button>
                                                                </span>
                                                                {about}
                                                                {season && sourceSeasonIds.includes(season.id) && (
                                                                    <SeasonSources
                                                                        season={field.id} words={words} sources={sourcesIn(field.id)}
                                                                        joinRegistry={joinRegistry(field.id)}
                                                                        onJoin={(to) => joinSeason(field.id, to)} joinsName={joinsName(field.id)}
                                                                    />
                                                                )}
                                                                {season?.removable && (
                                                                    <button
                                                                        type="button" className={`btn btn-small seasons-dialog-delete${deleted ? '' : ' is-danger'}`}
                                                                        onClick={() => toggleSeasonRemoved(field.id)}
                                                                    >
                                                                        <FontAwesomeIcon icon={faIcon('fass', deleted ? 'rotate-left' : 'trash')} aria-hidden="true"/>
                                                                        {deleted ? `Keep this ${words.season.singular}` : `Delete ${words.season.singular}`}
                                                                    </button>
                                                                )}
                                                                {errors.seasons?.[index]?.name && <span className="error" role="alert">{errors.seasons[index]?.name?.message}</span>}
                                                            </span>
                                                        ) : (
                                                            <button
                                                                type="button" className="seasons-dialog-season-head" aria-expanded="false"
                                                                onClick={() => toggleSeason(field.id)}
                                                            >
                                                                <span className="seasons-dialog-season-copy">
                                                                    <b>{nameNow}</b>
                                                                    {about}
                                                                </span>
                                                                <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')} aria-hidden="true"/>
                                                            </button>
                                                        )}
                                                        {!narrow && (
                                                            <span className="seasons-dialog-arrows">
                                                                <button type="button" aria-label={`Move ${words.season.singular} ${index + 1} up`} disabled={up < 0} onClick={() => moveSeason(index, up)}>
                                                                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-up')}/>
                                                                </button>
                                                                <button type="button" aria-label={`Move ${words.season.singular} ${index + 1} down`} disabled={down < 0} onClick={() => moveSeason(index, down)}>
                                                                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-down')}/>
                                                                </button>
                                                            </span>
                                                        )}
                                                    </li>
                                                    </Fragment>
                                                )
                                            })}
                                            {(added.get(null) ?? []).map(addedRow)}
                                            {previewBody && (previewed?.waiting ?? []).map((list) => (
                                                <li key={`waiting-${list.listId}`} className="seasons-dialog-season is-new">
                                                    <span className="seasons-dialog-grip" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/></span>
                                                    <span className="seasons-dialog-number" aria-hidden="true"/>
                                                    <span className="seasons-dialog-season-copy">
                                                        <b>{list.title}</b>
                                                        <span className="seasons-dialog-season-about">
                                                            <span className="seasons-dialog-badge">New</span>
                                                            <span>Not indexed yet: VODLoft lists its {words.videos} after saving</span>
                                                        </span>
                                                    </span>
                                                </li>
                                            ))}
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
                            {reviewing && (
                                <button type="button" className="btn seasons-dialog-back" onClick={() => setReviewing(null)} disabled={isSubmitting}>
                                    <FontAwesomeIcon icon={faIcon('fass', 'arrow-left')} aria-hidden="true"/> Back
                                </button>
                            )}
                            <button type="button" className="btn" onClick={onDismiss} disabled={isSubmitting}>Cancel</button>
                            {reviewing ? (
                                <button type="submit" className="btn btn-primary" disabled={!reviewReady || isSubmitting}>
                                    {isSubmitting ? 'Saving…' : moves ? 'Save and move' : `Save ${season.plural}`}
                                </button>
                            ) : (
                                <button type="submit" className="btn btn-primary" disabled={!view || !isDirty}>
                                    Next <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')} aria-hidden="true"/>
                                </button>
                            )}
                        </div>
                    </form>
                </div>
            </div>

        </>
    )
}


/** What one open season of the Seasons dialog is made of: its lists and feeds, each but its own able to have a season
 * of its own again, and putting it together with another season. */
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
        <span className="seasons-dialog-made-of">
            <span className="seasons-dialog-made-of-title">Made of</span>
            <span className="seasons-dialog-made-of-list">
                {sources.map((source) => (
                    <span key={source.key} className="seasons-dialog-source-chip">
                        {source.title}
                        {sources.length > 1 && source !== home && (
                            <button type="button" onClick={source.own} title={`${capitalized(words.season.a)} of its own again`}
                                    aria-label={`Give ${source.title} ${words.season.a} of its own again`}>
                                <FontAwesomeIcon icon={faIcon('fass', 'xmark')} aria-hidden="true"/>
                            </button>
                        )}
                    </span>
                ))}
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
        </span>
    )
}
