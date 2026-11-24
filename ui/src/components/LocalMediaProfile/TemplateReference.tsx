import {useEffect, useId, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {faIcon} from '../../icons/faIcon'
import {createPortal} from 'react-dom'
import type {LocalMediaProfileMode} from './LocalMediaProfileForm'
import type {OutputTemplateVariable} from './outputTemplateVariables'
import {JINJA_FILTERS, TEMPLATE_FUNCTIONS, type TemplateFunction} from './outputTemplateFunctions'
import './TemplateReference.css'

/** One thing a template can use, as the reference lists it. */
export type ReferenceEntry = {
    code: string
    /** What Insert puts in the template. */
    insert: string
    description: string
    /** A few words for the row; the description shows when it is pointed at or tapped. */
    short?: string
    readMore?: OutputTemplateVariable['readMore']
}

type TabKey = 'variables' | 'indexing' | 'metadata' | 'functions' | 'jinja'

type Props = {
    mode: LocalMediaProfileMode
    variables: readonly OutputTemplateVariable[]
    builtInIndexes: readonly ReferenceEntry[]
    customIndexes: readonly ReferenceEntry[]
    metadata: readonly ReferenceEntry[]
    /** Puts text at the editor's cursor; left out when the template is read only. */
    onInsert?: (text: string) => void
    onClose: () => void
}

/** Below this width the reference is a sheet over the page instead of docked beside it. */
export const SHEET_QUERY = '(max-width: 1099px)'

const DATE_PARTS = new Set([
    'date', 'time', 'datetime', 'year', 'month', 'day', 'hour', 'minute', 'second', 'day_of_year', 'day_of_year_reversed',
])

/** The heading a variable is listed under, from the part of the media it describes. */
function variableGroup(name: string, mode: LocalMediaProfileMode): string {
    if (DATE_PARTS.has(name) || name.startsWith('episode_published_')) return 'Date and time'
    if (mode === 'video') return name.startsWith('movie_') ? 'Movie it belongs to' : 'Video'
    if (name.startsWith('collection')) return 'Collection'
    if (name.startsWith('season') || name.startsWith('album_')) return 'Season'
    if (name.startsWith('creator_') || name.startsWith('section_')) return 'Creator'
    if (name === 'artist' || name === 'album' || name.startsWith('track_')) return 'Music'
    return 'Episode'
}

function variableEntry(variable: OutputTemplateVariable): ReferenceEntry {
    return {
        code: variable.name, insert: `{{ ${variable.name} }}`,
        description: variable.description, short: variable.short, readMore: variable.readMore,
    }
}

function matches(query: string, ...texts: string[]): boolean {
    return texts.some((text) => text.toLowerCase().includes(query))
}

function EntryList({entries, onInsert}: {entries: readonly ReferenceEntry[], onInsert?: (text: string) => void}) {
    const [openCode, setOpenCode] = useState<string | null>(null)
    return (
        <ul className="template-reference__entries">
            {entries.map((entry) => {
                const open = openCode === entry.code
                const more = [
                    ...(entry.short !== undefined ? [entry.description] : []),
                    ...(entry.readMore?.paragraphs ?? []),
                ]
                return (
                    <li key={entry.code} className={open ? 'is-open' : undefined}>
                        <button
                            type="button"
                            className="template-reference__entry-head"
                            aria-expanded={open}
                            onClick={() => setOpenCode(open ? null : entry.code)}
                        >
                            <code>{entry.code}</code>
                            <span className="template-reference__entry-text">{entry.short ?? entry.description}</span>
                        </button>
                        {open && onInsert && (
                            <button type="button" className="template-reference__button template-reference__insert" onClick={() => onInsert(entry.insert)}>
                                Insert
                            </button>
                        )}
                        {open && more.length > 0 && (
                            <div className="template-reference__more">
                                {more.map((paragraph) => (
                                    <p key={paragraph} dangerouslySetInnerHTML={{__html: paragraph}}/>
                                ))}
                            </div>
                        )}
                    </li>
                )
            })}
        </ul>
    )
}

function FunctionRow({fn, open, onToggle, onInsert}: {
    fn: TemplateFunction, open: boolean, onToggle: () => void, onInsert?: (text: string) => void
}) {
    const bodyId = useId()
    return (
        <div className={`template-reference__function${open ? ' is-open' : ''}`}>
            <button type="button" className="template-reference__function-head" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
                <span className="template-reference__chevron" aria-hidden="true">{open ? '⌄' : '›'}</span>
                <code>{fn.name}</code>
                <span className="template-reference__summary">{fn.summary}</span>
            </button>
            {open && (
                <div className="template-reference__function-body" id={bodyId}>
                    <p>{fn.description}</p>
                    <code className="template-reference__usage">{fn.usage}</code>
                    {fn.arguments.length > 0 && (
                        <table className="template-reference__arguments">
                            <tbody>
                                {fn.arguments.map((argument) => (
                                    <tr key={argument.name}>
                                        <td><code>{argument.name}</code></td>
                                        <td className="template-reference__default">{argument.default}</td>
                                        <td>{argument.description}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                    {fn.example && (
                        <div className="template-reference__example">
                            <code>{fn.example.code}</code>
                            <span className="template-reference__arrow" aria-hidden="true">→</span>
                            <b className="template-reference__result">{fn.example.result}</b>
                            {onInsert && (
                                <button type="button" className="template-reference__button template-reference__insert" onClick={() => onInsert(fn.example!.code)}>
                                    Insert
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

/**
 * Every variable, Indexing value and function a template can use. It docks beside the page on a wide screen,
 * so the editor and its example output stay in view, and slides up as a sheet on a phone.
 */
export default function TemplateReference({mode, variables, builtInIndexes, customIndexes, metadata, onInsert, onClose}: Props) {
    const [tab, setTab] = useState<TabKey>('variables')
    const [query, setQuery] = useState('')
    const [openFunction, setOpenFunction] = useState<string | null>(null)
    const offersCustomIndex = mode === 'collection'
    const functions = useMemo(
        () => TEMPLATE_FUNCTIONS.filter(({collectionOnly}) => offersCustomIndex || !collectionOnly),
        [offersCustomIndex],
    )
    const variableGroups = useMemo(() => {
        const groups = new Map<string, ReferenceEntry[]>()
        for (const variable of variables) {
            const group = variableGroup(variable.name, mode)
            groups.set(group, [...(groups.get(group) ?? []), variableEntry(variable)])
        }
        return [...groups.entries()]
    }, [mode, variables])
    const jinjaEntries = useMemo<ReferenceEntry[]>(
        () => JINJA_FILTERS.map(({name, short, usage, description}) => ({
            code: name, insert: `| ${name}`, description, short,
            // Only the name shows on the row; how to call it is part of what opens.
            readMore: usage === name ? undefined : {paragraphs: [`<code>${usage}</code>`]},
        })),
        [],
    )
    const tabs: {key: TabKey, label: string, count: number}[] = [
        {key: 'variables', label: 'Variables', count: variables.length},
        ...(offersCustomIndex ? [{key: 'indexing' as const, label: 'Indexing', count: builtInIndexes.length + customIndexes.length}] : []),
        ...(metadata.length > 0 ? [{key: 'metadata' as const, label: 'Metadata', count: metadata.length}] : []),
        {key: 'functions', label: 'Functions', count: functions.length},
        {key: 'jinja', label: 'Jinja', count: jinjaEntries.length},
    ]
    const shownTab = tabs.some(({key}) => key === tab) ? tab : 'variables'

    useEffect(() => {
        const close = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose()
        }
        document.addEventListener('keydown', close)
        document.body.classList.add('has-template-reference')
        return () => {
            document.removeEventListener('keydown', close)
            document.body.classList.remove('has-template-reference')
        }
    }, [onClose])

    const search = query.trim().toLowerCase()
    const found = search ? {
        variables: variables.map(variableEntry).filter((entry) => matches(search, entry.code, entry.description, entry.short ?? '')),
        indexes: [...builtInIndexes, ...customIndexes].filter((entry) => matches(search, entry.code, entry.description, entry.short ?? '')),
        metadata: metadata.filter((entry) => matches(search, entry.code, entry.description, entry.short ?? '')),
        functions: functions.filter((fn) => matches(
            search, fn.name, fn.summary, fn.description, ...fn.arguments.map((argument) => argument.description),
        )),
        jinja: jinjaEntries.filter((entry) => matches(search, entry.code, entry.description, entry.short ?? '')),
    } : null

    const functionRows = (list: readonly TemplateFunction[]) => list.map((fn) => (
        <FunctionRow
            key={fn.name}
            fn={fn}
            open={openFunction === fn.name || (!!search && list.length === 1)}
            onToggle={() => setOpenFunction((current) => current === fn.name ? null : fn.name)}
            onInsert={onInsert}
        />
    ))

    let content: ReactNode
    if (found) {
        const sections: [string, ReactNode, number][] = [
            ['Variables', <EntryList entries={found.variables} onInsert={onInsert}/>, found.variables.length],
            ['Indexing values', <EntryList entries={found.indexes} onInsert={onInsert}/>, found.indexes.length],
            ['Metadata', <EntryList entries={found.metadata} onInsert={onInsert}/>, found.metadata.length],
            ['Functions', functionRows(found.functions), found.functions.length],
            ['Jinja filters', <EntryList entries={found.jinja} onInsert={onInsert}/>, found.jinja.length],
        ]
        const shown = sections.filter(([, , count]) => count > 0)
        content = shown.length === 0
            ? <p className="template-reference__note">Nothing matches “{query.trim()}”.</p>
            : shown.map(([title, list, count]) => (
                <section key={title} className="template-reference__group">
                    <h4>{title} · {count}</h4>
                    {list}
                </section>
            ))
    } else if (shownTab === 'variables') {
        content = (
            <>
                {variableGroups.map(([group, entries]) => (
                    <section key={group} className="template-reference__group">
                        <h4>{group}</h4>
                        <EntryList entries={entries} onInsert={onInsert}/>
                    </section>
                ))}
            </>
        )
    } else if (shownTab === 'indexing') {
        content = (
            <>
                <p className="template-reference__note">Numbers for episodes. VODLoft keeps the built-in ones for every collection.</p>
                <section className="template-reference__group">
                    <h4>Built-in</h4>
                    <EntryList entries={builtInIndexes} onInsert={onInsert}/>
                </section>
                <section className="template-reference__group">
                    <h4>Your Indexing values</h4>
                    {customIndexes.length > 0
                        ? <EntryList entries={customIndexes} onInsert={onInsert}/>
                        : <p className="template-reference__note">None yet. Add them with the Indexing values button.</p>}
                </section>
            </>
        )
    } else if (shownTab === 'metadata') {
        content = <EntryList entries={metadata} onInsert={onInsert}/>
    } else if (shownTab === 'functions') {
        content = (
            <>
                <p className="template-reference__note">
                    Put a function after a value with a <code>|</code>, such as <code>{'{{ year | int }}'}</code>.
                    Give it arguments in brackets, by position or by name.
                </p>
                {functionRows(functions)}
            </>
        )
    } else {
        content = (
            <>
                <p className="template-reference__note">Jinja's own filters work too. Put them after a value with a <code>|</code>.</p>
                <EntryList entries={jinjaEntries} onInsert={onInsert}/>
            </>
        )
    }

    // On a phone the reference is a sheet: drag its handle down to close it.
    const [dragY, setDragY] = useState(0)
    const dragStart = useRef<number | null>(null)
    const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
        if (!window.matchMedia(SHEET_QUERY).matches || (event.target as HTMLElement).closest('button')) return
        dragStart.current = event.clientY
        event.currentTarget.setPointerCapture(event.pointerId)
    }
    const drag = (event: ReactPointerEvent<HTMLDivElement>) => {
        if (dragStart.current !== null) setDragY(Math.max(0, event.clientY - dragStart.current))
    }
    const endDrag = () => {
        if (dragStart.current === null) return
        dragStart.current = null
        if (dragY > 90) onClose()
        else setDragY(0)
    }

    return createPortal(
        <>
            <div className="template-reference-backdrop" onClick={onClose} aria-hidden="true"/>
            <aside
                className={`template-reference${dragY > 0 ? ' is-dragging' : ''}`}
                aria-label="Template reference"
                style={dragY > 0 ? {transform: `translateY(${dragY}px)`} : undefined}
            >
                <div
                    className="template-reference__handle"
                    onPointerDown={startDrag}
                    onPointerMove={drag}
                    onPointerUp={endDrag}
                    onPointerCancel={endDrag}
                >
                    <div className="template-reference__grip" aria-hidden="true"/>
                    <div className="template-reference__top">
                        <h3>Template reference</h3>
                        <button type="button" className="template-reference__button" onClick={onClose}>Close</button>
                    </div>
                </div>
                <label className="template-reference__search">
                    <FontAwesomeIcon icon={faIcon('fass', 'magnifying-glass')} aria-hidden="true"/>
                    <input
                        type="search"
                        placeholder="Find a variable or function"
                        aria-label="Find a variable or function"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                    />
                </label>
                {!search && (
                    <div className="template-reference__tabs" role="tablist">
                        {tabs.map(({key, label}) => (
                            <button
                                key={key}
                                type="button"
                                role="tab"
                                aria-selected={shownTab === key}
                                className={`template-reference__tab${shownTab === key ? ' is-active' : ''}`}
                                onClick={() => setTab(key)}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                )}
                <div className="template-reference__content">{content}</div>
            </aside>
        </>,
        document.body,
    )
}
