import {Fragment, useMemo, useState} from 'react'
import type {KeyboardEvent, ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import Switch from 'react-switch'

import SimpleSelect from '../common/SimpleSelect'
import {faIcon} from '../../icons/faIcon'
import {createSelectRegistry} from '../../utils/selectRegistry'
import type {RegexSample} from '../../types/schemas/regex'
import {explainRegex, regexTokens, type TokenKind} from './regexExplain'
import {
    DATE_FORMATS,
    blockName,
    blockRegex,
    blockSummary,
    buildRegex,
    describeBlocks,
    inferPreset,
    newBlock,
    parseBlocks,
    presetUnavailable,
    shortcutBlocks,
    shortcutOf,
    switchPreset,
    type Block,
    type BlockKind,
    type DateFormat,
    type OneOfBlock,
    type Preset,
    type RegexValue,
    type SpacesMode,
    type TextBlock,
    type Where,
} from './regexModel'
import {useRegexCheck} from './useRegexCheck'
import './RegexEditor.css'

export type {RegexValue} from './regexModel'

type RegexEditorProps = {
    id: string
    value: RegexValue
    onChange: (value: RegexValue) => void
    /** What the regex is matched against, in lower case: "title" or "description". */
    field?: 'title' | 'description'
    /** The Collection whose indexed episodes are the test texts. Leave out while a Collection is being added. */
    collectionId?: number | null
    disabled?: boolean
}

const PRESETS: ReadonlyArray<{value: Preset; label: string}> = [
    {value: 'contains', label: 'Contains'},
    {value: 'anyOf', label: 'Any of these'},
    {value: 'pattern', label: 'Pattern'},
    {value: 'custom', label: 'Custom regex'},
]

const WhereReg = {
    title: createSelectRegistry('RegexWhereTitle', {
        anywhere: {label: 'Anywhere in the title'},
        start: {label: 'At the start'},
        end: {label: 'At the end'},
        whole: {label: 'The whole title'},
    }),
    description: createSelectRegistry('RegexWhereDescription', {
        anywhere: {label: 'Anywhere in the description'},
        start: {label: 'At the start'},
        end: {label: 'At the end'},
        whole: {label: 'The whole description'},
    }),
}

const SpacesReg = createSelectRegistry('RegexSpaces', {
    one: {label: 'Exactly one space'},
    optional: {label: 'Optional: none or several'},
    several: {label: 'One or more spaces'},
})

const PositionReg = {
    title: createSelectRegistry('RegexPositionTitle', {start: {label: 'Start of title'}, end: {label: 'End of title'}}),
    description: createSelectRegistry('RegexPositionDescription', {
        start: {label: 'Start of description'},
        end: {label: 'End of description'},
    }),
}

const DateReg = createSelectRegistry(
    'RegexDate',
    Object.fromEntries(
        Object.entries(DATE_FORMATS).map(([key, format]) => [key, {label: `${format.label}, like ${format.example}`}]),
    ) as Record<DateFormat, {label: string}>,
)

const PALETTE: ReadonlyArray<{kind: BlockKind; help: string}> = [
    {kind: 'text', help: 'Exact words or symbols'},
    {kind: 'number', help: 'Digits, with a length'},
    {kind: 'anyText', help: 'Anything, or up to N characters'},
    {kind: 'spaces', help: 'One, optional or several'},
    {kind: 'oneOf', help: 'A list of words or symbols'},
    {kind: 'date', help: '2026-10-28, 28.10.2026 …'},
    {kind: 'optional', help: 'Blocks the text may skip'},
    {kind: 'position', help: 'Start or end of the text'},
]

type Path = number[]
type FilterMode = 'all' | 'matching' | 'notMatching'

// Small helpers ------------------------------------------------------------------

function ToggleRow({checked, onChange, label, help, disabled}: {
    checked: boolean
    onChange: (checked: boolean) => void
    label: string
    help?: ReactNode
    disabled?: boolean
}) {
    return (
        <label className="regex-editor__toggle">
            <Switch
                checked={checked}
                onChange={onChange}
                disabled={disabled}
                onColor="#0ea5e9"
                offColor="#94a3b8"
                uncheckedIcon={false}
                checkedIcon={false}
                height={18}
                width={34}
                handleDiameter={14}
            />
            <span>
                <strong>{label}</strong>
                {help ? <small>{help}</small> : null}
            </span>
        </label>
    )
}

function ChipInput({id, items, onChange, disabled, placeholder = 'Type and press Enter…'}: {
    id: string
    items: string[]
    onChange: (items: string[]) => void
    disabled?: boolean
    placeholder?: string
}) {
    const [draft, setDraft] = useState('')
    const add = () => {
        const text = draft.trim()
        if (text && !items.includes(text)) onChange([...items, text])
        setDraft('')
    }
    const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter' || event.key === ',') {
            event.preventDefault()
            add()
        } else if (event.key === 'Backspace' && !draft && items.length) {
            onChange(items.slice(0, -1))
        }
    }
    return (
        <div className={`regex-editor__chips${disabled ? ' is-disabled' : ''}`}>
            {items.map((item, index) => (
                <span key={`${item}-${index}`} className="regex-editor__chip">
                    {item}
                    <button
                        type="button"
                        aria-label={`Remove ${item}`}
                        disabled={disabled}
                        onClick={() => onChange(items.filter((_, other) => other !== index))}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                    </button>
                </span>
            ))}
            <input
                id={id}
                value={draft}
                disabled={disabled}
                placeholder={items.length ? '' : placeholder}
                onChange={(event) => setDraft(event.currentTarget.value)}
                onKeyDown={onKeyDown}
                onBlur={add}
            />
        </div>
    )
}

