import {useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import Select from 'react-select'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useLocalMediaProfileSites} from '../../lib/queries'
import {profileSitesOffering, profileSitesWithSetting, siteNames, type LocalMediaProfileType} from '../../types/local_media_profile'
import {AutoSubtitlesReg, LANGUAGES, SubtitleLanguageModeReg, languageName} from '../../types/quality'
import {createSelectRegistry} from '../../utils/selectRegistry'
import ReadMore from '../../utils/ReadMore'
import SimpleSelect from '../common/SimpleSelect'
import './SubtitleFields.css'

const WhereReg = createSelectRegistry('SubtitleWhere', {
    no_subtitles: {label: 'Not at all'},
    embed: {label: 'Inside the media', help: 'As tracks you can pick in your player, in MP4 and MKV files.'},
    sidecar: {label: 'Beside the media', help: 'As SRT files next to the media, such as Episode.en.srt.'},
    embed_and_sidecar: {label: 'Inside and beside the media', help: 'As tracks in MP4 and MKV files, and as SRT files next to the media.'},
})

const OPTIONS = {shouldDirty: true, shouldValidate: true} as const

function joinAnd(items: string[], joiner = 'and'): string {
    return items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} ${joiner} ${items[items.length - 1]}`
}

function modeHelp(mode: string, codes: string[], sidecars: boolean): string | undefined {
    if (mode === 'site') return SubtitleLanguageModeReg.getHelp('site')
    if (!codes.length) return undefined
    if (mode === 'listed') {
        // Jellyfin and Emby pick the file marked .default.
        const files = codes.map((code, index) => `Episode.${code}${sidecars && index === 0 ? '.default' : ''}.srt`)
        return `${joinAnd(files)}, when the site has them.`
    }
    const names = codes.map(languageName)
    return `One subtitle file per episode: ${names.map((name, i) => i === 0 ? `${name} if there is one` : `otherwise ${name}`).join(', ')}.`
}

type Props = {
    form: UseFormReturn<any>
    mode: LocalMediaProfileType
    onSubtitleModeChange?: (value: any) => void
}

/** Subtitles: where they are stored, which languages in which order, and what to do with several. */
export default function SubtitleFields({form, mode: profileType, onSubtitleModeChange}: Props) {
    const {control, setValue, formState: {errors}} = form
    const [subtitleMode, languages, languageMode, siteKeys, includeUpcomingSites, autoSubtitles] = useWatch({
        control, name: ['subtitleMode', 'subtitleLanguages', 'subtitleLanguageMode', 'siteKeys', 'includeUpcomingSites', 'autoSubtitles'],
    }) as [string, string[] | undefined, string, string[] | null, boolean, string | undefined]
    const {data: sites} = useLocalMediaProfileSites()
    const subtitleSites = profileSitesOffering(sites, profileType, siteKeys, includeUpcomingSites, (options) => options.subtitles)
    const autoSubtitleSites = profileSitesWithSetting(sites, profileType, siteKeys, includeUpcomingSites, 'autoSubtitles')
    const offersAutoSubtitles = autoSubtitleSites.sites.length > 0 || autoSubtitleSites.upcoming
    const list = languages ?? []
    const [dragging, setDragging] = useState<number | null>(null)
    const stores = subtitleMode && subtitleMode !== 'no_subtitles'
    const everyLanguage = languageMode === 'site'
    const help = modeHelp(languageMode, list, subtitleMode === 'sidecar' || subtitleMode === 'embed_and_sidecar')
    const whereHelp = WhereReg.values.includes(subtitleMode as any) ? WhereReg.getHelp(subtitleMode as any) : undefined

    const setLanguages = (next: string[]) => setValue('subtitleLanguages', next, OPTIONS)
    const move = (from: number, to: number) => {
        if (to < 0 || to >= list.length || from === to) return
        const next = [...list]
        const [item] = next.splice(from, 1)
        next.splice(to, 0, item)
        setLanguages(next)
    }
    const addable = Object.entries(LANGUAGES).filter(([code]) => !list.includes(code)).map(([value, label]) => ({value, label}))
    // None of the profile's Sites has subtitles, so there is nothing to choose.
    if (sites && !subtitleSites.sites.length && !subtitleSites.upcoming) return null

    return (
        <div className="subtitle-fields" id="subtitle-fields">
            <div className="form-row">
                <label htmlFor="subtitle-mode">Subtitles</label>
                <SimpleSelect
                    inputId="subtitle-mode"
                    registry={WhereReg}
                    value={subtitleMode}
                    onChange={(value) => {
                        onSubtitleModeChange?.(value)
                        setValue('subtitleMode', value, OPTIONS)
                    }}
                    aria-invalid={!!errors.subtitleMode}
                />
                {errors.subtitleMode && <div className="error" role="alert">{String(errors.subtitleMode.message)}</div>}
                {whereHelp && <div className="help">{whereHelp}</div>}
            </div>

            {stores && (
                <div className="form-row">
                    <label htmlFor="subtitle-language-mode">When several languages are available</label>
                    <SimpleSelect
                        inputId="subtitle-language-mode"
                        registry={SubtitleLanguageModeReg}
                        value={languageMode}
                        onChange={(value) => setValue('subtitleLanguageMode', value, OPTIONS)}
                    />
                    {help && <div className="help">{help}</div>}
                </div>
            )}

            {stores && (
                <div className="form-row">
                    <label htmlFor="subtitle-language-add" id="subtitle-languages-label">{everyLanguage ? 'Default track language' : 'Subtitle languages'}</label>
                    <ol className="subtitle-languages" aria-labelledby="subtitle-languages-label">
                        {list.map((code, index) => (
                            <li
                                key={code}
                                className={`subtitle-language${dragging === index ? ' is-dragging' : ''}${everyLanguage && index > 0 ? ' is-ignored' : ''}`}
                                draggable
                                onDragStart={(event) => {
                                    setDragging(index)
                                    event.dataTransfer.effectAllowed = 'move'
                                }}
                                onDragOver={(event) => {
                                    event.preventDefault()
                                    if (dragging !== null && dragging !== index) {
                                        move(dragging, index)
                                        setDragging(index)
                                    }
                                }}
                                onDragEnd={() => setDragging(null)}
                            >
                                <span className="subtitle-language__grip" aria-hidden="true">
                                    <FontAwesomeIcon icon={faIcon('fass', 'grip-vertical')}/>
                                </span>
                                <span className="subtitle-language__number" aria-hidden="true">{index + 1}</span>
                                <span className="subtitle-language__name">{languageName(code)}</span>
                                <span className="subtitle-language__actions">
                                    <button type="button" aria-label={`Move ${languageName(code)} up`} disabled={index === 0} onClick={() => move(index, index - 1)}>
                                        <FontAwesomeIcon icon={faIcon('fass', 'chevron-up')}/>
                                    </button>
                                    <button type="button" aria-label={`Move ${languageName(code)} down`} disabled={index === list.length - 1} onClick={() => move(index, index + 1)}>
                                        <FontAwesomeIcon icon={faIcon('fass', 'chevron-down')}/>
                                    </button>
                                    <button type="button" aria-label={`Remove ${languageName(code)}`} onClick={() => setLanguages(list.filter((item) => item !== code))}>
                                        <FontAwesomeIcon icon={faIcon('fass', 'xmark')}/>
                                    </button>
                                </span>
                            </li>
                        ))}
                        <li className="subtitle-language subtitle-language--add">
                            <Select
                                inputId="subtitle-language-add"
                                classNamePrefix="select"
                                className="subtitle-language__add"
                                placeholder="+ Add a language…"
                                options={addable}
                                value={null}
                                onChange={(option) => option && setLanguages([...list, option.value])}
                                isSearchable
                                aria-label="Add a language"
                            />
                        </li>
                    </ol>
                    {errors.subtitleLanguages && (
                        <div className="error" role="alert">
                            {String((errors.subtitleLanguages as any).message ?? 'Check the languages')}
                        </div>
                    )}
                    <div className="help">
                        {everyLanguage
                            ? 'Every language is downloaded. The first one here becomes the default track when an episode has it, or leave the list empty for no default. The grayed-out languages are kept for the other choices.'
                            : 'In order of preference. The first becomes the default track. Drag or use the arrows to reorder.'}
                    </div>
                </div>
            )}

            <div className="help">
                <ReadMore summary={`Subtitles from ${siteNames(subtitleSites)}. Subtitles saved beside the media are always SRT.`}>
                    <p>Embedding needs an MP4, MKV or HLS video, not audio. An HLS bundle keeps embedded subtitles inside it as WebVTT, so players that stream it can show them; subtitles beside it stay separate SRT files the bundle does not need.</p>
                </ReadMore>
            </div>

            {stores && offersAutoSubtitles && (
                <div className="form-row">
                    <label htmlFor="subtitle-auto">Use auto-generated subtitles</label>
                    <SimpleSelect
                        inputId="subtitle-auto"
                        registry={AutoSubtitlesReg}
                        value={autoSubtitles ?? 'fallback'}
                        onChange={(value) => setValue('autoSubtitles', value, OPTIONS)}
                        aria-describedby="subtitle-auto-help"
                    />
                    <div className="help" id="subtitle-auto-help">
                        <ReadMore summary={`Subtitles the site makes itself, in the languages above. Applies to ${siteNames(autoSubtitleSites)}.`}>
                            <p><strong>Only when there are no real ones</strong> uses an auto-generated subtitle for a language that has no subtitle a person made.</p>
                            <p><strong>Always</strong> also adds it next to a real one, as its own track marked auto-generated.</p>
                        </ReadMore>
                    </div>
                </div>
            )}
        </div>
    )
}
