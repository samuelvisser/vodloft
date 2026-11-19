import {useEffect, useMemo, useRef, useState} from 'react'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {lookUpCreator, useCreators} from '../../lib/queries'
import {
    CreatorCreateSchema, type CreatorCreateIn, type CreatorCreateOut, type CreatorLookupRead, type CreatorSectionRead,
    type SectionPlan,
} from '../../types/schemas/creator'
import {DwMembershipLevelReg} from '../../types/dailywire_user_info'
import {CollectionTypeReg, EpisodeIdentifierReg, type CollectionTypeValue, type EpisodeIdentifierValue} from '../../types/collection'
import {useCollectionDefaults} from '../../components/AddCollectionPage/collectionDefaults'
import {newSectionActionReg} from '../../types/creator'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../../components/common/SimpleSelect'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import SegmentedOptions from '../../components/SegmentedOptions/SegmentedOptions'
import CreatorHeader from './CreatorHeader'
import LookupSteps from './LookupSteps'
import './CreatorPages.css'

/** The starting points, in the words of what this creator has: playlists on YouTube, shows on The Daily Wire. */
function presetText(key: CreatorCreateIn['preset'], lists: string, hasFeeds: boolean, creator: CreatorLookupRead, music: boolean) {
    // What the Site calls everything a creator adds there, such as shows on The Daily Wire.
    const skipped = {
        label: 'Only what I pick',
        help: `All ${hasFeeds ? `feeds and ${creator.creatorSections.many}` : creator.creatorSections.many} start skipped.`,
    }
    if (music) {
        if (key === 'one_show') return {label: 'One discography', help: `One Music collection, with ${lists === 'albums' ? 'every album' : `each ${lists.replace(/s$/, '')} as an album`}${hasFeeds ? ' and the other tracks by year' : ''}.`}
        if (key === 'per_list') return {label: 'A collection per album', help: `Each ${lists === 'albums' ? 'album' : lists.replace(/s$/, '')} is a Music collection of its own.`}
        return skipped
    }
    if (key === 'one_show') {
        // A Site offers it only where its sections can be seasons, so not The Daily Wire's shows.
        const many = creator.creatorSections.many
        return {label: 'One collection', help: `${many.charAt(0).toUpperCase()}${many.slice(1)} as named seasons, the rest as seasons based on their year.`}
    }
    if (key === 'per_list') {
        return {
            label: `A collection per ${lists.replace(/s$/, '')}`,
            help: hasFeeds ? `Each of the ${lists} is a collection of its own, plus one for the other videos.` : `Each of the ${lists} is a collection of its own.`,
        }
    }
    return skipped
}

type Choice = 'main' | 'own' | 'skip'

function choiceOf(plan: SectionPlan | undefined): Choice {
    return plan?.target ?? 'skip'
}

/** What happens with a list the creator adds later, to start with: an artist's new playlist is a new album of
 *  theirs, where the Site's lists can be seasons; anyone else is asked. */
function newSectionsFor(creator: CreatorLookupRead, music: boolean): CreatorCreateIn['newSections'] {
    return music && creator.linkSeasons ? 'season' : 'ask'
}

const capitalize = (word: string) => word.charAt(0).toUpperCase() + word.slice(1)

/** What the Site's sections can become, in the words of this creator. */
function choicesFor(creator: CreatorLookupRead, section: CreatorSectionRead, music: boolean) {
    if (isMovie(creator, section)) {
        // A movie in the library joins the creator; another one is added to the library, as one of theirs.
        return createSelectRegistry(`CreatorMovie-${creator.ref}-${section.ref}-${creator.title}-${!!section.movieSlug}`, (
            section.movieSlug
                ? {own: {label: `Joins ${creator.title}`}, skip: {label: 'Stays apart'}}
                : {own: {label: 'Add to your library'}, skip: {label: 'Skip'}}
        ) as Record<Choice, {label: string}>)
    }
    const spec: Partial<Record<Choice, {label: string}>> = {}
    if (section.kind === 'feed') spec.main = {label: 'Main collection'}
    else if (section.kind === 'list' && creator.linkSeasons) spec.main = {label: music ? 'Main collection, as an album' : 'Main collection, as a season'}
    spec.own = {label: 'A collection of its own'}
    spec.skip = {label: 'Skip'}
    return createSelectRegistry(`CreatorSection-${creator.ref}-${section.ref}-${music}`, spec as Record<Choice, {label: string}>)
}

/** A single item that is a movie, which VODLoft adds from this page, unlike a single track. */
function isMovie(creator: CreatorLookupRead, section: CreatorSectionRead) {
    return section.kind === 'item' && creator.movies
}

