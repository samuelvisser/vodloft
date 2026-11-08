import {useEffect, useId, useRef, useState} from 'react'
import {z} from 'zod'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../../icons/faIcon'
import './OptionsEditor.css'
import {apiUrl} from '../../../lib/api'

const OptionLineSchema = z.object({
    line: z.number(),
    text: z.string(),
    status: z.enum(['valid', 'blocked', 'has_setting', 'invalid']),
    message: z.string(),
    setting: z.string().nullable().optional(),
})
type OptionLine = z.infer<typeof OptionLineSchema>

/** Where VODLoft's own setting for an option is: a label, and a link or an element on this page. */
export type SettingLink = {label: string; href?: string; elementId?: string}

const SETTING_LABELS: Record<string, string> = {
    quality: 'Quality, on the Local Media Profile',
    subtitles: 'Subtitles, on the Local Media Profile',
    thumbnails: 'Episode thumbnail behavior, on the Local Media Profile',
    metadata: 'Media metadata behavior, on the Local Media Profile',
    file_names: 'the output template, on the Local Media Profile',
    sponsorblock: 'SponsorBlock, on the Download Profile',
    which_episodes: 'Which episodes, on the Download Profile',
    cookies: 'Cookies, per site in Settings under Sources › Sign-ins',
}

function statusIcon(status: OptionLine['status']) {
    switch (status) {
        case 'valid': return faIcon('fass', 'check')
        case 'blocked': return faIcon('fass', 'ban')
        case 'has_setting': return faIcon('fass', 'arrow-right')
        default: return faIcon('fass', 'triangle-exclamation')
    }
}

/** Checks each line with yt-dlp's own parser on the server, shortly after each change. */
function useOptionsCheck(text: string) {
    const [lines, setLines] = useState<OptionLine[]>([])
    const [error, setError] = useState('')
    useEffect(() => {
        const controller = new AbortController()
        const timer = window.setTimeout(async () => {
            try {
                const response = await fetch(`${apiUrl()}/sources/ytdlp-options/check`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    signal: controller.signal,
                    body: JSON.stringify({text}),
                })
                if (!response.ok) throw new Error(`The options could not be checked (${response.status})`)
                setLines(z.array(OptionLineSchema).parse(await response.json()))
                setError('')
            } catch (caught) {
                if (controller.signal.aborted) return
                setError(caught instanceof Error ? caught.message : String(caught))
            }
        }, 300)
        return () => {
            controller.abort()
            window.clearTimeout(timer)
        }
    }, [text])
    return {lines, error}
}

type Props = {
    value: string
    onChange: (value: string) => void
    onBlur?: () => void
    id?: string
    invalid?: boolean
    describedBy?: string
    /** Where the settings VODLoft already has live, for the "already has a setting" lines. */
    settingLinks?: Partial<Record<string, SettingLink>>
    placeholder?: string
}

/** Your own yt-dlp options, one or more per line, each checked as you type. */
export default function OptionsEditor({value, onChange, onBlur, id, invalid, describedBy, settingLinks = {}, placeholder}: Props) {
    const fallbackId = useId()
    const inputId = id ?? fallbackId
    const {lines, error} = useOptionsCheck(value)
    const gutter = useRef<HTMLDivElement>(null)
    const byLine = new Map(lines.map((line) => [line.line, line]))
    const count = Math.max(1, value.split('\n').length)
    const problems = lines.filter((line) => line.status !== 'valid')

    const goTo = (link: SettingLink) => {
        if (!link.elementId) return
        const element = document.getElementById(link.elementId)
        element?.scrollIntoView({behavior: 'smooth', block: 'center'})
    }

    return (
        <div className={`options-editor${invalid ? ' is-invalid' : ''}`}>
            <div className="options-editor__code">
                <div className="options-editor__gutter" ref={gutter} aria-hidden="true">
                    {Array.from({length: count}, (_, index) => {
                        const line = byLine.get(index + 1)
                        return (
                            <span key={index} className={`options-editor__number${line ? ` is-${line.status}` : ''}`}>
                                {line && line.status !== 'valid' ? <FontAwesomeIcon icon={statusIcon(line.status)}/> : index + 1}
                            </span>
                        )
                    })}
                </div>
                <textarea
                    id={inputId}
                    className="options-editor__input"
                    value={value}
                    rows={Math.min(Math.max(count, 3), 14)}
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    autoComplete="off"
                    wrap="off"
                    placeholder={placeholder ?? '--concurrent-fragments 4\n--extractor-args "youtube:player_client=web"'}
                    aria-invalid={invalid || problems.length > 0}
                    aria-describedby={describedBy}
                    onChange={(event) => onChange(event.currentTarget.value)}
                    onBlur={onBlur}
                    onScroll={(event) => {
                        if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop
                    }}
                />
            </div>
            {error && <div className="options-editor__error">{error}</div>}
            {lines.length > 0 && (
                <ul className="options-editor__results" aria-live="polite">
                    {lines.map((line) => {
                        const link = line.setting ? settingLinks[line.setting] ?? {label: SETTING_LABELS[line.setting] ?? line.setting} : null
                        return (
                            <li key={line.line} className={`options-editor__result is-${line.status}`}>
                                <FontAwesomeIcon className="options-editor__result-icon" icon={statusIcon(line.status)}/>
                                <span>
                                    <span className="options-editor__result-line">Line {line.line}</span>{' '}
                                    {line.status === 'valid' && <>passed to yt-dlp</>}
                                    {line.status === 'blocked' && <><b>Blocked.</b> {line.message}</>}
                                    {line.status === 'invalid' && <><b>yt-dlp refuses this.</b> {line.message}</>}
                                    {line.status === 'has_setting' && link && <>
                                        {line.message}:{' '}
                                        {link.href
                                            ? <a href={link.href}>{link.label}</a>
                                            : link.elementId
                                                ? <button type="button" className="btn-link options-editor__link" onClick={() => goTo(link)}>{link.label}</button>
                                                : link.label}
                                    </>}
                                </span>
                            </li>
                        )
                    })}
                </ul>
            )}
        </div>
    )
}
