import {useEffect, useMemo, useRef, useState} from 'react'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {collectionWords, creatorNamesFor} from '../../lib/collectionWords'
import {lookUpCreator, useCreators, useSourceLookup} from '../../lib/queries'
import {SourceFeature, sourceHas} from '../../types/schemas/source'
import {
    CreatorCreateSchema, type CreatorCreateIn, type CreatorCreateOut, type CreatorLookupRead, type CreatorSectionRead,
    type NewLists, type NewSectionAction, type SectionPlan, newListsValues, withNewList,
} from '../../types/schemas/creator'
import {DwMembershipLevelReg} from '../../types/dailywire_user_info'
import {CollectionTypeReg, EpisodeIdentifierReg, type CollectionTypeValue, type EpisodeIdentifierValue} from '../../types/collection'
import {useCollectionDefaults} from '../../components/AddCollectionPage/collectionDefaults'
import {capitalized, newListActionReg} from '../../types/creator'
import NewListSettings from '../../components/common/NewListSettings'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../../components/common/SimpleSelect'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import SegmentedOptions from '../../components/SegmentedOptions/SegmentedOptions'
import CreatorHeader from './CreatorHeader'
import LookupSteps from './LookupSteps'
import {useSlow} from '../../lib/useSlow'
import type {ProgressStep} from '../../types/progress'
import {SECTION_ACTIONS} from './sectionActions'
import AddToNewCollectionDialog from './AddToNewCollectionDialog'
import './CreatorPages.css'

/** The starting points, in the words of what this creator has: playlists on YouTube, shows on The Daily Wire. */
function presetText(key: CreatorCreateIn['preset'], hasFeeds: boolean, creator: CreatorLookupRead, music: boolean) {
    // What the Site calls the lists and shows its creators add, such as shows on The Daily Wire.
    const {singular, plural} = creator.sectionGrowingNames
    const skipped = {
        label: 'Only what I pick',
        help: `All ${hasFeeds ? `feeds and ${plural}` : plural} start skipped.`,
    }
    if (music) {
        // Where the Site marks some types of list as albums, such as SoundCloud's albums, only those are kept.
        const kept = creator.albumNames ?? {singular, plural}
        const rest = creator.skippedListNames ? ` ${capitalized(creator.skippedListNames.plural)} start skipped.` : ''
        if (key === 'one_show') return {label: 'One discography', help: `One Music collection, with ${kept.singular === 'album' ? 'every album' : `each ${kept.singular} as an album`}${hasFeeds ? ` and the other ${creator.mediaNames.plural} in the ${collectionWords('music').season.singular} ${creator.musicLooseSeason}` : ''}.${rest}`}
        if (key === 'per_list') return {label: 'A collection per album', help: `Each ${kept.singular} is a Music collection of its own.${rest}`}
        return skipped
    }
    if (key === 'one_show') {
        // A Site offers it only where its lists can be seasons, so not The Daily Wire's shows.
        return {label: 'One collection', help: `${capitalized(plural)} as named seasons, the rest in the ${collectionWords('series').season.singular} ${creator.looseSeason}.`}
    }
    if (key === 'per_list') {
        return {
            label: `A collection per ${singular}`,
            help: hasFeeds ? `Each of the ${plural} is a collection of its own, plus one for the other videos.` : `Each of the ${plural} is a collection of its own.`,
        }
    }
    return skipped
}

type Choice = 'main' | 'main_loose' | 'own' | 'exclude' | 'keep_out'
/** The select's own entries besides the targets: where the section goes now when that is another section's new
 *  collection, and the dialog that picks one. */
type ChoiceKey = Choice | 'into' | 'pick'

function choiceOf(plan: SectionPlan | undefined): ChoiceKey {
    return plan?.intoRef ? 'into' : plan?.target ?? 'exclude'
}

/** The title the new collection of a feed or list of its own gets, as the backend names it. */
function ownTitle(creator: CreatorLookupRead, section: CreatorSectionRead) {
    return section.kind === 'feed' ? `${creator.title} ${section.title}` : section.title
}

/** Where a feed or list goes when it joins another section's new collection, in words. */
function intoLabel(creator: CreatorLookupRead, section: CreatorSectionRead, plan: SectionPlan, music: boolean) {
    const target = creator.sections.find((item) => item.ref === plan.intoRef)
    const title = target ? ownTitle(creator, target) : plan.intoRef
    if (section.kind === 'feed') return `In ${title}`
    const {season} = collectionWords(music ? 'music' : 'series')
    return plan.target === 'main_loose' ? `Add its contents to ${title}` : `${season.Singular} of ${title}`
}

