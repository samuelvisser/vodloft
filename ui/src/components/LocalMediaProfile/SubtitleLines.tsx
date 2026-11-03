import {Fragment, useRef, useState, type ReactNode} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import {Link} from 'react-router-dom'
import Select from 'react-select'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useAutoSubtitleUses} from '../../lib/queries'
import {AutoSubtitlesReg, LANGUAGES, SubtitleLanguageModeReg, languageName} from '../../types/quality'
import {createSelectRegistry} from '../../utils/selectRegistry'
import ReadMore from '../../utils/ReadMore'
import type {Part} from '../DownloadProfile/whichEpisodesText'
import '../DownloadProfile/WhichEpisodes.css'
import './SubtitleLines.css'

const WHERE_WORDS: Record<string, string> = {
    no_subtitles: 'not at all',
    embed: 'inside the media',
    sidecar: 'beside the media',
    embed_and_sidecar: 'inside and beside the media',
}
const WhereReg = createSelectRegistry('SubtitleWhere', {
    no_subtitles: {label: 'Not at all'},
    embed: {label: 'Inside the media', help: 'As tracks you can pick in your player, in MP4 and MKV files.'},
    sidecar: {label: 'Beside the media', help: 'As SRT files next to the media, such as Episode.en.srt.'},
    embed_and_sidecar: {label: 'Both'},
})

const LINE_FIELDS: Record<string, string[]> = {
    where: ['subtitleMode'],
    languages: ['subtitleLanguages', 'subtitleLanguageMode'],
}

function Sentence({parts}: {parts: Part[]}) {
    return <>{parts.map((part, index) => part.strong ? <b key={index}>{part.text}</b> : <Fragment key={index}>{part.text}</Fragment>)}</>
}

function strongList(items: string[], joiner = 'and'): Part[] {
    return items.flatMap((item, index) => [
        ...(index === 0 ? [] : [{text: index === items.length - 1 ? ` ${joiner} ` : ', '}]),
        {text: item, strong: true},
    ])
}

export function languagesSentence(languages: string[], mode: string): Part[] {
    if (mode === 'site' || !languages.length) return [{text: 'in '}, {text: 'every language the site offers', strong: true}]
    const names = languages.map(languageName)
    if (mode === 'first') return [{text: 'in '}, ...strongList(names, 'or'), {text: ', only the first one available'}]
    return [{text: 'in '}, ...strongList(names), {text: languages.length === 1 ? ', when the site has it' : ', every one the site has'}]
}