function NumberField({value, onChange, min = 0, placeholder, disabled}: {
    value: number | null
    onChange: (value: number | null) => void
    min?: number
    placeholder?: string
    disabled?: boolean
}) {
    return (
        <input
            className="input"
            type="number"
            min={min}
            value={value ?? ''}
            placeholder={placeholder}
            disabled={disabled}
            onChange={(event) => {
                const raw = event.currentTarget.value
                if (raw === '') return onChange(null)
                const next = event.currentTarget.valueAsNumber
                if (Number.isFinite(next)) onChange(Math.max(min, Math.round(next)))
            }}
        />
    )
}

function hasWordEdge(text: string): boolean {
    return /^[\p{L}\p{N}_]|[\p{L}\p{N}_]$/u.test(text)
}

// Block tree edits -----------------------------------------------------------------

function getAt(blocks: Block[], path: Path): Block | undefined {
    let list = blocks
    let block: Block | undefined
    for (const index of path) {
        block = list[index]
        if (!block) return undefined
        list = block.kind === 'optional' ? block.blocks : []
    }
    return block
}

function mapList(blocks: Block[], parent: Path, edit: (list: Block[]) => Block[]): Block[] {
    if (!parent.length) return edit(blocks)
    const [head, ...rest] = parent
    return blocks.map((block, index) => (
        index === head && block.kind === 'optional' ? {...block, blocks: mapList(block.blocks, rest, edit)} : block
    ))
}

function replaceAt(blocks: Block[], path: Path, next: Block): Block[] {
    return mapList(blocks, path.slice(0, -1), (list) => list.map((block, index) => (index === path[path.length - 1] ? next : block)))
}

function removeAt(blocks: Block[], path: Path): Block[] {
    return mapList(blocks, path.slice(0, -1), (list) => list.filter((_, index) => index !== path[path.length - 1]))
}

function moveAt(blocks: Block[], path: Path, offset: number): Block[] {
    const at = path[path.length - 1]
    return mapList(blocks, path.slice(0, -1), (list) => {
        const target = at + offset
        if (target < 0 || target >= list.length) return list
        const next = [...list]
        const [moved] = next.splice(at, 1)
        next.splice(target, 0, moved)
        return next
    })
}

// The regex field, with its parts coloured ----------------------------------------------

const KIND_CLASS: Record<TokenKind, string> = {
    literal: '',
    escape: 'is-escape',
    class: 'is-class',
    group: 'is-group',
    quantifier: 'is-quantifier',
    anchor: 'is-anchor',
    alternation: 'is-alternation',
    any: 'is-any',
}