function sectionFacts(section: CreatorSectionRead): string {
    return [
        section.kindLabel,
        section.year,
        section.itemCount != null
            ? `${section.itemCount} ${section.kindLabel === 'Album' ? (section.itemCount === 1 ? 'track' : 'tracks') : (section.itemCount === 1 ? 'video' : 'videos')}`
            : null,
    ].filter(Boolean).join(' · ')
}

/** What the lookup has done so far, over the shape of the page it is filling in. */
function AddCreatorSkeleton({steps, label}: {steps: string[], label: string}) {
    return (
        <div className="creator-skeleton" aria-busy="true">
            <LookupSteps steps={steps} first={`Looking the ${label} up`}/>
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

type NewCollection = {key: string, title: string, url: string | null}
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
    const suggestion = useCollectionDefaults(item.url ?? undefined)
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
    const [steps, setSteps] = useState<string[]>([])
    const [label, setLabel] = useState('creator')
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
    const into = watch('into') ?? ''
    // A music artist is called an artist everywhere on the page, whatever their site calls its creators.
    const music = watch('type') === 'music'
    const creatorWord = creator && music ? 'artist' : label
    const intoRegistry = useMemo(() => createSelectRegistry(`AddCreatorInto-${(libraryCreators ?? []).length}-${creatorWord}`, {
        '': {label: `A new ${creatorWord} in your library`},
        ...Object.fromEntries((libraryCreators ?? []).map((other) => [
            other.slug, {label: `${other.title} (${other.kind})`, help: 'The same person or group: this account joins them, with their settings.'},
        ])),
    }), [libraryCreators, creatorWord])
    const intoTitle = libraryCreators?.find((other) => other.slug === into)?.title

    useEffect(() => {
        const controller = new AbortController()
        setSteps([])
        lookUpCreator({sourceKey, url, ref}, (step, creatorLabel) => {
            if (creatorLabel) setLabel(creatorLabel)
            setSteps((done) => [...done, step])
        }, controller.signal)
            .then((found) => {
                setCreator(found)
                setLabel(found.creatorLabel)
                setValue('type', found.music ? 'music' : 'series')
                setValue('newSections', newSectionsFor(found, found.music))
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
    const newSections = watch('newSections') ?? 'ask'
    const byRef = useMemo(() => new Map(plans.map((plan) => [plan.ref, plan])), [plans])
    const registries = useMemo(
        () => new Map((creator?.sections ?? []).map((section) => [section.ref, choicesFor(creator!, section, music)])),
        [creator, music],
    )
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
        if (creator) setValue('newSections', newSectionsFor(creator, kind === 'music'))
        choosePreset(preset ?? creator?.presets[0]?.key, kind === 'music')
    }
    const choose = (section: string, choice: Choice) => {
        setValue('sections', plans.map((plan) => plan.ref === section ? {ref: section, target: choice} : plan), {shouldValidate: true})
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
            membershipLevel: data.membershipLevel, newSections: data.newSections, into: data.into || null,
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
                <div className="view-header"><h1 id="add-creator-title">Add {label}</h1></div>
                <div className="form-error-card" role="alert">{error}</div>
                <div className="actions"><button type="button" className="btn" onClick={() => navigate(-1)}>Back</button></div>
            </section>
        )
    }
    if (!creator) {
        return (
            <section className="view creator-view" aria-labelledby="add-creator-title">
                <div className="view-header"><h1 id="add-creator-title">Add {label}</h1></div>
                <AddCreatorSkeleton steps={steps} label={label}/>
            </section>
        )
    }
    if (creator.creatorSlug) {
        return (
            <section className="view" aria-labelledby="add-creator-title">
                <div className="view-header"><h1 id="add-creator-title">Add {label}</h1></div>
                <p>{creator.title} on {creator.siteName} is already in your library.</p>
                <div className="actions">
                    <button type="button" className="btn btn-primary" onClick={() => navigate(`/creator/${creator.creatorSlug}`)}>
                        Open {creator.creatorLabel}
                    </button>
                </div>
            </section>
        )
    }

    const listLabel = creator.sections.find((section) => section.kind === 'list')?.kindLabel
    const hasShows = creator.sections.some((section) => section.kind === 'show')
    const listsTitle = listLabel === 'Album' ? 'Albums' : listLabel ? 'Playlists' : hasShows ? 'Shows' : 'Playlists'
    const lists = listsTitle.toLowerCase()
    const hasFeeds = creator.sections.some((section) => section.kind === 'feed')
    const feeds = new Set(creator.sections.filter((section) => section.kind === 'feed').map((section) => section.ref))
    const keepsFeeds = (plan: SectionPlan[]) => plan.some((item) => feeds.has(item.ref) && item.target !== 'skip')
    // A Daily Wire host has no collection of their own: each show is one.
    const hasMain = [...registries.values()].some((registry) => registry.options.some((option) => option.value === 'main'))
    const groups: [string, CreatorSectionRead[]][] = [
        ['Feeds', creator.sections.filter((section) => section.kind === 'feed')],
        // A creator with shows but no lists, such as a Daily Wire host, has its shows here.
        [listsTitle, creator.sections.filter((section) => section.kind === (listLabel || !hasShows ? 'list' : 'show'))],
        ...(listLabel && hasShows ? [['Shows', creator.sections.filter((section) => section.kind === 'show')]] as [string, CreatorSectionRead[]][] : []),
        [music ? 'Singles' : 'Movies', creator.sections.filter((section) => section.kind === 'item')],
    ]
    // What is in the library already stays where it is, so it makes no collection.
    const inLibrary = new Set(creator.sections.filter((section) => section.collectionSlug).map((section) => section.ref))
    const sectionOf = new Map(creator.sections.map((section) => [section.ref, section]))
    const kept = plans.filter((plan) => plan.target !== 'skip' && !inLibrary.has(plan.ref))
    const keptMovies = kept.filter((plan) => sectionOf.get(plan.ref)?.kind === 'item')
    const newMovies = keptMovies.filter((plan) => !sectionOf.get(plan.ref)?.movieSlug).map((plan) => sectionOf.get(plan.ref)!.title)
    const joiningMovies = keptMovies.filter((plan) => sectionOf.get(plan.ref)?.movieSlug).map((plan) => sectionOf.get(plan.ref)!.movieTitle ?? sectionOf.get(plan.ref)!.title)
    const mainFeed = creator.sections.find((section) => section.kind === 'feed' && section.role === 'main')
    const newCollections: NewCollection[] = [
        ...(kept.some((plan) => plan.target === 'main') ? [{key: MAIN_KEY, title: intoTitle ?? creator.title, url: mainFeed?.url ?? creator.url}] : []),
        ...kept.filter((plan) => plan.target === 'own' && sectionOf.get(plan.ref)?.kind !== 'item').map((plan) => {
            const section = sectionOf.get(plan.ref)
            return {
                key: plan.ref,
                title: section?.kind === 'feed' ? `${creator.title} ${section.title}` : section?.title ?? plan.ref,
                url: section?.url ?? null,
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
        ? `${capitalize(summaryParts.length > 1 ? `${summaryParts.slice(0, -1).join(', ')} and ${summaryParts[summaryParts.length - 1]}` : summaryParts[0])}: ${
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
                        {' '}A {music ? 'track' : 'video'} that is in several places is kept once.
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
                                    label: capitalize(creator.creatorLabel),
                                    description: `Videos and ${lists} in Series collections, with ${lists} as seasons`,
                                },
                                {
                                    value: 'music',
                                    label: 'Music artist',
                                    description: `Music collections, with ${lists} as albums and their videos as tracks or music videos`,
                                },
                            ]}
                        />
                        <div className="help">
                            {creator.music && creator.musicReason
                                ? `${creator.musicReason}, so VODLoft took it for a music artist. Pick ${capitalize(creator.creatorLabel)} if it isn't.`
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
                                <b>{presetText(item.key, lists, music ? keepsFeeds(item.musicPlan) : hasFeeds, creator, music).label}</b>
                                <span>{presetText(item.key, lists, music ? keepsFeeds(item.musicPlan) : hasFeeds, creator, music).help}</span>
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
                                                    : sectionFacts(section)}
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
                                                onChange={(value) => choose(section.ref, value as Choice)}
                                            />
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}


                {!into && <div className="form-row creator-membership">
                    <label htmlFor="creator-new-sections">When the {creatorWord} adds {/^[aeiou]/.test(lists) ? 'an' : 'a'} {lists.replace(/s$/, '')}</label>
                    <SimpleSelect
                        inputId="creator-new-sections" registry={newSectionActionReg(creatorWord, [{name: creator.siteName, linkSeasons: creator.linkSeasons, creatorSections: creator.creatorSections}], music)} value={newSections}
                        onChange={(value) => setValue('newSections', value as CreatorCreateIn['newSections'])}
                    />
                    <div className="help">{newSectionActionReg(creatorWord, [{name: creator.siteName, linkSeasons: creator.linkSeasons, creatorSections: creator.creatorSections}], music).meta(newSections as never)?.help} VODLoft looks for new ones once a day.</div>
                </div>}

                {sourceKey === 'dailywire' && (
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
