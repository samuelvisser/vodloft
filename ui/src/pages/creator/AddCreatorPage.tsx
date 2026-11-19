import {useEffect, useMemo, useState} from 'react'
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
import {newSectionActionReg} from '../../types/creator'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../../components/common/SimpleSelect'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import CreatorHeader from './CreatorHeader'
import LookupSteps from './LookupSteps'
import './CreatorPages.css'

/** The starting points, in the words of what this creator has: playlists on YouTube, shows on The Daily Wire. */
function presetText(key: CreatorCreateIn['preset'], lists: string, hasFeeds: boolean, music: boolean) {
    if (music) {
        if (key === 'one_show') return {label: 'One discography', help: `One Music collection, with each album as a season${hasFeeds ? ' and the other tracks by year' : ''}.`}
        if (key === 'per_list') return {label: 'A collection per album', help: 'Each album is a Music collection of its own.'}
        return {label: 'Only what I pick', help: 'Everything starts skipped.'}
    }
    if (key === 'one_show') return {label: 'One show', help: `Videos and livestreams by year, ${lists} as named seasons, Shorts apart.`}
    if (key === 'per_list') {
        return {
            label: `A collection per ${lists.replace(/s$/, '')}`,
            help: hasFeeds ? `Each of the ${lists} is a collection of its own, plus one for the other videos.` : `Each of the ${lists} is a collection of its own.`,
        }
    }
    return {label: 'Only what I pick', help: 'Everything starts skipped.'}
}

type Choice = 'main' | 'own' | 'skip'

function choiceOf(plan: SectionPlan | undefined): Choice {
    return plan?.target ?? 'skip'
}