function HighlightedRegex({pattern, highlight, errorAt}: {
    pattern: string
    highlight: [number, number] | null
    errorAt: number | null
}) {
    const kinds = useMemo(() => {
        const result: Array<TokenKind | null> = new Array(pattern.length).fill(null)
        for (const token of regexTokens(pattern)) {
            for (let i = token.start; i < token.end && i < pattern.length; i += 1) result[i] = token.kind
        }
        return result
    }, [pattern])
    const segments: Array<{text: string; className: string}> = []
    for (let i = 0; i < pattern.length; i += 1) {
        const classes = [
            kinds[i] ? KIND_CLASS[kinds[i]!] : '',
            highlight && i >= highlight[0] && i < highlight[1] ? 'is-hovered' : '',
            errorAt !== null && i === errorAt ? 'is-error' : '',
        ].filter(Boolean).join(' ')
        const last = segments[segments.length - 1]
        if (last && last.className === classes) last.text += pattern[i]
        else segments.push({text: pattern[i], className: classes})
    }
    const errorAtEnd = errorAt !== null && errorAt >= pattern.length
    return (
        <>
            {segments.map((segment, index) => (
                <span key={index} className={segment.className || undefined}>{segment.text}</span>
            ))}
            {errorAtEnd ? <span className="is-error"> </span> : null}
            {'\n'}
        </>
    )
}

function SampleText({sample}: {sample: RegexSample}) {
    const parts: ReactNode[] = []
    let at = 0
    sample.spans.forEach(([start, end], index) => {
        if (start > at) parts.push(sample.text.slice(at, start))
        parts.push(<mark key={index}>{sample.text.slice(start, end)}</mark>)
        at = end
    })
    if (at < sample.text.length) parts.push(sample.text.slice(at))
    return <>{parts}</>
}

const dateFormatter = new Intl.DateTimeFormat(undefined, {day: 'numeric', month: 'short', year: 'numeric'})

// The editor ---------------------------------------------------------------------------