function joinAnd(items: string[], joiner = 'and'): string {
    return items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} ${joiner} ${items[items.length - 1]}`
}

function modeHelp(mode: string, codes: string[]): string | undefined {
    if (mode === 'site') return SubtitleLanguageModeReg.getHelp('site')
    if (!codes.length) return undefined
    if (mode === 'listed') return `${joinAnd(codes.map((code) => `Episode.${code}.srt`))}, when the site has them.`
    const names = codes.map(languageName)
    return `One subtitle file per episode: ${names.map((name, i) => i === 0 ? `${name} if there is one` : `otherwise ${name}`).join(', ')}.`
}

type Props = {
    form: UseFormReturn<any>
    onSubtitleModeChange?: (value: any) => void
}

/** Subtitles as sentences: where they are stored, and in which languages. */
export default function SubtitleLines({form, onSubtitleModeChange}: Props) {
    const {control, getValues, setValue, trigger, formState: {errors}} = form
    const [subtitleMode, languages, languageMode, profileId] = useWatch({
        control, name: ['subtitleMode', 'subtitleLanguages', 'subtitleLanguageMode', 'id'],
    }) as [string, string[] | undefined, string, number | undefined]
    const list = languages ?? []
    const [open, setOpen] = useState<string | null>(null)
    const [autoOpen, setAutoOpen] = useState(false)
    const [dragging, setDragging] = useState<number | null>(null)
    const snapshot = useRef<unknown[] | null>(null)
    const stores = subtitleMode && subtitleMode !== 'no_subtitles'
    const {data: uses} = useAutoSubtitleUses(stores ? profileId : undefined)

    const openLine = (key: string) => {
        snapshot.current = LINE_FIELDS[key].map((name) => getValues(name))
        setOpen(key)
    }
    const cancel = () => {
        if (open && snapshot.current) {
            LINE_FIELDS[open].forEach((name, index) => setValue(name, snapshot.current![index], {shouldDirty: true, shouldValidate: true}))
        }
        snapshot.current = null
        setOpen(null)
    }
    const done = async () => {
        if (open && await trigger(LINE_FIELDS[open])) {
            snapshot.current = null
            setOpen(null)
        }
    }
    const toggle = (key: string) => open === key ? cancel() : openLine(key)
    const setLanguages = (next: string[]) => setValue('subtitleLanguages', next, {shouldDirty: true, shouldValidate: true})
    const move = (from: number, to: number) => {
        if (to < 0 || to >= list.length || from === to) return
        const next = [...list]
        const [item] = next.splice(from, 1)
        next.splice(to, 0, item)
        setLanguages(next)
    }
    const addable = Object.entries(LANGUAGES).filter(([code]) => !list.includes(code)).map(([value, label]) => ({value, label}))

    const line = (key: string, parts: Part[], editor: ReactNode) => {
        const isOpen = open === key
        return (
            <li className={`which-episodes-line${isOpen ? ' is-open' : ''}`}>
                <div className="which-episodes-sentence" onClick={(event) => {
                    if (!(event.target as HTMLElement).closest('button, a, input, [class*="select__"]')) toggle(key)
                }}>
                    <span className="which-episodes-text"><Sentence parts={parts}/></span>
                    <button
                        type="button" className={`which-episodes-icon${isOpen ? ' is-active' : ''}`}
                        aria-label={`Edit: ${parts.map((part) => part.text).join('')}`} aria-expanded={isOpen}
                        onClick={() => toggle(key)}
                    >
                        <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                    </button>
                </div>
                {isOpen && (
                    <div className="which-episodes-editor">
                        {editor}
                        <div className="which-episodes-editor-actions">
                            <button type="button" className="btn" onClick={cancel}>Cancel</button>
                            <button type="button" className="btn btn-primary" onClick={done}>Done</button>
                        </div>
                    </div>
                )}
            </li>
        )
    }

    // The auto-generated pointer, grouped by choice: "for Kurzgesagt, for Veritasium only when there are no real ones, and not for MKBHD".
    const useName = (use: {collectionTitle: string; episodeTypes: string[]}) =>
        use.episodeTypes.length ? `${use.collectionTitle} (${use.episodeTypes.join(' and ')})` : use.collectionTitle
    const groupNames = (choice: string) => {
        const all = (uses ?? []).filter((use) => use.autoSubtitles === choice).map(useName)
        return all.length > 4 ? [...all.slice(0, 3), `${all.length - 3} more`] : all
    }
    const autoParts: Part[] = [{text: 'Auto-generated subtitles', strong: true}, {text: ' are downloaded'}]
    const groups: Part[][] = [
        groupNames('always').length ? [{text: 'for '}, ...strongList(groupNames('always'))] : [],
        groupNames('fallback').length ? [{text: 'for '}, ...strongList(groupNames('fallback')), {text: ' only when there are no real ones'}] : [],
        groupNames('never').length ? [{text: 'not for '}, ...strongList(groupNames('never'), 'or')] : [],
    ].filter((group) => group.length)
    groups.forEach((group, index) => {
        autoParts.push({text: index === 0 ? ' ' : index === groups.length - 1 ? ', and ' : ', '}, ...group)
    })

    return (
        <div className="form-row which-episodes subtitle-lines">
            <span className="subtitle-lines__label">Subtitles</span>
            <ul className="which-episodes-lines">
                {line('where', [{text: 'Store subtitles '}, {text: WHERE_WORDS[subtitleMode] ?? subtitleMode, strong: true}], (
                    <div className="quality-radios" role="radiogroup" aria-label="Where subtitles are stored">
                        {WhereReg.values.map((value) => (
                            <label key={value} className="quality-radio">
                                <input type="radio" name="subtitle-where" checked={subtitleMode === value} onChange={() => {
                                    onSubtitleModeChange?.(value)
                                    setValue('subtitleMode', value, {shouldDirty: true, shouldValidate: true})
                                }}/>
                                <span>
                                    <strong>{WhereReg.getLabel(value)}</strong>
                                    {WhereReg.getHelp(value) && <small>{WhereReg.getHelp(value)}</small>}
                                </span>
                            </label>
                        ))}
                    </div>
                ))}
                {stores && line('languages', languagesSentence(list, languageMode), (
                    <>
                        <strong>Languages, in order of preference</strong>
                        <div className="subtitle-chips">
                            {list.map((code, index) => (
                                <span
                                    key={code} className={`subtitle-chip${dragging === index ? ' is-dragging' : ''}`} draggable
                                    onDragStart={() => setDragging(index)}
                                    onDragOver={(event) => {
                                        event.preventDefault()
                                        if (dragging !== null && dragging !== index) {
                                            move(dragging, index)
                                            setDragging(index)
                                        }
                                    }}
                                    onDragEnd={() => setDragging(null)}
                                >
                                    <FontAwesomeIcon className="subtitle-chip__grip" icon={faIcon('fass', 'grip-vertical')}/>
                                    <span className="subtitle-chip__number">{index + 1}</span>
                                    {languageName(code)}
                                    {index > 0 && (
                                        <button type="button" aria-label={`Move ${languageName(code)} earlier`} onClick={() => move(index, index - 1)}>
                                            <FontAwesomeIcon icon={faIcon('fass', 'chevron-left')}/>
                                        </button>
                                    )}
                                    <button type="button" aria-label={`Remove ${languageName(code)}`} onClick={() => setLanguages(list.filter((item) => item !== code))}>
                                        <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                                    </button>
                                </span>
                            ))}
                            <div className="subtitle-chips__add">
                                <Select
                                    inputId="subtitle-language-add"
                                    classNamePrefix="select"
                                    placeholder="+ Add a language…"
                                    options={addable}
                                    value={null}
                                    onChange={(option) => option && setLanguages([...list, option.value])}
                                    isSearchable
                                    aria-label="Add a language"
                                />
                            </div>
                        </div>
                        <div className="help">Drag to reorder. The first language becomes the default subtitle track in players that read it.</div>
                        {errors.subtitleLanguages && <div className="error" role="alert">{String((errors.subtitleLanguages as any).message ?? 'Check the languages')}</div>}
                        <div className="quality-radios" role="radiogroup" aria-label="Which languages">
                            {SubtitleLanguageModeReg.values.map((value) => (
                                <label key={value} className="quality-radio">
                                    <input type="radio" name="subtitle-language-mode" checked={languageMode === value}
                                           onChange={() => setValue('subtitleLanguageMode', value, {shouldDirty: true, shouldValidate: true})}/>
                                    <span>
                                        <strong>{SubtitleLanguageModeReg.getLabel(value)}</strong>
                                        {modeHelp(value, list) && <small>{modeHelp(value, list)}</small>}
                                    </span>
                                </label>
                            ))}
                        </div>
                    </>
                ))}
                {stores && uses && uses.length > 0 && (
                    <li className={`which-episodes-line${autoOpen ? ' is-open' : ''}`}>
                        <div className="which-episodes-sentence" onClick={() => setAutoOpen((value) => !value)}>
                            <FontAwesomeIcon className="subtitle-lines__fold" icon={faIcon('fass', autoOpen ? 'chevron-down' : 'chevron-right')}/>
                            <span className="which-episodes-text"><Sentence parts={autoParts}/></span>
                        </div>
                        {autoOpen && (
                            <div className="subtitle-uses-wrap">
                                <div className="subtitle-uses">
                                    {uses.map((use) => (
                                        <div key={use.downloadProfileId} className="subtitle-use">
                                            <strong>{use.collectionTitle}</strong>
                                            <span className="which-episodes-muted">{use.episodeTypes.length ? use.episodeTypes.join(' and ') : 'YouTube'}</span>
                                            <span className={`subtitle-use__choice is-${use.autoSubtitles}`}>{AutoSubtitlesReg.getLabelLoose(use.autoSubtitles)}</span>
                                            <Link to={`/edit-download-profile/${use.downloadProfileId}#youtube-subtitles`}>
                                                Edit <FontAwesomeIcon icon={faIcon('fass', 'arrow-up-right-from-square')}/>
                                            </Link>
                                        </div>
                                    ))}
                                </div>
                                <div className="help">Set on each YouTube Download Profile that uses this Local Media Profile. Opening one scrolls to its YouTube section.</div>
                            </div>
                        )}
                    </li>
                )}
            </ul>
            <div className="help">
                <ReadMore summary="Applies to every Source. Subtitles saved beside the media are always SRT.">
                    <p>Subtitles come from The Daily Wire and from every site yt-dlp downloads from, such as YouTube. NPO Start has no subtitles yet.</p>
                    <p>Auto-generated subtitles only exist on YouTube, so that choice is on each Download Profile of a YouTube Collection.</p>
                    <p>Embedding needs an MP4 or MKV video, not an HLS bundle or audio.</p>
                </ReadMore>
            </div>
        </div>
    )
}
