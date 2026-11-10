import {Fragment, useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent} from 'react'
import {Controller, useFieldArray, useWatch, type UseFormReturn} from 'react-hook-form'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Select from 'react-select'
import Switch from 'react-switch'

import {faIcon} from '../../icons/faIcon'
import ReadMore from '../../utils/ReadMore'
import TimeInterval from '../../utils/TimeInterval'
import SimpleSelect from '../common/SimpleSelect'
import SelectAllLabel from '../common/SelectAllLabel'
import NumberInput from '../common/NumberInput'
import DateInput from '../common/DateInput'
import RegexEditor from '../RegexEditor/RegexEditor'
import {EpisodeIdentifierReg} from '../../types/collection'
import {
    DurationOperatorReg,
    EpisodeFilterActionReg,
    EpisodeFilterFieldReg,
    newEpisodeFilter,
    type EpisodeFilter,
    type EpisodeFilterAction,
    type EpisodeFilterField,
} from '../../types/schemas/download_profile'
import type {SeasonDetachedOut} from '../../types/schemas/season'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {EpisodeTagRead} from '../../types/schemas/source'
import {useWhichEpisodes} from './useWhichEpisodes'
import {useCollectionExamples} from '../../lib/collectionExamples'
import {insertIndex, isDateLine, joinIgnoreCase, splitIgnoreCase} from './episodeFilters'
import {filterComplete, filterSentence, formatRunningTime, plainText, type Part} from './whichEpisodesText'
import './WhichEpisodes.css'

type Props = {
    form: UseFormReturn<any>
    episodeIdentifier?: string
    tags?: readonly EpisodeTagRead[]
    /** The collection's seasons, oldest first. */
    seasons: readonly SeasonDetachedOut[]
    /** The saved Collection; counts need its indexed episodes. */
    collectionId?: number
}

/** A date line downloads or keeps; skipping by date would not mean anything. */
const DateLineActionReg = createSelectRegistry('DateLineAction', {
    only: {label: 'Only download'},
    keep: {label: 'Keep'},
})

// Read after "Only download" or "Keep".
const PublishedModeReg = createSelectRegistry('PublishedMode', {
    count: {label: 'the latest … episodes'},
    days: {label: 'episodes published in the last … days'},
    since: {label: 'episodes published since a date'},
})
type PublishedMode = (typeof PublishedModeReg)['values'][number]

const UPCOMING_SEASONS = '__upcoming__'

