import {Fragment, useMemo, useRef, useState, type MouseEvent, type ReactNode} from 'react'
import {useFieldArray, useWatch, type UseFormReturn} from 'react-hook-form'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

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
import {dateSentence, plainText, ruleSentence, seasonsSentence, typesSentence, type Part} from './whichEpisodesText'
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
    seasons: ['seasons', 'includeUpcomingSeasons'],
    dates: [
        'downloadDaysInPast', 'downloadEpisodeCount',
        'downloadStartingFrom', 'deleteOlderEpisodes', 'retentionFrom',
    ],
}

// A new filter can also be one of the built-in lines while that line isn't there.
const FILTER_KINDS = {
    title: {label: 'title'},
    description: {label: 'description'},
    duration: {label: 'duration'},
    types: {label: 'episode types'},
    published: {label: 'publication date'},
    downloaded: {label: 'download date'},
}
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
    const builtIns = ['types', ...(seasonal ? ['seasons'] : []), ...(episodeIdentifier !== undefined ? ['dates'] : [])]
    const datesAllowed = episodeIdentifier !== undefined
    // While creating, every built-in line stays open until you open or close one yourself.
    const [chosenOpen, setOpen] = useState<Set<string> | null>(startOpen ? null : new Set())
    const open = chosenOpen ?? new Set(builtIns)
    const [showWhich, setShowWhich] = useState(false)
    const [shown, setShown] = useState(100)
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
            // Lines still being written are left out of the count until they are complete.
            rules: rules.filter((rule) => rule.field === 'duration' ? !!rule.durationSeconds && !!rule.durationOperator : !!rule.pattern),
            includeEpisodes: showWhich,
        }
    }, [collectionId, values, rules, showWhich])
    const {result} = useWhichEpisodes(request)
    // Counts of the rules sent, mapped back to every rule line (unfinished lines have none).
    const ruleCounts = useMemo(() => {
        const counts: Array<number | undefined> = []
        let sent = 0
        for (const rule of rules) {
            const complete = rule.field === 'duration' ? !!rule.durationSeconds && !!rule.durationOperator : !!rule.pattern
            counts.push(complete && result ? result.rules[sent] : undefined)
            if (complete) sent += 1
        }
        return counts
    }, [rules, result])
    const sentRuleIndexes = useMemo(() => rules.flatMap((rule, index) => (
        (rule.field === 'duration' ? rule.durationSeconds && rule.durationOperator : rule.pattern) ? [index] : []
    )), [rules])

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
        const snapshot = snapshots.current.get(key) as unknown[] | undefined
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

    // Episode types and the date window are filters you can remove and add again; while open they stay.
    const typesShown = (values.epIdTypeList ?? []).length > 0 || open.has('types')
    const hasDateLimit = (values.downloadDaysInPast ?? 0) > 0 || (values.downloadEpisodeCount ?? 0) > 0
        || !!values.downloadStartingFrom || values.retentionFrom === 'downloaded'
    const datesShown = datesAllowed && (hasDateLimit || open.has('dates'))
    const kindReg = createSelectRegistry('WhichEpisodesFilterKind', FILTER_KINDS, [
        ...EpisodeRuleFieldReg.values,
        ...(typesShown ? [] : ['types' as const]),
        ...(datesAllowed && !datesShown ? ['published' as const, 'downloaded' as const] : []),
    ])
    const removeBuiltIn = (key: string) => {
        closeLine(key)
        if (key === 'types') setValue('epIdTypeList', [], {shouldDirty: true, shouldValidate: true})
        if (key === 'dates') {
            for (const [name, value] of Object.entries(DATE_RESET)) setValue(name, value, {shouldDirty: true, shouldValidate: true})
        }
    }
    // A new filter turned into a built-in line: the line opens, and Cancel takes it away again.
    const addBuiltIn = (ruleIndex: number, kind: 'types' | 'published' | 'downloaded') => {
        remove(ruleIndex)
        const key = kind === 'types' ? 'types' : 'dates'
        openLine(key, BUILT_IN_FIELDS[key])
        if (kind === 'types') {
            setValue('epIdTypeList', downloadProfileDefaultsFor(episodeIdentifier, tags).epIdTypeList, {shouldDirty: true})
        } else {
            setValue('downloadDaysInPast', 180, {shouldDirty: true})
            setValue('retentionFrom', kind, {shouldDirty: true})
            setValue('deleteOlderEpisodes', kind === 'downloaded', {shouldDirty: true})
        }
    }

    const unselectedTypes = (tags ?? []).filter((tag) => !(values.epIdTypeList ?? []).includes(tag.key))
    const typeLabels = (values.epIdTypeList ?? []).map((key: string) => tags?.find((tag) => tag.key === key)?.label ?? key)
    const seasonNames = (values.seasons ?? []).map((season: SeasonItem) => seasons.find((item) => item.slug === season.slug)?.name ?? season.name)

    const builtInLine = (key: string, parts: Part[], count: number | undefined, content: ReactNode, countLabel?: string) => {
        const isOpen = open.has(key)
        const names = BUILT_IN_FIELDS[key]
        return (
            <li key={key} className={`which-episodes-line${isOpen ? ' is-open' : ''}`}>
                <div className="which-episodes-sentence" onClick={(event) => toggleFromSentence(event, () => isOpen ? closeLine(key) : openLine(key, names))}>
                    <span className="which-episodes-text"><Sentence parts={parts}/></span>
                    <CountBadge count={count} label={countLabel}/>
                    <button
                        type="button" className={`which-episodes-icon${isOpen ? ' is-active' : ''}`}
                        aria-label={`Edit: ${plainText(parts)}`} aria-expanded={isOpen}
                        onClick={() => isOpen ? closeLine(key) : openLine(key, names)}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                    </button>
                    {key === 'seasons'
                        ? <span className="which-episodes-icon is-placeholder" title="The seasons line can’t be removed">—</span>
                        : (
                            <button type="button" className="which-episodes-icon" aria-label={`Remove: ${plainText(parts)}`} onClick={() => removeBuiltIn(key)}>
                                <FontAwesomeIcon icon={faIcon('fass', 'trash')}/>
                            </button>
                        )}
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
            return rule ? plainText(ruleSentence(rule)) : 'A filter'
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
                    unselectedTypes.length > 0 && unselectedTypes.length <= 2 ? unselectedTypes.map((tag) => tag.label).join(', ') : undefined,
                )}
                {seasonal && builtInLine('seasons', seasonsSentence(seasonNames, !!values.includeUpcomingSeasons), result?.seasons, seasonsField)}
                {datesShown && builtInLine('dates', withLead(!typesShown && !seasonal, dateSentence({
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
                    const parts = ruleSentence(rule)
                    return (
                        <li key={item.id} className={`which-episodes-line${isOpen ? ' is-open' : ''}`}>
                            <div className="which-episodes-sentence" onClick={(event) => toggleFromSentence(event, () => isOpen ? closeLine(key) : openLine(key, [name]))}>
                                {isOpen ? (
                                    <span className="which-episodes-text which-episodes-rule-head">
                                        <SimpleSelect
                                            inputId={`rule-${index}-action`} registry={EpisodeRuleActionReg} value={rule.action}
                                            aria-label="What the filter does"
                                            onChange={(value) => setValue(`${name}.action`, value, {shouldDirty: true})}
                                        />
                                        <span>if the</span>
                                        <SimpleSelect
                                            inputId={`rule-${index}-field`} registry={kindReg} value={rule.field}
                                            aria-label="What the filter looks at"
                                            onChange={(value) => {
                                                if (value === 'types' || value === 'published' || value === 'downloaded') {
                                                    addBuiltIn(index, value)
                                                    return
                                                }
                                                setValue(`${name}.field`, value, {shouldDirty: true})
                                                if (value === 'duration' && !rule.durationOperator) {
                                                    setValue(`${name}.durationOperator`, 'shorter', {shouldDirty: true})
                                                    setValue(`${name}.durationSeconds`, 120, {shouldDirty: true})
                                                }
                                            }}
                                        />
                                    </span>
                                ) : (
                                    <span className="which-episodes-text"><Sentence parts={parts}/></span>
                                )}
                                {rule.action === 'keep'
                                    ? <span className="which-episodes-count is-keep" title="Keep never stops a download; it protects matching downloads from deletion">keeps</span>
                                    : <CountBadge count={ruleCounts[index]}/>}
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
                                    {rule.field === 'duration' ? (
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
            {showWhich && result?.episodes && (
                <ul className="which-episodes-list">
                    {result.episodes.slice(0, shown).map((episode) => (
                        <li key={episode.id} className={episode.leftOutBy ? 'is-left-out' : 'is-downloaded'}>
                            <FontAwesomeIcon icon={episode.leftOutBy ? faIcon('fass', 'minus') : faIcon('fass', 'check')}/>
                            <span className="which-episodes-list-title">{episode.title}</span>
                            <span className="which-episodes-muted">{leftOutLabel(episode.leftOutBy) ?? 'Downloads'}</span>
                            <span className="which-episodes-muted">
                                {episode.publishedAt ? new Date(episode.publishedAt).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'}) : ''}
                            </span>
                        </li>
                    ))}
                    {result.episodes.length > shown && (
                        <li><button type="button" className="btn btn-link" onClick={() => setShown((value) => value + 200)}>Show more</button></li>
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
    const message = ruleErrors?.pattern?.message ?? ruleErrors?.durationSeconds?.message ?? ruleErrors?.message ?? ruleErrors?.root?.message
    if (!message) return null
    return <div className="error" role="alert" aria-live="polite">{String(message)}</div>
}