/** The feeds and lists set to become a collection of their own that ``section`` can go into: a feed's always, a
 *  list's where lists can be seasons, as on the Edit page. A Site's main feed has the main collection's link. */
function intoChoices(creator: CreatorLookupRead, section: CreatorSectionRead, plans: SectionPlan[]): CreatorSectionRead[] {
    if (section.kind !== 'feed' && !(section.kind === 'list' && creator.linkSeasons)) return []
    if (section.kind === 'feed' && section.role === 'main') return []
    const owning = new Set(plans.filter((plan) => plan.target === 'own').map((plan) => plan.ref))
    return creator.sections.filter((other) => other.ref !== section.ref && owning.has(other.ref) && !other.collectionSlug && (
        other.kind === 'feed' || (other.kind === 'list' && creator.linkSeasons)
    ))
}

/** What happens with a list of each kind the creator adds later, to start with, as the server says: an artist's new
 *  albums are new albums of theirs, and kinds that aren't albums are skipped; anyone else is asked. */
function newListsFor(creator: CreatorLookupRead, music: boolean): NewLists {
    return newListsValues(music ? creator.musicNewLists : creator.newLists)
}


/** What the Site's sections can become, in the words of this creator: the creator's own collection first, then the
 *  new collection of another feed or list (``into`` is where it goes now, ``pick`` asks for one), then the rest. */
function choicesFor(creator: CreatorLookupRead, section: CreatorSectionRead, music: boolean, plans: SectionPlan[]) {
    if (isMovie(creator, section)) {
        // A movie in the library joins the creator; another one is added to the library, as one of theirs.
        return createSelectRegistry(`CreatorMovie-${creator.ref}-${section.ref}-${creator.title}-${!!section.movieSlug}`, (
            section.movieSlug
                ? {own: {label: `Joins ${creator.title}`}, exclude: {label: 'Stays apart'}}
                : {own: {label: 'Add to your library'}, exclude: {label: 'Skip'}}
        ) as Record<Choice, {label: string}>)
    }
    const spec: Partial<Record<ChoiceKey, {label: string}>> = {}
    // The same names as where the Edit page says each one is: the creator's main collection is named after them.
    const {season} = collectionWords(music ? 'music' : 'series')
    // The new collection puts the videos in none of its lists in one season, such as the album Singles.
    if (section.kind === 'feed') {
        spec.main = {label: creator.linkSeasons ? `In ${creator.title} as ${season.singular} ${music ? creator.musicLooseSeason : creator.looseSeason}` : `In ${creator.title}`}
    } else if (section.kind === 'list' && creator.linkSeasons) {
        spec.main = {label: `${season.Singular} of ${creator.title}`}
        spec.main_loose = {label: `Add its contents to ${creator.title}`}
    }
    const plan = plans.find((item) => item.ref === section.ref)
    if (plan?.intoRef) spec.into = {label: intoLabel(creator, section, plan, music)}
    if (intoChoices(creator, section, plans).length) spec.pick = {label: SECTION_ACTIONS.collection}
    spec.own = {label: SECTION_ACTIONS.own}
    spec.exclude = {label: SECTION_ACTIONS.skip}
    // Its videos stay out of every collection of the creator, also when another feed or list has them.
    if (section.kind === 'list') spec.keep_out = {label: SECTION_ACTIONS.keepOut(creator.mediaNames)}
    return createSelectRegistry(
        `CreatorSection-${creator.ref}-${section.ref}-${music}-${Object.values(spec).map((item) => item.label).join('|')}`,
        spec as Record<ChoiceKey, {label: string}>,
    )
}

/** Whether a line goes above the choice: above the other collections, and above the choices after them. */
function separated(registry: ReturnType<typeof choicesFor>, value: string) {
    const keys: string[] = registry.options.map((option) => option.value)
    const first = keys.find((key) => key === 'into' || key === 'pick')
    return keys.indexOf(value) > 0 && (value === first || value === 'own')
}

/** A single item that is a movie, which VODLoft adds from this page, unlike a single track. */
function isMovie(creator: CreatorLookupRead, section: CreatorSectionRead) {
    return section.kind === 'item' && creator.movies
}

