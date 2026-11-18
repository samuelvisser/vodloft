import {useEffect, useMemo, useState} from 'react'
import {useNavigate, useSearchParams} from 'react-router-dom'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {apiUrl} from '../../lib/api'
import {lookUpChannel} from '../../lib/queries'
import {
    ChannelCreateSchema, type ChannelCreateIn, type ChannelCreateOut, type ChannelLookupRead, type ChannelSectionRead,
    type SectionPlan,
} from '../../types/schemas/channel'
import {DwMembershipLevelReg} from '../../types/dailywire_user_info'
import {newSectionActionReg} from '../../types/channel'
import {getZodDefaults} from '../../utils/defaultZod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../../components/common/SimpleSelect'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import ChannelHeader from './ChannelHeader'
import './ChannelPages.css'

/** The starting points, in the words of what this channel has: playlists on YouTube, shows on The Daily Wire. */
function presetText(key: ChannelCreateIn['preset'], lists: string, hasFeeds: boolean) {
    if (key === 'one_show') return {label: 'One show', help: `Videos and livestreams by year, ${lists} as named seasons, Shorts apart.`}
    if (key === 'per_list') {
        return {
            label: `A collection per ${lists.replace(/s$/, '')}`,
            help: hasFeeds ? `Each of the ${lists} is a collection of its own, plus one for the other videos.` : `Each of the ${lists} is a collection of its own.`,
        }
    }
    return {label: 'Only what I pick', help: 'Everything starts skipped.'}
}

/** The order in which places claim a video, as the user sees them. */
function orderText(sections: ChannelSectionRead[], lists: string) {
    const feeds = ['live', 'short', 'main']
        .map((role) => sections.find((section) => section.kind === 'feed' && section.role === role)?.title)
        .filter((title): title is string => !!title)
    if (!feeds.length) return null
    const names = [lists, ...feeds]
    return `${names.slice(0, -1).join(', ')} and then ${names[names.length - 1]}`
}

type Choice = 'main:site_seasons' | 'main:one_season' | 'main:specials' | 'own' | 'skip'

function choiceOf(plan: ChannelCreateIn['sections'] extends (infer P)[] | undefined ? P | undefined : never): Choice {
    if (!plan || plan.target === 'skip') return 'skip'
    if (plan.target === 'own') return 'own'
    return `main:${plan.placement ?? 'site_seasons'}` as Choice
}

function planOf(ref: string, choice: Choice): SectionPlan {
    if (choice === 'skip' || choice === 'own') return {ref, target: choice, placement: 'site_seasons'}
    const [, placement] = choice.split(':') as ['main', SectionPlan['placement']]
    return {ref, target: 'main', placement}
}

/** What the Site's sections can become, in the words of this channel. */
function choicesFor(channel: ChannelLookupRead, section: ChannelSectionRead) {
    const spec: Partial<Record<Choice, {label: string}>> = {}
    if (section.kind === 'feed') spec['main:site_seasons'] = {label: 'Main collection, a season per year'}
    else if (section.hasSeasons) spec['main:site_seasons'] = {label: 'Main collection, with its own seasons'}
    if (section.kind !== 'feed') spec['main:one_season'] = {label: 'Main collection, as one season'}
    spec['main:specials'] = {label: 'Main collection, as specials'}
    spec.own = {label: 'A collection of its own'}
    spec.skip = {label: 'Skip'}
    return createSelectRegistry(`ChannelSection-${channel.ref}-${section.ref}`, spec as Record<Choice, {label: string}>)
}

function sectionFacts(section: ChannelSectionRead): string {
    return [
        section.kindLabel,
        section.itemCount != null ? `${section.itemCount} ${section.itemCount === 1 ? 'video' : 'videos'}` : null,
    ].filter(Boolean).join(' · ')
}

