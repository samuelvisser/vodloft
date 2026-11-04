import {Fragment, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode} from 'react'
import {useFieldArray, useWatch, type UseFormReturn} from 'react-hook-form'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Select from 'react-select'

import {faIcon} from '../../icons/faIcon'
import ReadMore from '../../utils/ReadMore'
import TimeInterval from '../../utils/TimeInterval'
import SimpleSelect from '../common/SimpleSelect'
import RegexEditor from '../RegexEditor/RegexEditor'
import {EpisodeIdentifierReg} from '../../types/collection'
import {
    DurationOperatorReg,
    EpisodeRuleActionReg,
    EpisodeRuleFieldReg,
    downloadProfileDefaultsFor,
    newEpisodeRule,
    type EpisodeRule,
} from '../../types/schemas/download_profile'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {EpisodeTagRead} from '../../types/schemas/source'
import type {SeasonItem} from './DownloadProfileSeasonFilter'
import {useWhichEpisodes} from './useWhichEpisodes'
import {dateSentence, plainText, ruleComplete, ruleSentence, seasonsSentence, typesSentence, type Part} from './whichEpisodesText'
import './WhichEpisodes.css'

type Props = {
    form: UseFormReturn<any>
    episodeIdentifier?: string
    tags?: readonly EpisodeTagRead[]
    seasons: SeasonItem[]
    /** The saved Collection; counts need its indexed episodes. */
    collectionId?: number
    /** Creating a profile opens the built-in lines, so they aren't hidden the first time. */
    startOpen?: boolean
    typesField: ReactNode
    seasonsField: ReactNode
    datesField: ReactNode
}

const BUILT_IN_FIELDS: Record<string, string[]> = {
    types: ['epIdTypeList'],
    seasons: ['seasons', 'includeUpcomingSeasons', 'allSeasons'],
    dates: [
        'downloadDaysInPast', 'downloadEpisodeCount',
        'downloadStartingFrom', 'deleteOlderEpisodes', 'retentionFrom',
    ],
}

// What a line looks at. Episode types, the season and the two dates are also built-in lines, while those lines aren't there.
const FILTER_KINDS = {
    title: {label: 'title'},
    description: {label: 'description'},
    duration: {label: 'duration'},
    types: {label: 'episode type'},
    season: {label: 'season'},
    published: {label: 'published'},
    downloaded: {label: 'downloaded'},
}
type FilterKind = keyof typeof FILTER_KINDS
const DATE_KINDS: readonly FilterKind[] = ['published', 'downloaded']

/** A new rule of a kind, with the defaults its editor starts from. */
function ruleOf(kind: EpisodeRule['field'], action: EpisodeRule['action']): EpisodeRule {
    const rule = {...newEpisodeRule(), action, field: kind}
    if (kind === 'duration') return {...rule, durationOperator: 'shorter', durationSeconds: 120}
    if (kind === 'types') return {...rule, episodeTypes: []}
    return rule
}
/** Without a seasons line, every season downloads, upcoming ones included. */
const SEASONS_RESET = {seasons: [], includeUpcomingSeasons: true, allSeasons: true}
const DATE_RESET = {downloadDaysInPast: 0, downloadEpisodeCount: 0, downloadStartingFrom: null, deleteOlderEpisodes: false, retentionFrom: 'published'}

const LEFT_OUT_LABELS: Record<string, string> = {
    unavailable: 'Can’t be downloaded',
    types: 'Episode types',
    seasons: 'Seasons',
    dates: 'Date window',
}

function Sentence({parts}: {parts: Part[]}) {
    return (
        <>
            {parts.map((part, index) => part.code
                ? <code key={index} className="which-episodes-code">{part.text}</code>
                : part.strong ? <b key={index}>{part.text}</b> : <Fragment key={index}>{part.text}</Fragment>)}
        </>
    )
}

/** Without an episode types line above it, the date line starts the sentence itself. */
function withLead(lead: boolean, parts: Part[]): Part[] {
    return lead ? [{text: 'Download episodes '}, ...parts] : parts
}

/** Clicking a line's sentence opens or closes it, unless the click was on one of its controls. */
function toggleFromSentence(event: MouseEvent<HTMLDivElement>, toggle: () => void) {
    if ((event.target as HTMLElement).closest('button, a, input, select, textarea, [class*="select__"]')) return
    toggle()
}