/** What the section is and holds, in the words of its Site: "Album · 2016 · 12 tracks", or "12 shorts" for a feed,
 * which is named after its type already. */
function sectionFacts(creator: CreatorLookupRead, section: CreatorSectionRead): string {
    const feed = section.kind === 'feed'
    const media = feed ? section.names : creator.mediaNames
    return [
        feed ? null : capitalized(section.names.singular),
        section.year,
        section.itemCount != null ? `${section.itemCount} ${section.itemCount === 1 ? media.singular : media.plural}` : null,
    ].filter(Boolean).join(' · ')
}

/** What the lookup has done so far, over the shape of the page it is filling in. */
function AddCreatorSkeleton({steps, label}: {steps: ProgressStep[], label: string}) {
    return (
        <div className="creator-skeleton" aria-busy="true">
            <LookupSteps steps={steps} first={label ? `Looking the ${label} up` : 'Looking it up'}/>
            <div className="creator-header" aria-hidden="true">
                <div className="creator-banner skeleton-block"/>
                <span className="creator-avatar skeleton-block"/>
                <span className="creator-name skeleton-block creator-skeleton-line creator-skeleton-line--title"/>
                <div className="creator-about creator-skeleton-copy">
                    <span className="skeleton-block creator-skeleton-line"/>
                    <span className="skeleton-block creator-skeleton-line creator-skeleton-line--short"/>
                </div>
            </div>
            <div className="creator-presets" aria-hidden="true">
                {[0, 1, 2].map((key) => <div key={key} className="skeleton-block creator-skeleton-preset"/>)}
            </div>
            <div className="creator-section-group" aria-hidden="true">
                <span className="skeleton-block creator-skeleton-line creator-skeleton-line--heading"/>
                <div className="creator-section-list">
                    {[0, 1, 2, 3].map((key) => (
                        <div key={key} className="creator-section-row">
                            <span className="creator-section-art skeleton-block"/>
                            <div className="creator-section-copy creator-skeleton-copy">
                                <span className="skeleton-block creator-skeleton-line creator-skeleton-line--title-small"/>
                                <span className="skeleton-block creator-skeleton-line creator-skeleton-line--short"/>
                            </div>
                            <span className="creator-section-choice skeleton-block creator-skeleton-choice"/>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

/** The key of the creator's own collection among the new collections' settings; the others go by their section. */
const MAIN_KEY = '__main__'

/** Only an artist's collections hold music, and those never show these settings. */
const NewCollectionTypeReg = createSelectRegistry('CreatorNewCollectionType', {
    podcast: CollectionTypeReg.meta('podcast')!,
    series: CollectionTypeReg.meta('series')!,
})

/** ``list`` says it is made from one of the creator's lists, such as a playlist. */
type NewCollection = {key: string, title: string, url: string | null, list: boolean}
type CollectionSettings = {type: CollectionTypeValue | '', episodeIdentifier: EpisodeIdentifierValue | ''}

/**
 * The type and episode identification of one collection the creator adds. It starts with what Add collection
 * suggests for the same link, looked up the same way, until the user chooses.
 */
function NewCollectionCard({item, value, onChange}: {
    item: NewCollection
    value: CollectionSettings | undefined
    onChange: (key: string, value: CollectionSettings) => void
}) {
    const suggestion = useCollectionDefaults(item.url ?? undefined, item.list)
    const chosen = useRef(false)
    useEffect(() => {
        if (chosen.current) return
        if (suggestion.defaults) onChange(item.key, suggestion.defaults)
        // Without a suggestion, it starts as every collection of a creator used to.
        else if (suggestion.error || !item.url) onChange(item.key, {type: 'series', episodeIdentifier: 'seasonal'})
    }, [suggestion.defaults, suggestion.error, item.key, item.url, onChange])
    const choose = (next: CollectionSettings) => {
        chosen.current = true
        onChange(item.key, next)
    }
    const field = (name: keyof CollectionSettings, label: string, registry: typeof NewCollectionTypeReg | typeof EpisodeIdentifierReg) => {
        const id = `creator-new-collection-${item.key}-${name}`
        const current = value?.[name] || null
        return (
            <div className="form-row">
                <label htmlFor={id}>{label}</label>
                <SimpleSelect
                    inputId={id} registry={registry} value={current}
                    isDisabled={suggestion.isLoading}
                    placeholder={suggestion.isLoading ? 'Looking it up…' : 'Choose…'}
                    onChange={(next) => choose({type: value?.type ?? '', episodeIdentifier: value?.episodeIdentifier ?? '', [name]: next ?? ''})}
                />
                {current && <div className="help">{registry.meta(current as never)?.help}</div>}
            </div>
        )
    }
    return (
        <div className="creator-new-collection" role="listitem">
            <b>{item.title}</b>
            {field('type', 'Collection type', NewCollectionTypeReg)}
            {field('episodeIdentifier', 'Episode identification', EpisodeIdentifierReg)}
        </div>
    )
}

export default function AddCreatorPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [params] = useSearchParams()
    const sourceKey = params.get('source') ?? ''
    const url = params.get('url')
    const ref = params.get('ref')
    const [creator, setCreator] = useState<CreatorLookupRead | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [steps, setSteps] = useState<ProgressStep[]>([])
    // What the Site calls the creator, which the backend tells with the lookup's first step.
    const [label, setLabel] = useState('')
    // The type and episode identification of each collection the creator adds, by MAIN_KEY or the section's ref.
    const [collectionSettings, setCollectionSettings] = useState<Record<string, CollectionSettings>>({})
    const setSettings = useMemo(() => (key: string, value: CollectionSettings) => {
        setCollectionSettings((all) => all[key]?.type === value.type && all[key]?.episodeIdentifier === value.episodeIdentifier ? all : {...all, [key]: value})
    }, [])

    const form = useForm<CreatorCreateIn, unknown, CreatorCreateOut>({
        resolver: zodResolver(CreatorCreateSchema),
        defaultValues: {...getZodDefaults(CreatorCreateSchema), sourceKey, url, ref},
    })
    const {watch, setValue, formState: {errors, isSubmitting}} = form
    const {data: libraryCreators} = useCreators()
    const sources = useSourceLookup()
    const into = watch('into') ?? ''
    const music = watch('type') === 'music'
    // A music artist is called an artist everywhere on the page, whatever their site calls its creators.
    const creatorWord = creator ? creatorNamesFor(watch('type'), creator.creatorNames).singular : label
    const intoRegistry = useMemo(() => createSelectRegistry(`AddCreatorInto-${(libraryCreators ?? []).length}-${creatorWord}`, {
        '': {label: `A new ${creatorWord} in your library`},
        ...Object.fromEntries((libraryCreators ?? []).map((other) => [
            other.slug, {label: `${other.title} (${other.kind})`, help: 'The same person or group: this account joins them, with their settings.'},
        ])),
    }), [libraryCreators, creatorWord])
    const intoTitle = libraryCreators?.find((other) => other.slug === into)?.title
    // A lookup found already answers in a moment, so its progress only shows once it takes a while.
    const slow = useSlow(!creator && !error)

    useEffect(() => {
        const controller = new AbortController()
        setSteps([])
        lookUpCreator({sourceKey, url, ref}, {onPlan: setSteps, onNames: (names) => setLabel(names.singular)}, controller.signal)
            .then((found) => {
                setCreator(found)
                setLabel(found.creatorNames.singular)
                setValue('type', found.music ? 'music' : 'series')
                setValue('newLists', newListsFor(found, found.music))
                const preset = found.presets[0]
                if (preset) {
                    setValue('preset', preset.key)
                    setValue('sections', found.music ? preset.musicPlan : preset.plan)
                }
            })
            .catch((exc) => { if (!controller.signal.aborted) setError(exc instanceof Error ? exc.message : String(exc)) })
        return () => controller.abort()
    }, [sourceKey, url, ref, setValue])

    const plans = watch('sections') ?? []
    const preset = watch('preset')
    const membershipLevel = watch('membershipLevel')
    const newLists = watch('newLists') ?? {}
    const newListKinds = creator ? (music ? creator.musicNewLists : creator.newLists) : []
    const byRef = useMemo(() => new Map(plans.map((plan) => [plan.ref, plan])), [plans])
    const registries = useMemo(
        () => new Map((creator?.sections ?? []).map((section) => [section.ref, choicesFor(creator!, section, music, plans)])),
        [creator, music, plans],
    )
    // The feed or list whose new collection to pick for another one to go into.
    const [picking, setPicking] = useState<CreatorSectionRead | null>(null)
    // Every choice select is as wide as the longest choice any of them has, so they line up.
    const choiceLabels = useMemo(() => (creator?.sections ?? [])
        .filter((section) => (section.kind !== 'item' || isMovie(creator!, section)) && !section.collectionSlug)
        .flatMap((section) => registries.get(section.ref)?.options.map((option) => option.label) ?? []),
    [creator, registries])

    const choosePreset = (key: CreatorCreateIn['preset'], asArtist = music) => {
        const chosen = creator?.presets.find((item) => item.key === key)
        if (!chosen || !key) return
        setValue('preset', key)
        setValue('sections', asArtist ? chosen.musicPlan : chosen.plan, {shouldValidate: true})
    }
    // An artist starts from what the preset keeps of an artist, such as only their albums on YouTube.
    const chooseKind = (kind: 'series' | 'music') => {
        setValue('type', kind, {shouldValidate: true})
        if (creator) setValue('newLists', newListsFor(creator, kind === 'music'))
        choosePreset(preset ?? creator?.presets[0]?.key, kind === 'music')
    }
    const choose = (section: string, choice: ChoiceKey, intoRef?: string) => {
        if (choice === 'into') return
        if (choice === 'pick') {
            setPicking(creator?.sections.find((item) => item.ref === section) ?? null)
            return
        }
        // A section that no longer gets a collection of its own takes the ones that joined it into the creator's own.
        const left = choice !== 'own' && byRef.get(section)?.target === 'own'
        setValue('sections', plans.map((plan) => plan.ref === section
            ? {ref: section, target: choice, ...(intoRef ? {intoRef} : {})}
            : left && plan.intoRef === section ? {ref: plan.ref, target: plan.target} : plan,
        ), {shouldValidate: true})
    }

    const onSubmit = buildServerAwareSubmit<CreatorCreateIn, CreatorCreateOut>(form, (data) => fetch(`${apiUrl()}/creators`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            sourceKey: data.sourceKey, url: data.url, ref: data.ref, lookupId: creator?.lookupId ?? null,
            // An artist's collections always hold music and are always seasonal, so they take no settings.
            sections: data.type === 'music' ? data.sections : data.sections.map((plan) => (
                plan.target === 'own' && collectionSettings[plan.ref] ? {...plan, ...collectionSettings[plan.ref]} : plan
            )),
            membershipLevel: data.membershipLevel, newLists: data.newLists, into: data.into || null,
            type: data.type === 'music' ? 'music' : collectionSettings[MAIN_KEY]?.type || 'series',
            ...(data.type !== 'music' && collectionSettings[MAIN_KEY]?.episodeIdentifier
                ? {episodeIdentifier: collectionSettings[MAIN_KEY].episodeIdentifier} : {}),
        }),
    }), {
        fallbackField: 'sections',
        onSuccess: (created: any) => {
            // The creator's page loads on its own, so the lists it changed refresh behind it.
            void queryClient.invalidateQueries({queryKey: ['creators']})
            void queryClient.invalidateQueries({queryKey: ['collections']})
            void queryClient.invalidateQueries({queryKey: ['collectionsView']})
            void queryClient.invalidateQueries({queryKey: ['movies']})
            navigate(`/creator/${created.slug}`, {replace: true})
        },
    })

    if (error) {
        return (
            <section className="view" aria-labelledby="add-creator-title">
                <div className="view-header"><h1 id="add-creator-title">{label ? `Add ${label}` : 'Add'}</h1></div>
                <div className="form-error-card" role="alert">{error}</div>
                <div className="actions"><button type="button" className="btn" onClick={() => navigate(-1)}>Back</button></div>
            </section>
        )
    }
    if (!creator) {
        return (
            <section className="view creator-view" aria-labelledby="add-creator-title">
                <div className="view-header"><h1 id="add-creator-title">{label ? `Add ${label}` : 'Add'}</h1></div>
                {slow && <AddCreatorSkeleton steps={steps} label={label}/>}
            </section>
        )
    }
    if (creator.creatorSlug) {
        return (
            <section className="view" aria-labelledby="add-creator-title">
                <div className="view-header"><h1 id="add-creator-title">{label ? `Add ${label}` : 'Add'}</h1></div>
                <p>{creator.title} on {creator.siteName} is already in your library.</p>
                <div className="actions">
                    <button type="button" className="btn btn-primary" onClick={() => navigate(`/creator/${creator.creatorSlug}`)}>
                        Open {creator.creatorNames.singular}
                    </button>
                </div>
            </section>
        )
    }

    // What the creator's Site calls its lists and shows, such as "albums and playlists" on SoundCloud.
    const lists = creator.sectionGrowingNames.plural
    const media = (type: string) => collectionWords(type, creator.audioOnly ? 'audio' : 'video')
    const hasFeeds = creator.sections.some((section) => section.kind === 'feed')
    const feeds = new Set(creator.sections.filter((section) => section.kind === 'feed').map((section) => section.ref))
    const keepsFeeds = (plan: SectionPlan[]) => plan.some((item) => feeds.has(item.ref) && item.target !== 'exclude' && item.target !== 'keep_out')
    // A Daily Wire host has no collection of their own: each show is one.
    const hasMain = [...registries.values()].some((registry) => registry.options.some((option) => option.value === 'main'))
    // A group for each type of section the Site has, in its words and order: Feeds and Playlists on YouTube, or
    // Albums, Playlists and Singles on SoundCloud.
    // Every feed goes under one heading, Feeds, as each feed is named after its type already; each type of list,
    // show or item has a heading of its own.
    const named = new Map<string, CreatorSectionRead[]>()
    for (const type of creator.sectionTypes) {
        for (const section of creator.sections.filter((section) => section.type === type.key)) {
            const many = capitalized((section.kind === 'feed' ? section.kindNames : section.names).plural)
            named.set(many, [...(named.get(many) ?? []), section])
        }
    }
    const groups: [string, CreatorSectionRead[]][] = [...named.entries()]
    // What is in the library already stays where it is, so it makes no collection.
    const inLibrary = new Set(creator.sections.filter((section) => section.collectionSlug).map((section) => section.ref))
    const sectionOf = new Map(creator.sections.map((section) => [section.ref, section]))
    const kept = plans.filter((plan) => plan.target !== 'exclude' && plan.target !== 'keep_out' && !inLibrary.has(plan.ref))
    const keptMovies = kept.filter((plan) => sectionOf.get(plan.ref)?.kind === 'item')
    const newMovies = keptMovies.filter((plan) => !sectionOf.get(plan.ref)?.movieSlug).map((plan) => sectionOf.get(plan.ref)!.title)
    const joiningMovies = keptMovies.filter((plan) => sectionOf.get(plan.ref)?.movieSlug).map((plan) => sectionOf.get(plan.ref)!.movieTitle ?? sectionOf.get(plan.ref)!.title)
    const mainFeed = creator.sections.find((section) => section.kind === 'feed' && section.role === 'main')
    const newCollections: NewCollection[] = [
        // A collection of the main feed left in the library, such as after the creator was deleted, becomes theirs again.
        ...(kept.some((plan) => plan.target === 'main' && !plan.intoRef) && !mainFeed?.collectionSlug ? [{key: MAIN_KEY, title: intoTitle ?? creator.title, url: mainFeed?.url ?? creator.url, list: false}] : []),
        ...kept.filter((plan) => plan.target === 'own' && sectionOf.get(plan.ref)?.kind !== 'item').map((plan) => {
            const section = sectionOf.get(plan.ref)
            return {
                key: plan.ref,
                title: section?.kind === 'feed' ? `${creator.title} ${section.title}` : section?.title ?? plan.ref,
                url: section?.url ?? null,
                list: section?.kind === 'list',
            }
        }),
    ]
    const collectionTitles = newCollections.map((item) => item.title)
    // Each new collection needs its settings before the creator can be added.
    const unsettled = !music && newCollections.some((item) => !collectionSettings[item.key]?.type || !collectionSettings[item.key]?.episodeIdentifier)
    const summaryParts = [
        collectionTitles.length ? `Creates ${collectionTitles.length} ${collectionTitles.length === 1 ? 'collection' : 'collections'}` : null,
        newMovies.length ? `adds ${newMovies.length} ${newMovies.length === 1 ? 'movie' : 'movies'}` : null,
        joiningMovies.length ? `adds ${joiningMovies.length} of yours` : null,
    ].filter((part): part is string => !!part)
    const summaryTitles = [...collectionTitles, ...newMovies, ...joiningMovies]
    const summary = summaryParts.length
        ? `${capitalized(summaryParts.length > 1 ? `${summaryParts.slice(0, -1).join(', ')} and ${summaryParts[summaryParts.length - 1]}` : summaryParts[0])}: ${
            summaryTitles.length > 4 ? `${summaryTitles.slice(0, 3).join(', ')} and ${summaryTitles.length - 3} more` : summaryTitles.join(', ')}`
        : 'Nothing picked yet'

    return (
        <section className="view creator-view" aria-labelledby="add-creator-title">
            <div className="view-header">
                <div>
                    <h1 id="add-creator-title">Add {creatorWord}</h1>
                    <p className="view-description">
                        Choose where each part of this {creatorWord} goes.
                        {hasMain ? ` The main collection is called ${creator.title}; anything you give a collection of its own gets one.` : ''}
                        {' '}{capitalized(media(music ? 'music' : 'series').episode.a)} that is in several places is kept once.
                    </p>
                </div>
            </div>

            <CreatorHeader
                title={creator.title} label={`${creator.siteName} ${creatorWord}`} handle={creator.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts} description={creator.description}
            />

            <form className="form form-fluid creator-setup" onSubmit={onSubmit} noValidate>
                {!creator.musicKnown && (
                    <div className="form-row creator-artist-choice">
                        <label id="creator-kind-label">What is {creator.title}?</label>
                        <SegmentedOptions<'series' | 'music'>
                            name="creator-kind"
                            ariaLabelledBy="creator-kind-label"
                            value={music ? 'music' : 'series'}
                            onChange={(value) => chooseKind(value as 'series' | 'music')}
                            options={[
                                {
                                    value: 'series',
                                    label: capitalized(creator.creatorNames.singular),
                                    description: `Series collections of their ${creator.mediaNames.plural}, with ${lists} as ${media('series').season.plural}`,
                                },
                                {
                                    value: 'music',
                                    label: `Music ${creatorNamesFor('music', creator.creatorNames).singular}`,
                                    description: `Music collections, with ${lists} as ${media('music').season.plural} and their ${creator.mediaNames.plural} as ${media('music').episode.plural}`,
                                },
                            ]}
                        />
                        <div className="help">
                            {creator.music && creator.musicReason
                                ? `${creator.musicReason}, so VODLoft took it for a music artist. Pick ${capitalized(creator.creatorNames.singular)} if it isn't.`
                                : `${creator.siteName} doesn't say whether this is a music artist. Pick Music artist if it is.`}
                        </div>
                        {errors.type && <div className="error" role="alert">{errors.type.message}</div>}
                    </div>
                )}
                {creator.presets.length > 1 && (
                    <fieldset className="creator-presets">
                        <legend>Presets for this {creatorWord}</legend>
                        {creator.presets.map((item) => (
                            <label key={item.key} className={`creator-preset${preset === item.key ? ' is-on' : ''}`}>
                                <input type="radio" name="preset" checked={preset === item.key} onChange={() => choosePreset(item.key)}/>
                                <b>{presetText(item.key, music ? keepsFeeds(item.musicPlan) : hasFeeds, creator, music).label}</b>
                                <span>{presetText(item.key, music ? keepsFeeds(item.musicPlan) : hasFeeds, creator, music).help}</span>
                            </label>
                        ))}
                    </fieldset>
                )}

                {(libraryCreators?.length ?? 0) > 0 && (
                    <div className="form-row creator-membership">
                        <label htmlFor="creator-into">Add {creatorWord} as</label>
                        <SimpleSelect
                            inputId="creator-into" registry={intoRegistry} value={into}
                            onChange={(value) => setValue('into', value ?? '', {shouldValidate: true})}
                        />
                        <div className="help">
                            {into
                                ? `${creator.title} on ${creator.siteName} becomes an account of ${intoTitle}, next to their accounts on other sites. Its collections join theirs.`
                                : `Or pick a creator in your library who is the same person or group, such as a host whose YouTube channel you add.`}
                        </div>
                        {errors.into && <div className="error" role="alert">{errors.into.message}</div>}
                    </div>
                )}

                {groups.filter(([, sections]) => sections.length).map(([title, sections]) => (
                    <div key={title} className="creator-section-group">
                        <h2>{title}</h2>
                        <div className="creator-section-list">
                            {sections.map((section) => (
                                <div key={section.ref} className="creator-section-row">
                                    {section.imageUrl
                                        ? <img className="creator-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
                                        : <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : section.kind === 'item' ? 'film' : 'list')}/></span>}
                                    <div className="creator-section-copy">
                                        <b>{section.title}</b>
                                        <span>
                                            {section.movieSlug && isMovie(creator, section) ? (
                                                <><span className="creator-section-chip">In your library</span> as {section.movieTitle ?? section.title}</>
                                            ) : section.collectionSlug
                                                ? `Already in your library as ${section.collectionTitle ?? section.collectionSlug}`
                                                : section.access
                                                    ? 'Only some members can watch this. Pick it if VODLoft signs in as one.'
                                                    : sectionFacts(creator, section)}
                                        </span>
                                    </div>
                                    {section.kind === 'item' && !isMovie(creator, section) ? (
                                        <span className="creator-section-note">Add it from its own page</span>
                                    ) : section.collectionSlug ? (
                                        <span className="creator-section-note">Stays where it is</span>
                                    ) : (
                                        <div className="creator-section-choice">
                                            <SimpleSelect
                                                aria-label={`Where ${section.title} goes`}
                                                registry={registries.get(section.ref)!}
                                                fitLabels={choiceLabels}
                                                value={choiceOf(byRef.get(section.ref))}
                                                onChange={(value) => choose(section.ref, value as ChoiceKey)}
                                                menuPortalTarget={document.body} menuPlacement="auto"
                                                styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                                                // Lines set the other collections apart from the creator's own and from the rest.
                                                classNames={{option: ({data}) => separated(registries.get(section.ref)!, data.value) ? 'creator-choice-separated' : ''}}
                                            />
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}


                {picking && (
                    <AddToNewCollectionDialog
                        section={picking}
                        collections={intoChoices(creator, picking, plans).map((section) => ({ref: section.ref, title: ownTitle(creator, section)}))}
                        plan={byRef.get(picking.ref)}
                        seasons={picking.kind === 'list' && creator.linkSeasons}
                        season={collectionWords(music ? 'music' : 'series').season}
                        media={picking.kind === 'feed' ? picking.names.plural : creator.mediaNames.plural}
                        onPick={(intoRef, asSeason) => {
                            choose(picking.ref, asSeason ? 'main' : 'main_loose', intoRef)
                            setPicking(null)
                        }}
                        onDismiss={() => setPicking(null)}
                    />
                )}

                {!into && <div className="creator-section-group">
                    <h2>When a new {creator.newListNames.singular} is added</h2>
                    <NewListSettings
                        kinds={newListKinds} valueOf={(kind) => newLists[kind.siteKey ?? '']?.[kind.key]} fallback="ask"
                        idPrefix="creator-new-lists" registryFor={(kind) => newListActionReg(creatorWord, kind, music)}
                        onChange={(kind, value) => setValue('newLists', withNewList(newLists, kind, value as NewSectionAction))}
                    />
                    {errors.newLists && <div className="error" role="alert">{(errors.newLists as {message?: string}).message}</div>}
                    <div className="help">VODLoft looks for new ones once a day.</div>
                </div>}

                {sourceHas(sources.get(sourceKey), SourceFeature.MEMBERSHIP_LEVELS) && (
                    <div className="form-row creator-membership">
                        <label htmlFor="creator-membership">Membership level</label>
                        <SimpleSelect
                            inputId="creator-membership" registry={DwMembershipLevelReg} value={membershipLevel}
                            onChange={(value) => setValue('membershipLevel', value as CreatorCreateIn['membershipLevel'])}
                        />
                        <div className="help">{DwMembershipLevelReg.meta(membershipLevel as never)?.help}</div>
                        {errors.membershipLevel && <div className="error" role="alert">{errors.membershipLevel.message}</div>}
                    </div>
                )}

                {!music && newCollections.length > 0 && (
                    <div className="creator-section-group">
                        <h2>New collections</h2>
                        <div className="creator-new-collections" role="list" aria-label="New collections">
                            {newCollections.map((item) => (
                                <NewCollectionCard key={item.key} item={item} value={collectionSettings[item.key]} onChange={setSettings}/>
                            ))}
                        </div>
                    </div>
                )}

                {errors.sections && <div className="form-error-card" role="alert">{errors.sections.message ?? errors.sections.root?.message}</div>}

                <div className="actions">
                    <span className="creator-summary">{summary}</span>
                    <button type="button" className="btn" onClick={() => navigate(-1)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !summaryParts.length || unsettled}>
                        {isSubmitting ? 'Adding…' : into ? `Add to ${intoTitle}` : `Add ${creatorWord}`}
                    </button>
                </div>
            </form>
        </section>
    )
}