/** What the lookup has done so far, over the shape of the page it is filling in. */
function AddChannelSkeleton({steps, label}: {steps: string[], label: string}) {
    return (
        <div className="channel-skeleton" aria-busy="true">
            <ol className="channel-lookup-steps" aria-live="polite">
                {(steps.length ? steps : [`Looking the ${label} up`]).map((step, index, all) => {
                    const current = index === all.length - 1
                    return (
                        <li key={step} className={current ? 'is-current' : 'is-done'}>
                            <FontAwesomeIcon icon={current ? faIcon('fass', 'spinner') : faIcon('fass', 'check')} spin={current} fixedWidth/>
                            <span>{step}{current ? '…' : ''}</span>
                        </li>
                    )
                })}
            </ol>
            <div className="channel-header" aria-hidden="true">
                <div className="channel-banner skeleton-block"/>
                <div className="channel-identity">
                    <span className="channel-avatar skeleton-block"/>
                    <div className="channel-identity-copy channel-skeleton-copy">
                        <span className="skeleton-block channel-skeleton-line channel-skeleton-line--kind"/>
                        <span className="skeleton-block channel-skeleton-line channel-skeleton-line--title"/>
                        <span className="skeleton-block channel-skeleton-line"/>
                        <span className="skeleton-block channel-skeleton-line channel-skeleton-line--short"/>
                    </div>
                </div>
            </div>
            <div className="channel-presets" aria-hidden="true">
                {[0, 1, 2].map((key) => <div key={key} className="skeleton-block channel-skeleton-preset"/>)}
            </div>
            <div className="channel-section-group" aria-hidden="true">
                <span className="skeleton-block channel-skeleton-line channel-skeleton-line--heading"/>
                <div className="channel-section-list">
                    {[0, 1, 2, 3].map((key) => (
                        <div key={key} className="channel-section-row">
                            <span className="channel-section-art skeleton-block"/>
                            <div className="channel-section-copy channel-skeleton-copy">
                                <span className="skeleton-block channel-skeleton-line channel-skeleton-line--title-small"/>
                                <span className="skeleton-block channel-skeleton-line channel-skeleton-line--short"/>
                            </div>
                            <span className="channel-section-choice skeleton-block channel-skeleton-choice"/>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

export default function AddChannelPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [params] = useSearchParams()
    const sourceKey = params.get('source') ?? ''
    const url = params.get('url')
    const ref = params.get('ref')
    const [channel, setChannel] = useState<ChannelLookupRead | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [steps, setSteps] = useState<string[]>([])
    const [label, setLabel] = useState('channel')

    const form = useForm<ChannelCreateIn, unknown, ChannelCreateOut>({
        resolver: zodResolver(ChannelCreateSchema),
        defaultValues: {...getZodDefaults(ChannelCreateSchema), sourceKey, url, ref},
    })
    const {watch, setValue, formState: {errors, isSubmitting}} = form

    useEffect(() => {
        const controller = new AbortController()
        setSteps([])
        lookUpChannel({sourceKey, url, ref}, (step, channelLabel) => {
            if (channelLabel) setLabel(channelLabel)
            setSteps((done) => [...done, step])
        }, controller.signal)
            .then((found) => {
                setChannel(found)
                setLabel(found.channelLabel)
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
        () => new Map((channel?.sections ?? []).map((section) => [section.ref, choicesFor(channel!, section)])),
        [channel],
    )

    const choosePreset = (key: ChannelCreateIn['preset']) => {
        const chosen = channel?.presets.find((item) => item.key === key)
        if (!chosen || !key) return
        setValue('preset', key)
        setValue('sections', chosen.plan, {shouldValidate: true})
    }
    const choose = (section: string, choice: Choice) => {
        setValue('sections', plans.map((plan) => plan.ref === section ? planOf(section, choice) : plan), {shouldValidate: true})
    }

    const onSubmit = buildServerAwareSubmit<ChannelCreateIn, ChannelCreateOut>(form, (data) => fetch(`${apiUrl()}/channels`, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            sourceKey: data.sourceKey, url: data.url, ref: data.ref, sections: data.sections,
            membershipLevel: data.membershipLevel, newSections: data.newSections,
        }),
    }), {
        fallbackField: 'sections',
        onSuccess: async (created: any) => {
            await queryClient.invalidateQueries({queryKey: ['channels']})
            await queryClient.invalidateQueries({queryKey: ['collections']})
            await queryClient.invalidateQueries({queryKey: ['collectionsView']})
            navigate(`/channel/${created.slug}`, {replace: true})
        },
    })

    if (error) {
        return (
            <section className="view" aria-labelledby="add-channel-title">
                <div className="view-header"><h1 id="add-channel-title">Add {label}</h1></div>
                <div className="form-error-card" role="alert">{error}</div>
                <div className="actions"><button type="button" className="btn" onClick={() => navigate(-1)}>Back</button></div>
            </section>
        )
    }
    if (!channel) {
        return (
            <section className="view channel-view" aria-labelledby="add-channel-title">
                <div className="view-header"><h1 id="add-channel-title">Add {label}</h1></div>
                <AddChannelSkeleton steps={steps} label={label}/>
            </section>
        )
    }
    if (channel.channelSlug) {
        return (
            <section className="view" aria-labelledby="add-channel-title">
                <div className="view-header"><h1 id="add-channel-title">Add {label}</h1></div>
                <p>{channel.title} is already in your library.</p>
                <div className="actions">
                    <button type="button" className="btn btn-primary" onClick={() => navigate(`/channel/${channel.channelSlug}`)}>
                        Open {channel.channelLabel}
                    </button>
                </div>
            </section>
        )
    }

    const listsTitle = channel.sections.find((section) => section.kind === 'list')?.kindLabel === 'Show' ? 'Shows' : 'Playlists'
    const lists = listsTitle.toLowerCase()
    const hasFeeds = channel.sections.some((section) => section.kind === 'feed')
    const order = orderText(channel.sections, lists)
    const groups: [string, ChannelSectionRead[]][] = [
        ['Feeds', channel.sections.filter((section) => section.kind === 'feed')],
        [listsTitle, channel.sections.filter((section) => section.kind === 'list')],
        ['Movies', channel.sections.filter((section) => section.kind === 'item')],
    ]
    // What is in the library already stays where it is, so it makes no collection.
    const inLibrary = new Set(channel.sections.filter((section) => section.collectionSlug).map((section) => section.ref))
    const kept = plans.filter((plan) => plan.target !== 'skip' && !inLibrary.has(plan.ref))
    const collectionTitles = [
        ...(kept.some((plan) => plan.target === 'main') ? [channel.title] : []),
        ...kept.filter((plan) => plan.target === 'own').map((plan) => {
            const section = channel.sections.find((item) => item.ref === plan.ref)
            return section?.kind === 'feed' ? `${channel.title} ${section.title}` : section?.title ?? plan.ref
        }),
    ]

    return (
        <section className="view channel-view" aria-labelledby="add-channel-title">
            <div className="view-header">
                <div>
                    <h1 id="add-channel-title">Add {channel.channelLabel}</h1>
                    <p className="view-description">
                        Choose where each part of this {channel.channelLabel} goes. The main collection is called
                        {' '}{channel.title}; anything you give a collection of its own gets one. A video that is in several
                        places is kept once.
                    </p>
                </div>
            </div>

            <ChannelHeader
                title={channel.title} label={`${channel.siteName} ${channel.channelLabel}`} handle={channel.handle}
                avatarUrl={channel.avatarUrl} bannerUrl={channel.bannerUrl} facts={channel.facts} description={channel.description}
            />

            <form className="form form-fluid channel-setup" onSubmit={onSubmit} noValidate>
                {channel.presets.length > 1 && (
                    <fieldset className="channel-presets">
                        <legend>What to keep from this {channel.channelLabel}</legend>
                        {channel.presets.map((item) => (
                            <label key={item.key} className={`channel-preset${preset === item.key ? ' is-on' : ''}`}>
                                <input type="radio" name="preset" checked={preset === item.key} onChange={() => choosePreset(item.key)}/>
                                <b>{presetText(item.key, lists, hasFeeds).label}</b>
                                <span>{presetText(item.key, lists, hasFeeds).help}</span>
                            </label>
                        ))}
                    </fieldset>
                )}

                {groups.filter(([, sections]) => sections.length).map(([title, sections]) => (
                    <div key={title} className="channel-section-group">
                        <h2>{title}</h2>
                        <div className="channel-section-list">
                            {sections.map((section) => (
                                <div key={section.ref} className="channel-section-row">
                                    {section.imageUrl
                                        ? <img className="channel-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
                                        : <span className="channel-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : 'list')}/></span>}
                                    <div className="channel-section-copy">
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
                                        <span className="channel-section-note">Add it from its own page</span>
                                    ) : section.collectionSlug ? (
                                        <span className="channel-section-note">Stays where it is</span>
                                    ) : (
                                        <div className="channel-section-choice">
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

                {order && (
                    <p className="channel-order-note">
                        A video in more than one of these places goes to the first one in this order: {order}.
                        Once a video has a file, it stays where it is.
                    </p>
                )}

                <div className="form-row channel-membership">
                    <label htmlFor="channel-new-sections">When the {channel.channelLabel} adds a {lists.replace(/s$/, '')}</label>
                    <SimpleSelect
                        inputId="channel-new-sections" registry={newSectionActionReg(channel.channelLabel)} value={newSections}
                        onChange={(value) => setValue('newSections', value as ChannelCreateIn['newSections'])}
                    />
                    <div className="help">{newSectionActionReg(channel.channelLabel).meta(newSections as never)?.help} VODLoft looks for new ones once a day.</div>
                </div>

                {sourceKey === 'dailywire' && (
                    <div className="form-row channel-membership">
                        <label htmlFor="channel-membership">Membership level</label>
                        <SimpleSelect
                            inputId="channel-membership" registry={DwMembershipLevelReg} value={membershipLevel}
                            onChange={(value) => setValue('membershipLevel', value as ChannelCreateIn['membershipLevel'])}
                        />
                        <div className="help">{DwMembershipLevelReg.meta(membershipLevel as never)?.help}</div>
                        {errors.membershipLevel && <div className="error" role="alert">{errors.membershipLevel.message}</div>}
                    </div>
                )}

                {errors.sections && <div className="form-error-card" role="alert">{errors.sections.message ?? errors.sections.root?.message}</div>}

                <div className="actions">
                    <span className="channel-summary">
                        {collectionTitles.length
                            ? `Creates ${collectionTitles.length} ${collectionTitles.length === 1 ? 'collection' : 'collections'}: ${collectionTitles.length > 4 ? `${collectionTitles.slice(0, 3).join(', ')} and ${collectionTitles.length - 3} more` : collectionTitles.join(', ')}`
                            : 'Nothing picked yet'}
                    </span>
                    <button type="button" className="btn" onClick={() => navigate(-1)}>Cancel</button>
                    <button type="submit" className="btn btn-primary" disabled={isSubmitting || !collectionTitles.length}>
                        {isSubmitting ? 'Adding…' : `Add ${channel.channelLabel}`}
                    </button>
                </div>
            </form>
        </section>
    )
}