/** What the Site's sections can become, in the words of this creator. */
function choicesFor(creator: CreatorLookupRead, section: CreatorSectionRead) {
    const spec: Partial<Record<Choice, {label: string}>> = {}
    if (section.kind === 'feed') spec.main = {label: 'Main collection'}
    else if (section.kind === 'list' && creator.linkSeasons) spec.main = {label: `Main collection, as ${creator.music ? 'an album' : 'a playlist'} season`}
    spec.own = {label: 'A collection of its own'}
    spec.skip = {label: 'Skip'}
    return createSelectRegistry(`CreatorSection-${creator.ref}-${section.ref}`, spec as Record<Choice, {label: string}>)
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
                <div className="creator-identity">
                    <span className="creator-avatar skeleton-block"/>
                    <div className="creator-identity-copy creator-skeleton-copy">
                        <span className="skeleton-block creator-skeleton-line creator-skeleton-line--kind"/>
                        <span className="skeleton-block creator-skeleton-line creator-skeleton-line--title"/>
                        <span className="skeleton-block creator-skeleton-line"/>
                        <span className="skeleton-block creator-skeleton-line creator-skeleton-line--short"/>
                    </div>
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

    const form = useForm<CreatorCreateIn, unknown, CreatorCreateOut>({
        resolver: zodResolver(CreatorCreateSchema),
        defaultValues: {...getZodDefaults(CreatorCreateSchema), sourceKey, url, ref},
    })
    const {watch, setValue, formState: {errors, isSubmitting}} = form
    const {data: libraryCreators} = useCreators()
    const into = watch('into') ?? ''
    const intoRegistry = useMemo(() => createSelectRegistry(`AddCreatorInto-${(libraryCreators ?? []).length}`, {
        '': {label: `A new ${label} in your library`},
        ...Object.fromEntries((libraryCreators ?? []).map((other) => [
            other.slug, {label: `${other.title} (${other.kind})`, help: 'The same person or group: this account joins them, with their settings.'},
        ])),
    }), [libraryCreators, label])
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
                const preset = found.presets[0]
                if (preset) {
                    setValue('preset', preset.key)
                    setValue('sections', preset.plan)
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
        () => new Map((creator?.sections ?? []).map((section) => [section.ref, choicesFor(creator!, section)])),
        [creator],
    )

    const choosePreset = (key: CreatorCreateIn['preset']) => {
        const chosen = creator?.presets.find((item) => item.key === key)
        if (!chosen || !key) return
        setValue('preset', key)
        setValue('sections', chosen.plan, {shouldValidate: true})
    }
    const choose = (section: string, choice: Choice) => {
        setValue('sections', plans.map((plan) => plan.ref === section ? {ref: section, target: choice} : plan), {shouldValidate: true})
    }

    const onSubmit = buildServerAwareSubmit<CreatorCreateIn, CreatorCreateOut>(form, (data) => fetch(`${apiUrl()}/creators`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            sourceKey: data.sourceKey, url: data.url, ref: data.ref, lookupId: creator?.lookupId ?? null, sections: data.sections,
            membershipLevel: data.membershipLevel, newSections: data.newSections, into: data.into || null,
        }),
    }), {
        fallbackField: 'sections',
        onSuccess: (created: any) => {
            // The creator's page loads on its own, so the lists it changed refresh behind it.
            void queryClient.invalidateQueries({queryKey: ['creators']})
            void queryClient.invalidateQueries({queryKey: ['collections']})
            void queryClient.invalidateQueries({queryKey: ['collectionsView']})
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
    const groups: [string, CreatorSectionRead[]][] = [
        ['Feeds', creator.sections.filter((section) => section.kind === 'feed')],
        [listsTitle, creator.sections.filter((section) => section.kind === 'list')],
        ...(listLabel && hasShows ? [['Shows', creator.sections.filter((section) => section.kind === 'show')]] as [string, CreatorSectionRead[]][] : []),
        [creator.music ? 'Singles' : 'Movies', creator.sections.filter((section) => section.kind === 'item')],
    ]
    // What is in the library already stays where it is, so it makes no collection.
    const inLibrary = new Set(creator.sections.filter((section) => section.collectionSlug).map((section) => section.ref))
    const kept = plans.filter((plan) => plan.target !== 'skip' && !inLibrary.has(plan.ref))
    const collectionTitles = [
        ...(kept.some((plan) => plan.target === 'main') ? [intoTitle ?? creator.title] : []),
        ...kept.filter((plan) => plan.target === 'own').map((plan) => {
            const section = creator.sections.find((item) => item.ref === plan.ref)
            return section?.kind === 'feed' ? `${creator.title} ${section.title}` : section?.title ?? plan.ref
        }),
    ]

    return (
        <section className="view creator-view" aria-labelledby="add-creator-title">
            <div className="view-header">
                <div>
                    <h1 id="add-creator-title">Add {creator.creatorLabel}</h1>
                    <p className="view-description">
                        Choose where each part of this {creator.creatorLabel} goes. The main collection is called
                        {' '}{creator.title}; anything you give a collection of its own gets one. A {creator.music ? 'track' : 'video'} that is in several
                        places is kept once.
                    </p>
                </div>
            </div>

            <CreatorHeader
                title={creator.title} label={`${creator.siteName} ${creator.creatorLabel}`} handle={creator.handle}
                avatarUrl={creator.avatarUrl} bannerUrl={creator.bannerUrl} facts={creator.facts} description={creator.description}
            />

            <form className="form form-fluid creator-setup" onSubmit={onSubmit} noValidate>
                {creator.presets.length > 1 && (
                    <fieldset className="creator-presets">
                        <legend>What to keep from this {creator.creatorLabel}</legend>
                        {creator.presets.map((item) => (
                            <label key={item.key} className={`creator-preset${preset === item.key ? ' is-on' : ''}`}>
                                <input type="radio" name="preset" checked={preset === item.key} onChange={() => choosePreset(item.key)}/>
                                <b>{presetText(item.key, lists, hasFeeds, creator.music).label}</b>
                                <span>{presetText(item.key, lists, hasFeeds, creator.music).help}</span>
                            </label>
                        ))}
                    </fieldset>
                )}

                {(libraryCreators?.length ?? 0) > 0 && (
                    <div className="form-row creator-membership">
                        <label htmlFor="creator-into">Add it as</label>
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
                                        : <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : 'list')}/></span>}
                                    <div className="creator-section-copy">
                                        <b>{section.title}</b>
                                        <span>
                                            {section.collectionSlug
                                                ? `Already in your library as ${section.collectionTitle ?? section.collectionSlug}`
                                                : section.access
                                                    ? 'Only some members can watch this. Pick it if VODLoft signs in as one.'
                                                    : sectionFacts(section)}
                                        </span>
                                    </div>
                                    {section.kind === 'item' ? (
                                        <span className="creator-section-note">Add it from its own page</span>
                                    ) : section.collectionSlug ? (
                                        <span className="creator-section-note">Stays where it is</span>
                                    ) : (
                                        <div className="creator-section-choice">
                                            <SimpleSelect
                                                aria-label={`Where ${section.title} goes`}
                                                registry={registries.get(section.ref)!}
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
                    <label htmlFor="creator-new-sections">When the {creator.creatorLabel} adds {/^[aeiou]/.test(lists) ? 'an' : 'a'} {lists.replace(/s$/, '')}</label>
                    <SimpleSelect
                        inputId="creator-new-sections" registry={newSectionActionReg(creator.creatorLabel)} value={newSections}
                        onChange={(value) => setValue('newSections', value as CreatorCreateIn['newSections'])}
                    />
                    <div className="help">{newSectionActionReg(creator.creatorLabel).meta(newSections as never)?.help} VODLoft looks for new ones once a day.</div>
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

                {errors.sections && <div className="form-error-card" role="alert">{errors.sections.message ?? errors.sections.root?.message}</div>}

                <div className="actions">
                    <span className="creator-summary">
                        {collectionTitles.length
                            ? `Creates ${collectionTitles.length} ${collectionTitles.length === 1 ? 'collection' : 'collections'}: ${collectionTitles.length > 4 ? `${collectionTitles.slice(0, 3).join(', ')} and ${collectionTitles.length - 3} more` : collectionTitles.join(', ')}`
                            : 'Nothing picked yet'}
                    </span>
                    <button type="button" className="btn" onClick={() => navigate(-1)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !collectionTitles.length}>
                        {isSubmitting ? 'Adding…' : into ? `Add to ${intoTitle}` : `Add ${creator.creatorLabel}`}
                    </button>
                </div>
            </form>
        </section>
    )
}