function publishedMode(filter: EpisodeFilter): PublishedMode {
    if (filter.startingFrom !== null) return 'since'
    if (filter.days !== null) return 'days'
    return 'count'
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

/** Clicking a line's sentence opens or closes it, unless the click was on one of its controls. */
function toggleFromSentence(event: MouseEvent<HTMLDivElement>, toggle: () => void) {
    if ((event.target as HTMLElement).closest('button, a, input, select, textarea, [class*="select__"]')) return
    toggle()
}

function CountBadge({count, waiting, active, onShow}: {count: number | undefined; waiting: boolean; active: boolean; onShow: () => void}) {
    if (count === undefined) {
        // The counts load after the form; the line shows it is waiting for its number.
        return waiting ? <span className="which-episodes-count is-loading" aria-label="Counting">…</span> : null
    }
    return (
        <button
            type="button" className={`which-episodes-count${count === 0 ? ' is-zero' : ''}`}
            title="Show the episodes this filter leaves out" disabled={count === 0} onClick={onShow} aria-pressed={!!active}
        >
            −{count}
        </button>
    )
}

/** A number field of a filter: empty means no number yet. */
function numberOrNull(value: string): number | null {
    if (value.trim() === '') return null
    const number = Number(value)
    return Number.isFinite(number) ? Math.round(number) : null
}

/** One list of filters, from top to bottom, that decides which episodes a Download Profile downloads and keeps. */
export default function WhichEpisodes({form, episodeIdentifier, tags, seasons, collectionId}: Props) {
    const {control, getValues, setValue, trigger} = form
    const {fields, insert, remove, move} = useFieldArray({control, name: 'filters'})
    const seasonal = episodeIdentifier === EpisodeIdentifierReg.Enum.seasonal

    const values = useWatch({control}) as Record<string, any>
    const filters: EpisodeFilter[] = values.filters ?? []
    const deleteOlder = !!values.deleteOlderEpisodes

    // While a collection is added, the counts run over its newest episodes.
    const examples = useCollectionExamples()
    const exampleCollection = collectionId === undefined && examples && !examples.failed ? examples.collection : undefined

    // One line is open at a time. What it was when opened lets Cancel put it back; a new line has nothing and is removed.
    const [openId, setOpenId] = useState<string | null>(null)
    const snapshot = useRef<{filter: EpisodeFilter; deleteOlder: boolean} | null>(null)
    const [showWhich, setShowWhich] = useState(false)
    // Which episodes the list shows: all, the ones that download, the ones that can't be, or the ones one line leaves out.
    const [shown, setShown] = useState<string>('all')
    const shownRef = useRef<HTMLDivElement | null>(null)
    const dragFrom = useRef<number | null>(null)
    const [dragOver, setDragOver] = useState<number | null>(null)

    // Filters still being written are left out of the count until they are complete.
    const sentIndexes = useMemo(() => filters.flatMap((filter, index) => filterComplete(filter) ? [index] : []), [filters])
    const request = useMemo(() => {
        if (collectionId === undefined && exampleCollection === undefined) return null
        return {
            ...(collectionId !== undefined ? {collectionId} : {exampleCollection}),
            downloadWithCountdown: !!values.downloadWithCountdown,
            filters: sentIndexes.map((index) => filters[index]),
            includeEpisodes: showWhich,
            episodesShown: shown === 'all' ? undefined : shown,
        }
    }, [collectionId, exampleCollection, values.downloadWithCountdown, filters, sentIndexes, showWhich, shown])
    const {result, loading, episodes, hasMore, loadingMore, moreFailed, loadMore} = useWhichEpisodes(request)
    const counts = useMemo(() => {
        const byIndex = new Map<number, number>()
        sentIndexes.forEach((index, sent) => {
            const count = result?.filters[sent]
            if (count !== undefined) byIndex.set(index, count)
        })
        return byIndex
    }, [sentIndexes, result])

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

    const typeLabel = (key: string) => tags?.find((tag) => tag.key === key)?.label ?? key
    const seasonLabel = (slug: string) => seasons.find((season) => season.slug === slug)?.name ?? slug
    const sentenceOf = (filter: EpisodeFilter) => filterSentence(filter, typeLabel, seasonLabel, deleteOlder)
    const tagOptions = createSelectRegistry(
        'WhichEpisodesEpisodeTypes',
        Object.fromEntries((tags ?? []).map((tag) => [tag.key, {label: tag.label}])),
        (tags ?? []).map((tag) => tag.key),
    ).options
    // Upcoming seasons first, then the newest season first.
    const seasonOptions = createSelectRegistry(
        'WhichEpisodesSeasons',
        {
            [UPCOMING_SEASONS]: {label: 'Upcoming seasons'},
            ...Object.fromEntries(seasons.map((season) => [season.slug, {label: season.name}])),
        },
        [UPCOMING_SEASONS, ...[...seasons].reverse().map((season) => season.slug)],
    ).options

    /** What a line can look at: a collection with seasons can filter on them, and the list has one line per date. */
    const fieldRegFor = (index: number) => createSelectRegistry('WhichEpisodesFilterField', Object.fromEntries(
        EpisodeFilterFieldReg.values.filter((field) => {
            if (field === 'seasons') return seasonal || seasons.length > 0 || filters[index]?.field === 'seasons'
            if (isDateLine({field})) return !filters.some((filter, other) => other !== index && filter.field === field)
            return true
        }).map((field) => [field, EpisodeFilterFieldReg.spec[field]]),
    ))

    const openLine = (id: string, index: number) => {
        snapshot.current = {filter: getValues(`filters.${index}`), deleteOlder: !!getValues('deleteOlderEpisodes')}
        setOpenId(id)
    }
    const closeLine = () => {
        snapshot.current = null
        setOpenId(null)
    }
    const cancelLine = (index: number) => {
        if (snapshot.current) {
            setValue(`filters.${index}`, snapshot.current.filter, {shouldDirty: true, shouldValidate: true})
            setValue('deleteOlderEpisodes', snapshot.current.deleteOlder, {shouldDirty: true})
        } else {
            remove(index)
        }
        closeLine()
    }
    const doneLine = async (index: number) => {
        if (await trigger([`filters.${index}`, 'filters'])) closeLine()
    }

    const addFilter = () => {
        const filter = newEpisodeFilter('title')
        const index = insertIndex(filters, filter.field)
        insert(index, filter)
        // A new line has no snapshot: Cancel removes it. Its id is known after the insert renders.
        snapshot.current = null
        setOpenId(`new:${index}`)
    }
    useEffect(() => {
        if (!openId?.startsWith('new:')) return
        const id = fields[Number(openId.slice(4))]?.id
        if (id) setOpenId(id)
    }, [openId, fields])

    const changeField = (index: number, field: EpisodeFilterField) => {
        const current = filters[index]
        setValue(`filters.${index}`, newEpisodeFilter(field, current?.action), {shouldDirty: true})
        // A line you are adding moves to where a filter of its kind goes.
        if (!snapshot.current) {
            const target = insertIndex(filters.filter((_, other) => other !== index), field)
            if (target !== index) move(index, target)
        }
    }
    const changePublishedMode = (index: number, mode: PublishedMode) => {
        const name = `filters.${index}`
        setValue(`${name}.count`, mode === 'count' ? 25 : null, {shouldDirty: true})
        setValue(`${name}.days`, mode === 'days' ? 180 : null, {shouldDirty: true})
        setValue(`${name}.startingFrom`, mode === 'since' ? new Date().toISOString().slice(0, 10) : null, {shouldDirty: true})
    }

    const onDragStart = (event: DragEvent<HTMLLIElement>, index: number) => {
        dragFrom.current = index
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', String(index))
    }
    const onDrop = (event: DragEvent<HTMLLIElement>, index: number) => {
        event.preventDefault()
        const from = dragFrom.current
        dragFrom.current = null
        setDragOver(null)
        if (from !== null && from !== index) move(from, index)
    }

    // A filter's count opens the list on the episodes that filter leaves out.
    const showLeftOutBy = (index: number) => {
        setShown(`filter:${sentIndexes.indexOf(index)}`)
        setShowWhich(true)
        window.setTimeout(() => shownRef.current?.scrollIntoView({behavior: 'smooth', block: 'nearest'}), 50)
    }
    const oneFilter = shown.startsWith('filter:')

    const shownReg = useMemo(() => {
        const spec: Record<string, {label: string}> = {
            all: {label: `All episodes${result ? ` (${result.total})` : ''}`},
            downloads: {label: `Episodes that download${result ? ` (${result.downloaded})` : ''}`},
        }
        sentIndexes.forEach((index, sent) => {
            const filter = filters[index]
            if (filter.action === 'keep') return
            spec[`filter:${sent}`] = {label: `Left out by filter ${index + 1}: ${plainText(sentenceOf(filter))}${result ? ` (${result.filters[sent]})` : ''}`}
        })
        if (result && result.unavailable > 0) spec.unavailable = {label: `Can’t be downloaded (${result.unavailable})`}
        return createSelectRegistry('ShownEpisodes', spec)
    }, [sentIndexes, filters, result])

    // A filter that was removed, became a Keep or is being rewritten no longer has episodes of its own to show.
    useEffect(() => {
        if (result && !shownReg.is(shown)) setShown('all')
    }, [result, shownReg, shown])

    const leftOutLabel = (key: string | null) => {
        if (!key) return null
        if (key === 'unavailable') return 'Can’t be downloaded'
        if (key.startsWith('filter:')) {
            const filter = filters[sentIndexes[Number(key.slice(7))]]
            return filter ? plainText(sentenceOf(filter)) : 'A filter'
        }
        return key
    }

    const editor = (filter: EpisodeFilter, index: number) => {
        const name = `filters.${index}`
        const id = `filter-${index}`
        if (filter.field === 'types') {
            return (
                <div className="form-row">
                    <label htmlFor={`${id}-types`}>Is any of</label>
                    <Select
                        inputId={`${id}-types`} isMulti closeMenuOnSelect={false}
                        classNamePrefix="select"
                        options={tagOptions}
                        value={tagOptions.filter((option) => (filter.episodeTypes ?? []).includes(option.value))}
                        onChange={(options) => setValue(`${name}.episodeTypes`, options.map((option) => option.value), {shouldDirty: true})}
                    />
                    <div className="help">
                        <ReadMore summary={<span>The episode types of the collection’s Source</span>}>
                            {(tags ?? []).map((tag) => <p key={tag.key}><b>{tag.label}</b>: {tag.help}.</p>)}
                        </ReadMore>
                    </div>
                </div>
            )
        }
        if (filter.field === 'seasons') {
            const chosen = [...(filter.includeUpcoming ? [UPCOMING_SEASONS] : []), ...(filter.seasonSlugs ?? [])]
            return (
                <div className="form-row">
                    <SelectAllLabel
                        htmlFor={`${id}-seasons`}
                        allChosen={seasonOptions.every((option) => chosen.includes(option.value))}
                        onSelectAll={() => {
                            setValue(`${name}.includeUpcoming`, true, {shouldDirty: true})
                            setValue(
                                `${name}.seasonSlugs`,
                                seasonOptions.map((option) => option.value).filter((value) => value !== UPCOMING_SEASONS),
                                {shouldDirty: true},
                            )
                        }}
                    >
                        Is any of
                    </SelectAllLabel>
                    <Select
                        inputId={`${id}-seasons`} isMulti closeMenuOnSelect={false} isClearable
                        classNamePrefix="select"
                        options={seasonOptions}
                        value={seasonOptions.filter((option) => chosen.includes(option.value))}
                        onChange={(options) => {
                            const picked = options.map((option) => option.value)
                            setValue(`${name}.includeUpcoming`, picked.includes(UPCOMING_SEASONS), {shouldDirty: true})
                            setValue(`${name}.seasonSlugs`, picked.filter((value) => value !== UPCOMING_SEASONS), {shouldDirty: true})
                        }}
                    />
                    <div className="help">With upcoming seasons, a season the collection gets later is added to this filter.</div>
                </div>
            )
        }
        if (filter.field === 'duration') {
            return (
                <div className="which-episodes-duration">
                    <SimpleSelect
                        inputId={`${id}-operator`} registry={DurationOperatorReg}
                        value={filter.durationOperator ?? 'shorter'} aria-label="Shorter or longer"
                        onChange={(value) => setValue(`${name}.durationOperator`, value, {shouldDirty: true})}
                    />
                    <TimeInterval
                        idPrefix={`${id}-duration`} backendUnit="seconds"
                        value={filter.durationSeconds ?? 0}
                        onChange={(value) => setValue(
                            `${name}.durationSeconds`, Number.isFinite(value) && value > 0 ? Math.round(value) : null,
                            {shouldDirty: true},
                        )}
                    />
                    <div className="help">Episodes whose length isn’t known yet are never left out by a duration filter.</div>
                </div>
            )
        }
        if (filter.field === 'published' || filter.field === 'downloaded') {
            const mode = filter.field === 'downloaded' ? 'days' : publishedMode(filter)
            const deletes = filter.action === 'only' && mode !== 'since'
            return (
                <>
                    {filter.field === 'published' && (
                        <div className="form-row">
                            <SimpleSelect
                                inputId={`${id}-mode`} aria-label="Which episodes by date"
                                registry={PublishedModeReg} value={mode}
                                onChange={(value) => changePublishedMode(index, value as PublishedMode)}
                            />
                        </div>
                    )}
                    {mode === 'count' && (
                        <div className="form-row">
                            <label htmlFor={`${id}-count`}>Episodes</label>
                            <NumberInput
                                id={`${id}-count`} inputMode="numeric" min={1} step={1}
                                value={filter.count ?? ''}
                                onChange={(event) => setValue(`${name}.count`, numberOrNull(event.target.value), {shouldDirty: true})}
                            />
                            <div className="help">The newest episodes that pass the filters above this one.</div>
                        </div>
                    )}
                    {mode === 'days' && (
                        <div className="form-row">
                            <label htmlFor={`${id}-days`}>{filter.field === 'downloaded' && filter.action === 'keep' ? 'Keep each download for … days' : 'Days'}</label>
                            <NumberInput
                                id={`${id}-days`} inputMode="numeric" min={1} step={1}
                                value={filter.days ?? ''}
                                onChange={(event) => setValue(`${name}.days`, numberOrNull(event.target.value), {shouldDirty: true})}
                            />
                            {filter.field === 'downloaded' && filter.action === 'only' && (
                                <div className="help">Only episodes published in this many days are downloaded.</div>
                            )}
                        </div>
                    )}
                    {mode === 'since' && (
                        <div className="form-row">
                            <label htmlFor={`${id}-since`}>On or after</label>
                            <DateInput
                                id={`${id}-since`}
                                value={filter.startingFrom}
                                onChange={(value) => setValue(`${name}.startingFrom`, value, {shouldDirty: true})}
                                clearButtonLabel="Clear the date"
                            />
                            {filter.action === 'only' && (
                                <div className="help">Episodes from before the date that are already downloaded are not deleted.</div>
                            )}
                        </div>
                    )}
                    {deletes && (
                        <div className="form-row">
                            <label htmlFor={`${id}-delete`}>{filter.field === 'downloaded'
                                ? `And delete them ${filter.days || '…'} ${filter.days === 1 ? 'day' : 'days'} after downloading`
                                : mode === 'count' ? 'And delete them once they are no longer among the latest' : 'And delete them once they are older'}</label>
                            <Controller
                                control={control}
                                name="deleteOlderEpisodes"
                                render={({field}) => (
                                    <Switch
                                        id={`${id}-delete`}
                                        checked={!!field.value}
                                        onChange={(checked) => field.onChange(checked)}
                                        onColor="#0ea5e9"
                                        offColor="#d1d5db"
                                        uncheckedIcon={false}
                                        checkedIcon={false}
                                    />
                                )}
                            />
                            <div className="help">Downloads you keep, and downloads a Keep filter matches, are never deleted.</div>
                        </div>
                    )}
                </>
            )
        }
        const regex = splitIgnoreCase(filter.pattern)
        return (
            <RegexEditor
                id={`${id}-regex`}
                field={filter.field === 'description' ? 'description' : 'title'}
                collectionId={collectionId ?? null}
                value={regex}
                onChange={(value) => setValue(`${name}.pattern`, joinIgnoreCase(value), {shouldDirty: true})}
            />
        )
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
                {fields.length === 0 && (
                    <li className="which-episodes-line">
                        <div className="which-episodes-sentence is-empty">
                            <span className="which-episodes-text">Download <b>every</b> episode</span>
                        </div>
                    </li>
                )}
                {fields.map((item, index) => {
                    const filter: EpisodeFilter = filters[index] ?? newEpisodeFilter()
                    const isOpen = openId === item.id
                    const parts = sentenceOf(filter)
                    const toggle = () => isOpen ? closeLine() : openLine(item.id, index)
                    const fieldReg = fieldRegFor(index)
                    return (
                        <li
                            key={item.id}
                            className={`which-episodes-line${isOpen ? ' is-open' : ''}${dragOver === index ? ' is-drop-target' : ''}`}
                            draggable={!isOpen}
                            onDragStart={(event) => onDragStart(event, index)}
                            onDragOver={(event) => {
                                if (dragFrom.current === null) return
                                event.preventDefault()
                                if (dragOver !== index) setDragOver(index)
                            }}
                            onDragLeave={() => setDragOver((current) => current === index ? null : current)}
                            onDrop={(event) => onDrop(event, index)}
                            onDragEnd={() => {
                                dragFrom.current = null
                                setDragOver(null)
                            }}
                        >
                            <div className="which-episodes-sentence" onClick={(event) => toggleFromSentence(event, toggle)}>
                                {!isOpen && (
                                    <span className="which-episodes-grip" title="Drag to change the order" aria-hidden="true">
                                        <FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/>
                                    </span>
                                )}
                                {isOpen ? (
                                    <span className="which-episodes-text which-episodes-rule-head">
                                        <SimpleSelect
                                            inputId={`filter-${index}-action`}
                                            registry={isDateLine(filter) ? DateLineActionReg : EpisodeFilterActionReg}
                                            value={filter.action}
                                            aria-label="What the filter does"
                                            onChange={(value) => setValue(`filters.${index}.action`, value as EpisodeFilterAction, {shouldDirty: true})}
                                        />
                                        {!isDateLine(filter) && <span>if</span>}
                                        <SimpleSelect
                                            inputId={`filter-${index}-field`} registry={fieldReg} value={filter.field}
                                            aria-label="What the filter looks at"
                                            onChange={(value) => value !== filter.field && changeField(index, value as EpisodeFilterField)}
                                        />
                                    </span>
                                ) : <span className="which-episodes-text"><Sentence parts={parts}/></span>}
                                {filter.action === 'keep'
                                    ? <span className="which-episodes-count is-keep" title="Keep never stops a download; it protects matching downloads from deletion">keeps</span>
                                    : <CountBadge
                                        count={counts.get(index)} waiting={request !== null && filterComplete(filter)}
                                        active={showWhich && shown === `filter:${sentIndexes.indexOf(index)}`}
                                        onShow={() => showLeftOutBy(index)}
                                    />}
                                <button
                                    type="button" className={`which-episodes-icon${isOpen ? ' is-active' : ''}`}
                                    aria-label={`Edit: ${plainText(parts)}`} aria-expanded={isOpen}
                                    onClick={toggle}
                                >
                                    <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                                </button>
                                <button
                                    type="button" className="which-episodes-icon" aria-label={`Remove: ${plainText(parts)}`}
                                    onClick={() => {
                                        if (isOpen) closeLine()
                                        remove(index)
                                    }}
                                >
                                    <FontAwesomeIcon icon={faIcon('fass', 'trash')}/>
                                </button>
                            </div>
                            {isOpen && (
                                <div className="which-episodes-editor">
                                    {editor(filter, index)}
                                    <FilterError form={form} index={index}/>
                                    <div className="which-episodes-editor-actions">
                                        <button
                                            type="button" className="btn which-episodes-move" disabled={index === 0}
                                            onClick={() => move(index, index - 1)} aria-label="Move up"
                                        >
                                            <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                        </button>
                                        <button
                                            type="button" className="btn which-episodes-move" disabled={index === fields.length - 1}
                                            onClick={() => move(index, index + 1)} aria-label="Move down"
                                        >
                                            <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                        </button>
                                        <span className="which-episodes-editor-spacer"/>
                                        <button type="button" className="btn" onClick={() => cancelLine(index)}>Cancel</button>
                                        <button type="button" className="btn btn-primary" onClick={() => doneLine(index)}>Done</button>
                                    </div>
                                </div>
                            )}
                        </li>
                    )
                })}
                {request !== null && (
                    // Shown before the count arrives, at the same height, so the form below does not move.
                    <li className="which-episodes-footer" aria-busy={!result && loading}>
                        <div className="which-episodes-footer-head">
                            <span className="which-episodes-total">
                                <span className="which-episodes-total__label">Total</span>
                                {result ? (
                                    <span>
                                        <b className="which-episodes-total__count">{result.downloaded} of {result.total}</b>
                                        {exampleCollection ? ' newest episodes would be downloaded' : ' indexed episodes will be downloaded'}
                                        {result.unavailable > 0 && <span className="which-episodes-muted"> ({result.unavailable} can’t be downloaded)</span>}
                                    </span>
                                ) : loading ? (
                                    <span><FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin/> Counting episodes…</span>
                                ) : (
                                    <span>Couldn’t count the episodes</span>
                                )}
                            </span>
                            <button
                                type="button" className="which-episodes-show" aria-expanded={showWhich} disabled={!result}
                                onClick={() => {
                                    setShowWhich((value) => !value)
                                    setShown('all')
                                }}
                            >
                                <FontAwesomeIcon icon={faIcon('fass', 'list')}/>
                                {showWhich ? 'Hide the list' : 'Show which'}
                                <FontAwesomeIcon icon={faIcon('fass', showWhich ? 'chevron-up' : 'chevron-down')}/>
                            </button>
                        </div>
                        {showWhich && result && (
                            <div className="which-episodes-shown" ref={shownRef}>
                                <label htmlFor="which-episodes-shown">Show</label>
                                <SimpleSelect
                                    inputId="which-episodes-shown" registry={shownReg} value={shown} className="which-episodes-shown-select"
                                    onChange={setShown} menuPlacement="auto"
                                />
                            </div>
                        )}
                        {showWhich && episodes && (
                            <ul className="which-episodes-list" ref={listRef}>
                                {episodes.map((episode) => (
                                    <li key={episode.id} className={episode.leftOutBy ? 'is-left-out' : 'is-downloaded'}>
                                        <FontAwesomeIcon icon={episode.leftOutBy ? faIcon('fass', 'minus') : faIcon('fass', 'check')}/>
                                        <span className="which-episodes-list-main">
                                            <span className="which-episodes-list-title">{episode.title}</span>
                                            {/* Every episode in a one-filter list was left out by that filter, so it doesn't say so again. */}
                                            {!oneFilter && (
                                                <span className="which-episodes-muted which-episodes-list-reason">
                                                    {leftOutLabel(episode.leftOutBy) ?? 'Downloads'}
                                                </span>
                                            )}
                                        </span>
                                        <span className="which-episodes-list-meta">
                                            {episode.episodeType && <span className="which-episodes-type">{typeLabel(episode.episodeType)}</span>}
                                            {episode.duration ? <span>{formatRunningTime(episode.duration)}</span> : null}
                                            {episode.publishedAt && (
                                                <span>{new Date(episode.publishedAt).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'})}</span>
                                            )}
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
                    </li>
                )}
            </ul>
            <ListError form={form}/>
            <div className="help">
                <ReadMore summary={<span>Filters apply from top to bottom. Drag a filter to change the order. The numbers show how many {exampleCollection
                    ? 'of the newest episodes, looked up for this collection before it is saved,'
                    : 'indexed episodes'} each filter leaves out.</span>}>
                    <p>
                        An episode is downloaded when no <b>Skip</b> or <b>Only download</b> filter leaves it out. Each filter looks only at
                        the episodes the filters above it let through, so “the latest 25 episodes” below an episode type filter are the
                        latest 25 of those types.
                    </p>
                    <p>
                        A <b>Keep</b> filter never stops a download. Wherever it is in the list, it protects the downloads it matches from
                        being deleted. Only a published or downloaded filter deletes downloads, and only when you turn that on.
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

function FilterError({form, index}: {form: UseFormReturn<any>; index: number}) {
    const errors = form.formState.errors as any
    const filterErrors = errors?.filters?.[index]
    const message = filterErrors?.pattern?.message ?? filterErrors?.durationSeconds?.message ?? filterErrors?.episodeTypes?.message
        ?? filterErrors?.seasonSlugs?.message ?? filterErrors?.days?.message ?? filterErrors?.count?.message
        ?? filterErrors?.startingFrom?.message ?? filterErrors?.action?.message ?? filterErrors?.message ?? filterErrors?.root?.message
    if (!message) return null
    return <div className="error" role="alert" aria-live="polite">{String(message)}</div>
}

/** An error about the list as a whole, such as two published lines, or one the server gave. */
function ListError({form}: {form: UseFormReturn<any>}) {
    const errors = form.formState.errors as any
    const message = errors?.filters?.root?.message ?? errors?.filters?.message
    if (!message) return null
    return <div className="error" role="alert" aria-live="polite">{String(message)}</div>
}