function CountBadge({count, label}: {count: number | undefined; label?: string}) {
    if (count === undefined) return null
    return (
        <span className={`which-episodes-count${count === 0 ? ' is-zero' : ''}`} title="Indexed episodes this line leaves out">
            −{count}{label ? ` ${label}` : ''}
        </span>
    )
}

/** One section of sentences that decides which episodes a Download Profile downloads. */
export default function WhichEpisodes({
    form, episodeIdentifier, tags, seasons, collectionId, startOpen = false, typesField, seasonsField, datesField,
}: Props) {
    const {control, getValues, setValue, trigger} = form
    const {fields, append, remove} = useFieldArray({control, name: 'rules'})
    const seasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal
    const builtIns = ['types', ...(seasonal && !getValues('allSeasons') ? ['seasons'] : []), ...(episodeIdentifier !== undefined ? ['dates'] : [])]
    const datesAllowed = episodeIdentifier !== undefined
    // While creating, every built-in line stays open until you open or close one yourself.
    const [chosenOpen, setOpen] = useState<Set<string> | null>(startOpen ? null : new Set())
    const open = chosenOpen ?? new Set(builtIns)
    const [showWhich, setShowWhich] = useState(false)
    // Values when a line was opened, so Cancel can put them back; a new rule has none and is removed instead.
    const snapshots = useRef(new Map<string, unknown>())

    const values = useWatch({control}) as Record<string, any>
    const rules: EpisodeRule[] = values.rules ?? []

    const request = useMemo(() => {
        if (collectionId === undefined) return null
        return {
            collectionId,
            epIdTypeList: values.epIdTypeList ?? [],
            downloadWithCountdown: !!values.downloadWithCountdown,
            downloadDaysInPast: Number.isFinite(values.downloadDaysInPast) ? values.downloadDaysInPast : 0,
            downloadEpisodeCount: Number.isFinite(values.downloadEpisodeCount) ? values.downloadEpisodeCount : 0,
            downloadStartingFrom: values.downloadStartingFrom ?? null,
            seasonSlugs: (values.seasons ?? []).map((season: SeasonItem) => season.slug),
            includeUpcomingSeasons: !!values.includeUpcomingSeasons,
            allSeasons: !!values.allSeasons,
            // Lines still being written are left out of the count until they are complete.
            rules: rules.filter(ruleComplete),
            includeEpisodes: showWhich,
        }
    }, [collectionId, values, rules, showWhich])
    const {result, episodes, hasMore, loadingMore, moreFailed, loadMore} = useWhichEpisodes(request)
    // The list loads its next page when its end scrolls into view.
    const listRef = useRef<HTMLUListElement | null>(null)
    const endRef = useRef<HTMLLIElement | null>(null)
    useEffect(() => {
        const node = endRef.current
        if (!node || !hasMore || loadingMore || moreFailed) return
        const observer = new IntersectionObserver(
            (entries) => { if (entries[0]?.isIntersecting) loadMore() },
            {root: listRef.current, rootMargin: '200px'},
        )
        observer.observe(node)
        return () => observer.disconnect()
    }, [hasMore, loadingMore, moreFailed, loadMore])
    // Counts of the rules sent, mapped back to every rule line (unfinished lines have none).
    const ruleCounts = useMemo(() => {
        const counts: Array<number | undefined> = []
        let sent = 0
        for (const rule of rules) {
            const complete = ruleComplete(rule)
            counts.push(complete && result ? result.rules[sent] : undefined)
            if (complete) sent += 1
        }
        return counts
    }, [rules, result])
    const sentRuleIndexes = useMemo(() => rules.flatMap((rule, index) => ruleComplete(rule) ? [index] : []), [rules])

    const openLine = (key: string, fieldNames: string[]) => {
        snapshots.current.set(key, fieldNames.map((name) => getValues(name)))
        setOpen(new Set([key]))
    }
    const closeLine = (key: string) => {
        snapshots.current.delete(key)
        setOpen((current) => {
            const next = new Set(current ?? builtIns)
            next.delete(key)
            return next
        })
    }
    const cancelLine = (key: string, fieldNames: string[], ruleIndex?: number) => {
        const snapshot = snapshots.current.get(key) as unknown[] | (() => void) | undefined
        if (typeof snapshot === 'function') {
            // A built-in line that became this new rule: Cancel removes the rule and brings the line back.
            if (ruleIndex !== undefined) remove(ruleIndex)
            closeLine(key)
            snapshot()
            return
        }
        if (snapshot) {
            fieldNames.forEach((name, index) => setValue(name, snapshot[index], {shouldDirty: true, shouldValidate: true}))
        } else if (ruleIndex !== undefined) {
            remove(ruleIndex)
        }
        closeLine(key)
    }
    const doneLine = async (key: string, fieldNames: string[]) => {
        if (await trigger(fieldNames)) closeLine(key)
    }

    // Episode types, the seasons and the date window are filters you can remove and add again; while open they stay.
    const typesShown = (values.epIdTypeList ?? []).length > 0 || open.has('types')
    const seasonsShown = seasonal && (!values.allSeasons || open.has('seasons'))
    const hasDateLimit = (values.downloadDaysInPast ?? 0) > 0 || (values.downloadEpisodeCount ?? 0) > 0
        || !!values.downloadStartingFrom || values.retentionFrom === 'downloaded'
    const datesShown = datesAllowed && (hasDateLimit || open.has('dates'))
    /** What a line can look at: every rule kind, the season while there is no seasons line, and the dates while there is no date line or this is it. */
    const kindRegFor = (current: FilterKind) => createSelectRegistry('WhichEpisodesFilterKind', FILTER_KINDS, [
        ...EpisodeRuleFieldReg.values,
        ...(seasonal && !seasonsShown ? ['season' as const] : []),
        ...(datesAllowed && (!datesShown || DATE_KINDS.includes(current)) ? DATE_KINDS : []),
    ])
    const setDateField = (kind: string) => {
        const days = Number.isFinite(values.downloadDaysInPast) ? values.downloadDaysInPast : 0
        setValue('retentionFrom', kind, {shouldDirty: true, shouldValidate: true})
        if (kind === 'downloaded') {
            // Counting from the download date only works with a number of days.
            setValue('downloadEpisodeCount', 0, {shouldDirty: true, shouldValidate: true})
            setValue('downloadStartingFrom', null, {shouldDirty: true, shouldValidate: true})
            setValue('downloadDaysInPast', days > 0 ? days : 180, {shouldDirty: true, shouldValidate: true})
            setValue('deleteOlderEpisodes', true, {shouldDirty: true, shouldValidate: true})
        }
    }
    /** A built-in line becomes a new rule; Cancel on that rule brings the line back as it was. */
    const builtInToRule = (key: 'types' | 'dates', rule: EpisodeRule) => {
        const names = BUILT_IN_FIELDS[key]
        const saved = names.map((name) => getValues(name))
        removeBuiltIn(key)
        const index = fields.length
        append(rule)
        snapshots.current.set(`rule-new-${index}`, () => {
            names.forEach((name, position) => setValue(name, saved[position], {shouldDirty: true, shouldValidate: true}))
            openLine(key, names)
        })
        setOpen(new Set([`rule-new-${index}`]))
    }
    /** A built-in line becomes another built-in line, through a new rule that Cancel takes away again. */
    const builtInToBuiltIn = (key: 'types' | 'dates', kind: 'types' | 'season' | 'published' | 'downloaded') => {
        removeBuiltIn(key)
        const index = fields.length
        append(newEpisodeRule())
        addBuiltIn(index, kind)
    }
    const changeTypesLine = (action: EpisodeRule['action'], kind: FilterKind) => {
        if (DATE_KINDS.includes(kind) || kind === 'season') {
            builtInToBuiltIn('types', kind as 'season' | 'published' | 'downloaded')
            return
        }
        const rule = ruleOf(kind as EpisodeRule['field'], action)
        builtInToRule('types', kind === 'types' ? {...rule, episodeTypes: [...(values.epIdTypeList ?? [])]} : rule)
    }
    const changeDatesLine = (kind: FilterKind) => {
        if (DATE_KINDS.includes(kind)) {
            setDateField(kind)
        } else if ((kind === 'types' && !typesShown) || kind === 'season') {
            builtInToBuiltIn('dates', kind)
        } else {
            builtInToRule('dates', ruleOf(kind as EpisodeRule['field'], 'only'))
        }
    }
    const removeBuiltIn = (key: string) => {
        closeLine(key)
        if (key === 'types') setValue('epIdTypeList', [], {shouldDirty: true, shouldValidate: true})
        if (key === 'seasons') {
            for (const [name, value] of Object.entries(SEASONS_RESET)) setValue(name, value, {shouldDirty: true, shouldValidate: true})
        }
        if (key === 'dates') {
            for (const [name, value] of Object.entries(DATE_RESET)) setValue(name, value, {shouldDirty: true, shouldValidate: true})
        }
    }
    // A new filter turned into a built-in line: the line opens, and Cancel takes it away again.
    const addBuiltIn = (ruleIndex: number, kind: 'types' | 'season' | 'published' | 'downloaded') => {
        remove(ruleIndex)
        const key = kind === 'types' ? 'types' : kind === 'season' ? 'seasons' : 'dates'
        openLine(key, BUILT_IN_FIELDS[key])
        if (kind === 'types') {
            setValue('epIdTypeList', downloadProfileDefaultsFor(episodeIdentifier, tags).epIdTypeList, {shouldDirty: true})
        } else if (kind === 'season') {
            // The seasons line starts again from the latest season and the upcoming ones.
            setValue('seasons', seasons.length > 0 ? [seasons[seasons.length - 1]] : [], {shouldDirty: true})
            setValue('includeUpcomingSeasons', true, {shouldDirty: true})
            setValue('allSeasons', false, {shouldDirty: true})
        } else {
            // Like a new profile: the latest 25 episodes. Counting from the download date only works with days.
            setValue('downloadDaysInPast', kind === 'downloaded' ? 180 : 0, {shouldDirty: true})
            setValue('downloadEpisodeCount', kind === 'downloaded' ? 0 : 25, {shouldDirty: true})
            setValue('downloadStartingFrom', null, {shouldDirty: true})
            setValue('retentionFrom', kind, {shouldDirty: true})
            setValue('deleteOlderEpisodes', true, {shouldDirty: true})
        }
    }

    const typeLabel = (key: string) => tags?.find((tag) => tag.key === key)?.label ?? key
    const tagOptions = createSelectRegistry(
        'WhichEpisodesEpisodeTypes',
        Object.fromEntries((tags ?? []).map((tag) => [tag.key, {label: tag.label}])),
        (tags ?? []).map((tag) => tag.key),
    ).options
    const unselectedTypes = (tags ?? []).filter((tag) => !(values.epIdTypeList ?? []).includes(tag.key))
    /** Names the episode types a line leaves out on its count badge, when there are few enough to fit. */
    const excludedTypesLabel = (labels: string[]) => labels.length > 0 && labels.length <= 2 ? labels.join(', ') : undefined
    /** A type filter's count badge names the types it leaves out, like the built-in types line does. */
    const ruleCountLabel = (rule: EpisodeRule) => {
        if (rule.field !== 'types' || !rule.episodeTypes?.length) return undefined
        if (rule.action === 'skip') return excludedTypesLabel(rule.episodeTypes.map(typeLabel))
        return excludedTypesLabel((tags ?? []).filter((tag) => !rule.episodeTypes?.includes(tag.key)).map((tag) => tag.label))
    }
    const typeLabels = (values.epIdTypeList ?? []).map((key: string) => tags?.find((tag) => tag.key === key)?.label ?? key)
    const seasonNames = (values.seasons ?? []).map((season: SeasonItem) => seasons.find((item) => item.slug === season.slug)?.name ?? season.name)

    /** An open line's header: what the line does, and what it looks at. */
    const lineHead = (
        id: string, action: EpisodeRule['action'], kind: FilterKind,
        onAction: ((action: EpisodeRule['action']) => void) | null, onKind: (kind: FilterKind) => void,
    ) => (
        <span className="which-episodes-text which-episodes-rule-head">
            <SimpleSelect
                inputId={`${id}-action`} registry={EpisodeRuleActionReg} value={action}
                aria-label="What the filter does" isDisabled={onAction === null}
                onChange={(value) => onAction?.(value as EpisodeRule['action'])}
            />
            <span>if</span>
            <SimpleSelect
                inputId={`${id}-field`} registry={kindRegFor(kind)} value={kind}
                aria-label="What the filter looks at"
                onChange={(value) => onKind(value as FilterKind)}
            />
        </span>
    )

    const builtInHead = (key: string) => {
        if (key === 'types') return lineHead('types', 'only', 'types', (action) => action !== 'only' && changeTypesLine(action, 'types'), (kind) => kind !== 'types' && changeTypesLine('only', kind))
        if (key === 'dates') {
            const kind: FilterKind = values.retentionFrom === 'downloaded' ? 'downloaded' : 'published'
            // The date line only says which episodes to download; Keep and Skip would not mean anything for it.
            return lineHead('dates', 'only', kind, null, (next) => next !== kind && changeDatesLine(next))
        }
        return null
    }

    const builtInLine = (key: string, parts: Part[], count: number | undefined, content: ReactNode, countLabel?: string) => {
        const isOpen = open.has(key)
        const names = BUILT_IN_FIELDS[key]
        const head = isOpen ? builtInHead(key) : null
        return (
            <li key={key} className={`which-episodes-line${isOpen ? ' is-open' : ''}`}>
                <div className="which-episodes-sentence" onClick={(event) => toggleFromSentence(event, () => isOpen ? closeLine(key) : openLine(key, names))}>
                    {head ?? <span className="which-episodes-text"><Sentence parts={parts}/></span>}
                    <CountBadge count={count} label={countLabel}/>
                    <button
                        type="button" className={`which-episodes-icon${isOpen ? ' is-active' : ''}`}
                        aria-label={`Edit: ${plainText(parts)}`} aria-expanded={isOpen}
                        onClick={() => isOpen ? closeLine(key) : openLine(key, names)}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                    </button>
                    <button type="button" className="which-episodes-icon" aria-label={`Remove: ${plainText(parts)}`} onClick={() => removeBuiltIn(key)}>
                        <FontAwesomeIcon icon={faIcon('fass', 'trash')}/>
                    </button>
                </div>
                {isOpen && (
                    <div className="which-episodes-editor">
                        {content}
                        <div className="which-episodes-editor-actions">
                            <button type="button" className="btn" onClick={() => cancelLine(key, names)}>Cancel</button>
                            <button type="button" className="btn btn-primary" onClick={() => doneLine(key, names)}>Done</button>
                        </div>
                    </div>
                )}
            </li>
        )
    }

    const addFilter = () => {
        const index = fields.length
        append(newEpisodeRule())
        // A new rule has no snapshot: Cancel removes it.
        setOpen(new Set([`rule-new-${index}`]))
    }

    const leftOutLabel = (key: string | null) => {
        if (!key) return null
        if (key.startsWith('rule:')) {
            const rule = rules[sentRuleIndexes[Number(key.slice(5))]]
            return rule ? plainText(ruleSentence(rule, typeLabel)) : 'A filter'
        }
        return LEFT_OUT_LABELS[key] ?? key
    }

    return (
        <div className="form-row which-episodes">
            <div className="which-episodes-header">
                <label>Which episodes</label>
                <button type="button" className="btn btn-link" onClick={addFilter}>
                    <FontAwesomeIcon icon={faIcon('fass', 'plus')}/> Add filter
                </button>
            </div>
            <ul className="which-episodes-lines">
                {typesShown && builtInLine(
                    'types', typesSentence(typeLabels), result?.types, typesField,
                    excludedTypesLabel(unselectedTypes.map((tag) => tag.label)),
                )}
                {seasonsShown && builtInLine('seasons', withLead(!typesShown, seasonsSentence(seasonNames, !!values.includeUpcomingSeasons)), result?.seasons, seasonsField)}
                {datesShown && builtInLine('dates', withLead(!typesShown && !seasonsShown, dateSentence({
                    downloadDaysInPast: values.downloadDaysInPast ?? 0,
                    downloadEpisodeCount: values.downloadEpisodeCount ?? 0,
                    downloadStartingFrom: values.downloadStartingFrom ?? null,
                    deleteOlderEpisodes: !!values.deleteOlderEpisodes,
                    retentionFrom: values.retentionFrom ?? 'published',
                })), result?.dates, datesField)}
                {fields.map((item, index) => {
                    const rule: EpisodeRule = rules[index] ?? newEpisodeRule()
                    const key = open.has(`rule-new-${index}`) ? `rule-new-${index}` : `rule-${item.id}`
                    const isOpen = open.has(key)
                    const name = `rules.${index}`
                    const parts = ruleSentence(rule, typeLabel)
                    return (
                        <li key={item.id} className={`which-episodes-line${isOpen ? ' is-open' : ''}`}>
                            <div className="which-episodes-sentence" onClick={(event) => toggleFromSentence(event, () => isOpen ? closeLine(key) : openLine(key, [name]))}>
                                {isOpen ? lineHead(`rule-${index}`, rule.action, rule.field, (action) => setValue(`${name}.action`, action, {shouldDirty: true}), (value) => {
                                    if (value === 'season' || value === 'published' || value === 'downloaded' || (value === 'types' && rule.action === 'only' && !typesShown)) {
                                        addBuiltIn(index, value)
                                        return
                                    }
                                    const next = ruleOf(value as EpisodeRule['field'], rule.action)
                                    setValue(`${name}.field`, next.field, {shouldDirty: true})
                                    if (value === 'duration' && !rule.durationOperator) {
                                        setValue(`${name}.durationOperator`, next.durationOperator, {shouldDirty: true})
                                        setValue(`${name}.durationSeconds`, next.durationSeconds, {shouldDirty: true})
                                    }
                                    if (value === 'types' && !rule.episodeTypes) setValue(`${name}.episodeTypes`, [], {shouldDirty: true})
                                }) : <span className="which-episodes-text"><Sentence parts={parts}/></span>}
                                {rule.action === 'keep'
                                    ? <span className="which-episodes-count is-keep" title="Keep never stops a download; it protects matching downloads from deletion">keeps</span>
                                    : <CountBadge count={ruleCounts[index]} label={ruleCountLabel(rule)}/>}
                                <button
                                    type="button" className={`which-episodes-icon${isOpen ? ' is-active' : ''}`}
                                    aria-label={`Edit: ${plainText(parts)}`} aria-expanded={isOpen}
                                    onClick={() => isOpen ? closeLine(key) : openLine(key, [name])}
                                >
                                    <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                                </button>
                                <button
                                    type="button" className="which-episodes-icon" aria-label={`Remove: ${plainText(parts)}`}
                                    onClick={() => {
                                        closeLine(key)
                                        remove(index)
                                    }}
                                >
                                    <FontAwesomeIcon icon={faIcon('fass', 'trash')}/>
                                </button>
                            </div>
                            {isOpen && (
                                <div className="which-episodes-editor">
                                    {rule.field === 'types' ? (
                                        <div className="form-row">
                                            <label htmlFor={`rule-${index}-types`}>Is any of</label>
                                            <Select
                                                inputId={`rule-${index}-types`} isMulti closeMenuOnSelect={false}
                                                classNamePrefix="select"
                                                options={tagOptions}
                                                value={tagOptions.filter((option) => (rule.episodeTypes ?? []).includes(option.value))}
                                                onChange={(options) => setValue(`${name}.episodeTypes`, options.map((option) => option.value), {shouldDirty: true})}
                                            />
                                        </div>
                                    ) : rule.field === 'duration' ? (
                                        <div className="which-episodes-duration">
                                            <SimpleSelect
                                                inputId={`rule-${index}-operator`} registry={DurationOperatorReg}
                                                value={rule.durationOperator ?? 'shorter'} aria-label="Shorter or longer"
                                                onChange={(value) => setValue(`${name}.durationOperator`, value, {shouldDirty: true})}
                                            />
                                            <TimeInterval
                                                idPrefix={`rule-${index}-duration`} backendUnit="seconds"
                                                value={rule.durationSeconds ?? 0}
                                                onChange={(value) => setValue(
                                                    `${name}.durationSeconds`, Number.isFinite(value) && value > 0 ? Math.round(value) : null,
                                                    {shouldDirty: true},
                                                )}
                                            />
                                            <div className="help">Episodes whose length isn’t known yet are never left out by a duration filter.</div>
                                        </div>
                                    ) : (
                                        <RegexEditor
                                            id={`rule-${index}-regex`}
                                            field={rule.field === 'description' ? 'description' : 'title'}
                                            collectionId={collectionId ?? null}
                                            value={{pattern: rule.pattern ?? '', ignoreCase: rule.ignoreCase}}
                                            onChange={(value) => {
                                                setValue(`${name}.pattern`, value.pattern, {shouldDirty: true})
                                                setValue(`${name}.ignoreCase`, value.ignoreCase, {shouldDirty: true})
                                            }}
                                        />
                                    )}
                                    <RuleError form={form} index={index}/>
                                    <div className="which-episodes-editor-actions">
                                        <button type="button" className="btn" onClick={() => cancelLine(key, [name], index)}>Cancel</button>
                                        <button type="button" className="btn btn-primary" onClick={() => doneLine(key, [name])}>Done</button>
                                    </div>
                                </div>
                            )}
                        </li>
                    )
                })}
                {result && (
                    <li className="which-episodes-footer">
                        <span className="which-episodes-total">
                            <span className="which-episodes-total__label">Total</span>
                            <span>
                                <b className="which-episodes-total__count">{result.downloaded} of {result.total}</b> indexed episodes will be downloaded
                                {result.unavailable > 0 && <span className="which-episodes-muted"> ({result.unavailable} can’t be downloaded)</span>}
                            </span>
                        </span>
                        <button type="button" className="which-episodes-show" aria-expanded={showWhich} onClick={() => setShowWhich((value) => !value)}>
                            <FontAwesomeIcon icon={faIcon('fass', 'list')}/>
                            {showWhich ? 'Hide the list' : 'Show which'}
                            <FontAwesomeIcon icon={faIcon('fass', showWhich ? 'chevron-up' : 'chevron-down')}/>
                        </button>
                    </li>
                )}
            </ul>
            {showWhich && episodes && (
                <ul className="which-episodes-list" ref={listRef}>
                    {episodes.map((episode) => (
                        <li key={episode.id} className={episode.leftOutBy ? 'is-left-out' : 'is-downloaded'}>
                            <FontAwesomeIcon icon={episode.leftOutBy ? faIcon('fass', 'minus') : faIcon('fass', 'check')}/>
                            <span className="which-episodes-list-title">{episode.title}</span>
                            <span className="which-episodes-muted">{leftOutLabel(episode.leftOutBy) ?? 'Downloads'}</span>
                            <span className="which-episodes-muted">
                                {episode.publishedAt ? new Date(episode.publishedAt).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'}) : ''}
                            </span>
                        </li>
                    ))}
                    {hasMore && (
                        <li ref={endRef} className="which-episodes-list-end">
                            {moreFailed
                                ? <>Couldn’t load more episodes. <button type="button" className="btn btn-link" onClick={loadMore}>Try again</button></>
                                : <><FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin/> Loading more episodes…</>}
                        </li>
                    )}
                </ul>
            )}
            <div className="help">
                <ReadMore summary={<span>Each line narrows the one above it. The numbers show how many indexed episodes each line leaves out.</span>}>
                    <p>
                        An episode is downloaded when it passes the built-in lines and every <b>Skip</b> and <b>Only download</b> filter.
                        A <b>Keep</b> filter never stops a download; it protects matching downloads from being deleted by the date line.
                    </p>
                    <p>
                        Changing filters later only affects episodes that aren’t downloaded yet. An episode a filter skips can still be
                        downloaded by hand from its page.
                    </p>
                </ReadMore>
            </div>
        </div>
    )
}

function RuleError({form, index}: {form: UseFormReturn<any>; index: number}) {
    const errors = form.formState.errors as any
    const ruleErrors = errors?.rules?.[index]
    const message = ruleErrors?.pattern?.message ?? ruleErrors?.durationSeconds?.message ?? ruleErrors?.episodeTypes?.message ?? ruleErrors?.message ?? ruleErrors?.root?.message
    if (!message) return null
    return <div className="error" role="alert" aria-live="polite">{String(message)}</div>
}