export default function RegexEditor({id, value, onChange, field = 'title', collectionId = null, disabled = false}: RegexEditorProps) {
    const {pattern, ignoreCase} = value
    const [preset, setPreset] = useState<Preset>(() => inferPreset(pattern))
    const [wholeWordsPreference, setWholeWordsPreference] = useState(true)
    const [selected, setSelected] = useState<Path | null>(null)
    const [paletteFor, setPaletteFor] = useState<Path | null>(null)
    const [hovered, setHovered] = useState<[number, number] | null>(null)
    const [ownSamples, setOwnSamples] = useState<string[]>([])
    const [draftSample, setDraftSample] = useState('')
    const [filter, setFilter] = useState<FilterMode>('all')
    const [shown, setShown] = useState(8)

    const check = useRegexCheck({pattern, ignoreCase, samples: ownSamples, collectionId, field})
    const blocks = useMemo(() => parseBlocks(pattern), [pattern])
    const result = check.result
    const serverError = result && !result.valid ? result.error ?? 'This pattern is not valid' : null
    // Like other VODLoft fields, the expression only shows its error once you have left it.
    const [touched, setTouched] = useState(false)
    const shownError = touched ? serverError : null
    const errorAt = shownError ? result?.errorPosition ?? null : null

    const set = (next: Partial<RegexValue>) => {
        let nextPattern = next.pattern ?? pattern
        let nextIgnoreCase = next.ignoreCase ?? ignoreCase
        // A pasted (?i) becomes the switch.
        if (nextPattern.startsWith('(?i)')) {
            nextPattern = nextPattern.slice(4)
            nextIgnoreCase = true
        }
        onChange({pattern: nextPattern, ignoreCase: nextIgnoreCase})
    }

    // Contains and Any of these -----------------------------------------------------
    const shortcut = useMemo(() => {
        const parsed = blocks ?? []
        const found = shortcutOf(parsed)
        if (found) return found
        // Only Position blocks, as when the text is still empty.
        const start = parsed[0]?.kind === 'position' && parsed[0].at === 'start'
        const last = parsed[parsed.length - 1]
        const end = last?.kind === 'position' && last.at === 'end'
        const where: Where = start && end ? 'whole' : start ? 'start' : end ? 'end' : 'anywhere'
        return {where, block: null}
    }, [blocks])
    const where = shortcut.where
    const textBlock: TextBlock = shortcut.block?.kind === 'text'
        ? shortcut.block
        : {kind: 'text', text: shortcut.block?.kind === 'oneOf' ? (shortcut.block.items[0] ?? '') : '', wholeWords: wholeWordsPreference}
    const oneOfBlock: OneOfBlock = shortcut.block?.kind === 'oneOf'
        ? shortcut.block
        : {kind: 'oneOf', items: textBlock.text ? [textBlock.text] : [], wholeWords: wholeWordsPreference}
    const textWholeWords = hasWordEdge(textBlock.text) ? textBlock.wholeWords : wholeWordsPreference
    const oneOfWholeWords = oneOfBlock.items.some(hasWordEdge) ? oneOfBlock.wholeWords : wholeWordsPreference

    const setShortcut = (nextWhere: Where, block: TextBlock | OneOfBlock) => {
        set({pattern: buildRegex(shortcutBlocks(nextWhere, block))})
    }

    // Pattern ---------------------------------------------------------------------
    const patternBlocks = blocks ?? []
    const setBlocks = (next: Block[]) => set({pattern: buildRegex(next)})
    const selectedBlock = selected ? getAt(patternBlocks, selected) : undefined

    const offsets = useMemo(() => {
        // Where each top-level block's part sits in the regex, for hover highlighting.
        let at = 0
        return patternBlocks.map((block) => {
            const start = at
            at += blockRegex(block).length
            return [start, at] as [number, number]
        })
    }, [patternBlocks])

    const addBlock = (kind: BlockKind) => {
        const parent = paletteFor ?? []
        const block = newBlock(kind)
        const list = parent.length ? (getAt(patternBlocks, parent) as {blocks: Block[]}).blocks : patternBlocks
        setBlocks(mapList(patternBlocks, parent, (items) => [...items, block]))
        setSelected([...parent, list.length])
        setPaletteFor(null)
    }

    const switchTo = (next: Preset) => {
        if (presetUnavailable(next, pattern)) return
        setPreset(next)
        setSelected(null)
        setPaletteFor(null)
        set({pattern: switchPreset(next, pattern)})
    }

    // Description and explanation -------------------------------------------------------
    const noun = field
    const description = blocks ? describeBlocks(blocks, ignoreCase, noun) : null
    const explanation = useMemo(() => (preset === 'custom' ? explainRegex(pattern) : null), [preset, pattern])

    // Tester ------------------------------------------------------------------------------
    const samples = result?.valid ? result.samples : []
    const filtered = samples.filter((sample) => (
        filter === 'all' || (filter === 'matching' ? sample.matched : !sample.matched)
    ))
    const ownMatches = samples.filter((sample) => sample.own && sample.matched).length
    const timedOut = samples.some((sample) => sample.timedOut)
    const plural = `${noun}s`

    const addSample = () => {
        const text = draftSample.trim()
        if (text && !ownSamples.includes(text)) setOwnSamples([text, ...ownSamples])
        setDraftSample('')
    }

    const renderInspector = (block: Block, path: Path) => {
        const update = (next: Block) => setBlocks(replaceAt(patternBlocks, path, next))
        const fields = (() => {
            switch (block.kind) {
                case 'text':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field">
                                <span>Text</span>
                                <input
                                    className="input"
                                    value={block.text}
                                    disabled={disabled}
                                    onChange={(event) => update({...block, text: event.currentTarget.value})}
                                />
                                <small>Typed as plain text; symbols are escaped for you.</small>
                            </label>
                            <ToggleRow
                                label="Whole words only"
                                checked={block.wholeWords}
                                disabled={disabled}
                                onChange={(wholeWords) => update({...block, wholeWords})}
                            />
                        </div>
                    )
                case 'oneOf':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field" htmlFor={`${id}-block-items`}>
                                <span>Words or symbols</span>
                                <ChipInput
                                    id={`${id}-block-items`}
                                    items={block.items}
                                    disabled={disabled}
                                    onChange={(items) => update({...block, items})}
                                />
                            </label>
                            <ToggleRow
                                label="Whole words only"
                                checked={block.wholeWords}
                                disabled={disabled}
                                onChange={(wholeWords) => update({...block, wholeWords})}
                            />
                        </div>
                    )
                case 'number':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field">
                                <span>Digits, at least</span>
                                <NumberField
                                    min={1}
                                    value={block.min}
                                    disabled={disabled}
                                    onChange={(min) => update({...block, min: min ?? 1, max: block.max !== null && block.max < (min ?? 1) ? min ?? 1 : block.max})}
                                />
                            </label>
                            <label className="regex-editor__field">
                                <span>Digits, at most</span>
                                <NumberField
                                    min={block.min}
                                    value={block.max}
                                    placeholder="No limit"
                                    disabled={disabled}
                                    onChange={(max) => update({...block, max})}
                                />
                                <small>Leave empty for no limit.</small>
                            </label>
                            <ToggleRow
                                label="Optional"
                                help={`The ${noun} may leave it out`}
                                checked={block.optional}
                                disabled={disabled}
                                onChange={(optional) => update({...block, optional})}
                            />
                        </div>
                    )
                case 'anyText':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field">
                                <span>Up to this many characters</span>
                                <NumberField
                                    min={1}
                                    value={block.max}
                                    placeholder="Any length"
                                    disabled={disabled}
                                    onChange={(max) => update({...block, max})}
                                />
                                <small>Leave empty for any length, none included.</small>
                            </label>
                        </div>
                    )
                case 'spaces':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field">
                                <span>Spaces</span>
                                <SimpleSelect
                                    registry={SpacesReg}
                                    value={block.mode}
                                    isDisabled={disabled}
                                    onChange={(mode) => update({...block, mode: mode as SpacesMode})}
                                />
                            </label>
                        </div>
                    )
                case 'date':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field">
                                <span>Written as</span>
                                <SimpleSelect
                                    registry={DateReg}
                                    value={block.format}
                                    isDisabled={disabled}
                                    onChange={(format) => update({...block, format: format as DateFormat})}
                                />
                            </label>
                        </div>
                    )
                case 'position':
                    return (
                        <div className="regex-editor__grid">
                            <label className="regex-editor__field">
                                <span>Where</span>
                                <SimpleSelect
                                    registry={PositionReg[field]}
                                    value={block.at}
                                    isDisabled={disabled}
                                    onChange={(at) => update({...block, at: at as 'start' | 'end'})}
                                />
                                <small>A start block goes first and an end block last.</small>
                            </label>
                        </div>
                    )
                case 'optional':
                    return (
                        <div className="regex-editor__nested">
                            <p className="regex-editor__muted">The {noun} may have these blocks here, or skip all of them.</p>
                            {renderChips(block.blocks, path)}
                        </div>
                    )
            }
        })()
        const index = path[path.length - 1]
        return (
            <div className="regex-editor__inspector">
                <div className="regex-editor__inspector-head">
                    <strong>{blockName(block.kind)} block</strong>
                    <span className="regex-editor__inspector-actions">
                        Move
                        <button type="button" aria-label="Move left" disabled={disabled || index === 0} onClick={() => {
                            setBlocks(moveAt(patternBlocks, path, -1))
                            setSelected([...path.slice(0, -1), index - 1])
                        }}>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrow-left')}/>
                        </button>
                        <button type="button" aria-label="Move right" disabled={disabled} onClick={() => {
                            const list = path.length > 1 ? (getAt(patternBlocks, path.slice(0, -1)) as {blocks: Block[]}).blocks : patternBlocks
                            if (index + 1 >= list.length) return
                            setBlocks(moveAt(patternBlocks, path, 1))
                            setSelected([...path.slice(0, -1), index + 1])
                        }}>
                            <FontAwesomeIcon icon={faIcon('fass', 'arrow-right')}/>
                        </button>
                        ·
                        <button type="button" className="regex-editor__link" disabled={disabled} onClick={() => {
                            setBlocks(removeAt(patternBlocks, path))
                            setSelected(null)
                        }}>
                            Remove
                        </button>
                    </span>
                </div>
                {fields}
            </div>
        )
    }

    const renderChips = (list: Block[], parent: Path) => (
        <div className="regex-editor__blocks">
            {list.map((block, index) => {
                const path = [...parent, index]
                const isSelected = selected?.join('.') === path.join('.')
                return (
                    <button
                        key={index}
                        type="button"
                        className={`regex-editor__block is-${block.kind}${isSelected ? ' is-selected' : ''}`}
                        disabled={disabled}
                        onMouseEnter={() => (parent.length ? null : setHovered(offsets[index] ?? null))}
                        onMouseLeave={() => setHovered(null)}
                        onFocus={() => (parent.length ? null : setHovered(offsets[index] ?? null))}
                        onBlur={() => setHovered(null)}
                        onClick={() => {
                            setSelected(isSelected ? null : path)
                            setPaletteFor(null)
                        }}
                    >
                        <small>{blockName(block.kind)}</small>
                        <span>{blockSummary(block)}</span>
                    </button>
                )
            })}
            <button
                type="button"
                className={`regex-editor__block regex-editor__add${paletteFor?.join('.') === parent.join('.') ? ' is-selected' : ''}`}
                disabled={disabled}
                onClick={() => {
                    setPaletteFor(paletteFor?.join('.') === parent.join('.') ? null : parent)
                    setSelected(parent.length ? parent : null)
                }}
            >
                <FontAwesomeIcon icon={faIcon('fass', 'plus')}/> {parent.length ? 'Add inside' : 'Add block'}
            </button>
        </div>
    )

    return (
        <div className="regex-editor">
            <div className="regex-editor__presets" role="tablist" aria-label="How to write the pattern">
                {PRESETS.map((option) => {
                    const reason = option.value === preset ? null : presetUnavailable(option.value, pattern)
                    return (
                        <button
                            key={option.value}
                            type="button"
                            role="tab"
                            aria-selected={preset === option.value}
                            className={`regex-editor__preset${preset === option.value ? ' is-active' : ''}`}
                            disabled={disabled || Boolean(reason)}
                            title={reason ?? undefined}
                            onClick={() => switchTo(option.value)}
                        >
                            {option.label}
                            {reason ? <small>{reason}</small> : null}
                        </button>
                    )
                })}
            </div>

            {preset === 'contains' ? (
                <div className="regex-editor__section regex-editor__form">
                    <label className="regex-editor__field">
                        <span>Text</span>
                        <input
                            id={`${id}-text`}
                            className="input"
                            value={textBlock.text}
                            disabled={disabled}
                            autoFocus
                            onChange={(event) => setShortcut(where, {...textBlock, text: event.currentTarget.value, wholeWords: textWholeWords})}
                        />
                        <small>Typed as plain text. Characters like . ? ( ) are escaped for you.</small>
                    </label>
                    <label className="regex-editor__field">
                        <span>Where</span>
                        <SimpleSelect
                            registry={WhereReg[field]}
                            value={where}
                            isDisabled={disabled}
                            onChange={(next) => setShortcut(next as Where, {...textBlock, wholeWords: textWholeWords})}
                        />
                        <small>Or: at the start · at the end · the whole {noun}</small>
                    </label>
                    <div className="regex-editor__toggles">
                        <ToggleRow
                            label="Whole words only"
                            help={textBlock.text ? `“${textBlock.text}” but not “${textBlock.text}reel”` : 'Not inside a longer word'}
                            checked={textWholeWords}
                            disabled={disabled}
                            onChange={(wholeWords) => {
                                setWholeWordsPreference(wholeWords)
                                setShortcut(where, {...textBlock, wholeWords})
                            }}
                        />
                        <ToggleRow
                            label="Ignore case"
                            help="Capitals and small letters alike"
                            checked={ignoreCase}
                            disabled={disabled}
                            onChange={(next) => set({ignoreCase: next})}
                        />
                    </div>
                </div>
            ) : null}

            {preset === 'anyOf' ? (
                <div className="regex-editor__section regex-editor__form regex-editor__form--any">
                    <div className="regex-editor__field">
                        <label htmlFor={`${id}-items`}>Words or phrases</label>
                        <ChipInput
                            id={`${id}-items`}
                            items={oneOfBlock.items}
                            disabled={disabled}
                            onChange={(items) => setShortcut(where, {...oneOfBlock, items, wholeWords: oneOfWholeWords})}
                        />
                        <small>A {noun} matches when it contains at least one of them.</small>
                    </div>
                    <label className="regex-editor__field">
                        <span>Where</span>
                        <SimpleSelect
                            registry={WhereReg[field]}
                            value={where}
                            isDisabled={disabled}
                            onChange={(next) => setShortcut(next as Where, {...oneOfBlock, wholeWords: oneOfWholeWords})}
                        />
                    </label>
                    <div className="regex-editor__toggles">
                        <ToggleRow
                            label="Whole words only"
                            checked={oneOfWholeWords}
                            disabled={disabled}
                            onChange={(wholeWords) => {
                                setWholeWordsPreference(wholeWords)
                                setShortcut(where, {...oneOfBlock, wholeWords})
                            }}
                        />
                        <ToggleRow
                            label="Ignore case"
                            checked={ignoreCase}
                            disabled={disabled}
                            onChange={(next) => set({ignoreCase: next})}
                        />
                    </div>
                </div>
            ) : null}

            {preset === 'pattern' ? (
                <div className="regex-editor__section">
                    {renderChips(patternBlocks, [])}
                    {selected && selectedBlock ? renderInspector(selectedBlock, selected) : null}
                    {paletteFor ? (
                        <div className="regex-editor__palette" role="menu" aria-label="Add a block">
                            {PALETTE.filter((item) => !(paletteFor.length && item.kind === 'position')).map((item) => (
                                <button key={item.kind} type="button" role="menuitem" onClick={() => addBlock(item.kind)}>
                                    <strong>{blockName(item.kind)}</strong>
                                    <span>{item.help}</span>
                                </button>
                            ))}
                        </div>
                    ) : null}
                </div>
            ) : null}

            <div className="regex-editor__section">
                <div className="regex-editor__label-row">
                    <label htmlFor={`${id}-expression`}>Regular expression</label>
                    <span className="regex-editor__muted">
                        {preset === 'pattern' ? 'Hover a block to highlight its part' : 'Python syntax, as VODLoft uses it'}
                    </span>
                </div>
                <div className={`regex-editor__expression${shownError ? ' is-invalid' : ''}`}>
                    <div className="regex-editor__code">
                        <pre aria-hidden="true">
                            <HighlightedRegex pattern={pattern} highlight={hovered} errorAt={errorAt}/>
                        </pre>
                        <textarea
                            id={`${id}-expression`}
                            value={pattern}
                            rows={1}
                            spellCheck={false}
                            autoCapitalize="off"
                            autoCorrect="off"
                            disabled={disabled}
                            aria-invalid={Boolean(shownError)}
                            aria-describedby={`${id}-description`}
                            onChange={(event) => {
                                const next = event.currentTarget.value.replace(/\r?\n/g, '')
                                set({pattern: next})
                                setPreset(inferPreset(next.replace(/^\(\?i\)/, '')))
                                setSelected(null)
                            }}
                            onBlur={() => setTouched(true)}
                        />
                    </div>
                    <button
                        type="button"
                        className={`regex-editor__case${ignoreCase ? ' is-active' : ''}`}
                        aria-pressed={ignoreCase}
                        disabled={disabled}
                        onClick={() => set({ignoreCase: !ignoreCase})}
                    >
                        Aa Ignore case
                    </button>
                </div>
                {shownError ? (
                    <div className="regex-editor__error" role="alert">
                        <FontAwesomeIcon icon={faIcon('fass', 'circle-exclamation')}/>
                        {shownError}
                        {errorAt !== null ? ` (at character ${errorAt + 1})` : ''}
                    </div>
                ) : null}
                {!serverError && pattern ? (
                    <div id={`${id}-description`} className="regex-editor__description">
                        {description ?? (preset === 'custom' ? `The parts of this regex, one by one:` : 'Add a block to start.')}
                    </div>
                ) : null}
                {explanation && pattern && !serverError ? (
                    <>
                        <div className="regex-editor__explain">
                            {explanation.rows.map((row, index) => (
                                <Fragment key={index}>
                                    <code style={{paddingLeft: `${row.depth * 18}px`}}>{row.source}</code>
                                    <span style={{paddingLeft: `${row.depth * 18}px`}}>{row.text}</span>
                                </Fragment>
                            ))}
                        </div>
                        {explanation.unsupported.length ? (
                            <div className="regex-editor__note">
                                <FontAwesomeIcon icon={faIcon('fass', 'circle-exclamation')}/>
                                <span>
                                    This regex uses {explanation.unsupported.map((part, index) => (
                                        <Fragment key={part}>{index ? ' and ' : ''}<strong>{part}</strong></Fragment>
                                    ))}, which the Pattern builder has no block for, so it stays in Custom regex.
                                    Two separate rules are often easier to read later.
                                </span>
                            </div>
                        ) : null}
                    </>
                ) : null}
            </div>

            <div className="regex-editor__section regex-editor__tester">
                <div className="regex-editor__tester-head">
                    <strong>{collectionId !== null ? 'Test on this Collection' : `Test ${plural}`}</strong>
                    <span className="regex-editor__count">
                        {check.loading && !result ? 'Testing…' : collectionId !== null && result?.valid
                            ? <><b>{result.collectionMatches} of {result.collectionTotal}</b> {plural} match</>
                            : result?.valid && ownSamples.length
                                ? <><b>{ownMatches} of {ownSamples.length}</b> {plural} match</>
                                : null}
                    </span>
                    <div className="regex-editor__filter" role="group" aria-label="Show">
                        {([['all', 'All'], ['matching', 'Matching'], ['notMatching', 'Not matching']] as const).map(([mode, label]) => (
                            <button
                                key={mode}
                                type="button"
                                className={filter === mode ? 'is-active' : ''}
                                aria-pressed={filter === mode}
                                onClick={() => setFilter(mode)}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
                {check.error ? <div className="regex-editor__error">{check.error}</div> : null}
                {timedOut ? (
                    <div className="regex-editor__note">
                        <FontAwesomeIcon icon={faIcon('fass', 'circle-exclamation')}/>
                        <span>This pattern took too long on some {plural}. Those count as not matching.</span>
                    </div>
                ) : null}
                <ul className="regex-editor__samples">
                    {filtered.slice(0, shown).map((sample, index) => (
                        <li key={`${sample.own ? 'own' : 'ep'}-${index}-${sample.text}`} className={sample.matched ? 'is-match' : ''}>
                            <span className="regex-editor__mark" aria-label={sample.matched ? 'Matches' : 'Does not match'}>
                                {sample.matched ? <FontAwesomeIcon icon={faIcon('fass', 'check')}/> : '·'}
                            </span>
                            <span className="regex-editor__sample-text"><SampleText sample={sample}/></span>
                            {sample.own ? (
                                <button
                                    type="button"
                                    className="regex-editor__remove"
                                    aria-label="Remove this test text"
                                    onClick={() => setOwnSamples(ownSamples.filter((text) => text !== sample.text))}
                                >
                                    <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                                </button>
                            ) : sample.publishedAt ? (
                                <span className="regex-editor__date">{dateFormatter.format(new Date(sample.publishedAt))}</span>
                            ) : null}
                        </li>
                    ))}
                    {result?.valid && !filtered.length ? (
                        <li className="regex-editor__empty">
                            {samples.length ? `No ${plural} here.` : collectionId !== null
                                ? `This Collection has no indexed episodes yet. Add your own test ${plural} below.`
                                : `Add your own test ${plural} below. Once the Collection is added, its episodes are tested too.`}
                        </li>
                    ) : null}
                </ul>
                {filtered.length > shown ? (
                    <button type="button" className="regex-editor__link" onClick={() => setShown(shown + 20)}>
                        Show more ({filtered.length - shown} more)
                    </button>
                ) : null}
                <div className="regex-editor__add-sample">
                    <input
                        className="input"
                        value={draftSample}
                        placeholder={`Add a test ${noun}…`}
                        aria-label={`Add a test ${noun}`}
                        onChange={(event) => setDraftSample(event.currentTarget.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault()
                                addSample()
                            }
                        }}
                    />
                    <button type="button" className="btn btn-secondary" disabled={!draftSample.trim()} onClick={addSample}>
                        Add
                    </button>
                </div>
            </div>
        </div>
    )
}
