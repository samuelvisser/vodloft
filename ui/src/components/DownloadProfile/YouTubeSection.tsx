import {useEffect, useRef, useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useLocalMediaProfiles, useSiteOptions} from '../../lib/queries'
import {AutoSubtitlesReg} from '../../types/quality'
import ReadMore from '../../utils/ReadMore'
import SponsorBlockLine from './SponsorBlockLine'
import './WhichEpisodes.css'
import '../LocalMediaProfile/SubtitleLines.css'

const SENTENCE_ENDS: Record<string, string> = {
    never: ' never',
    fallback: ' only when there are no real ones',
    always: ' always, next to the real ones',
}

type Props = {
    form: UseFormReturn<any>
    collectionId?: number
    sourceKey?: string
    collectionUrl?: string
}

/** Choices only YouTube Collections have: auto-generated subtitles and SponsorBlock. */
export default function YouTubeSection({form, collectionId, sourceKey, collectionUrl}: Props) {
    const {control, getValues, setValue} = form
    const [autoSubtitles, localMediaProfileId] = useWatch({control, name: ['autoSubtitles', 'localMediaProfileId']}) as [string, number | string | undefined]
    const {data: site} = useSiteOptions({collectionId, sourceKey, url: collectionUrl})
    const {data: mediaProfiles} = useLocalMediaProfiles()
    const [open, setOpen] = useState(false)
    const [highlight, setHighlight] = useState(false)
    const before = useRef<string | null>(null)
    const section = useRef<HTMLDivElement>(null)

    const mediaProfile = mediaProfiles?.find((profile) => String(profile.id) === String(localMediaProfileId))
    // A profile that is still being made in the same flow counts as storing subtitles.
    const storesSubtitles = !mediaProfile || mediaProfile.subtitleMode !== 'no_subtitles'
    const autoShown = !!site?.autoSubtitles && storesSubtitles
    const sponsorBlockShown = !!site?.sponsorblock
    const shown = autoShown || sponsorBlockShown

    // The Local Media Profile links here with #youtube-subtitles: scroll to it and briefly highlight it.
    useEffect(() => {
        if (!autoShown || window.location.hash !== '#youtube-subtitles') return
        section.current?.scrollIntoView({behavior: 'smooth', block: 'center'})
        setHighlight(true)
        const timer = window.setTimeout(() => setHighlight(false), 2000)
        return () => window.clearTimeout(timer)
    }, [autoShown])

    if (!shown) return null
    const choice = autoSubtitles ?? 'fallback'
    const toggle = () => {
        if (open) {
            if (before.current !== null) setValue('autoSubtitles', before.current, {shouldDirty: true})
            setOpen(false)
        } else {
            before.current = getValues('autoSubtitles')
            setOpen(true)
        }
    }

    return (
        <div className="form-row which-episodes" id="youtube-subtitles" ref={section}>
            <span style={{fontWeight: 600}}>YouTube</span>
            <ul className="which-episodes-lines">
                {autoShown && (
                <li className={`which-episodes-line${open ? ' is-open' : ''}${highlight ? ' is-highlighted' : ''}`}>
                    <div className="which-episodes-sentence" onClick={(event) => {
                        if (!(event.target as HTMLElement).closest('button, input')) toggle()
                    }}>
                        <span className="which-episodes-text">
                            Use <b>auto-generated subtitles</b>{SENTENCE_ENDS[choice] ?? ''}
                        </span>
                        <button type="button" className={`which-episodes-icon${open ? ' is-active' : ''}`} aria-label="Edit auto-generated subtitles" aria-expanded={open} onClick={toggle}>
                            <FontAwesomeIcon icon={faIcon('fass', 'pen')}/>
                        </button>
                    </div>
                    {open && (
                        <div className="which-episodes-editor">
                            <div style={{display: 'grid', gap: 8}}>
                                {AutoSubtitlesReg.values.map((value) => (
                                    <label key={value} style={{display: 'flex', gap: 8, alignItems: 'flex-start'}}>
                                        <input type="radio" name="auto-subtitles" checked={choice === value}
                                               onChange={() => setValue('autoSubtitles', value, {shouldDirty: true})}/>
                                        <span style={{display: 'grid'}}>
                                            <strong>{AutoSubtitlesReg.getLabel(value)}</strong>
                                            {AutoSubtitlesReg.getHelp(value) && <small className="which-episodes-muted">{AutoSubtitlesReg.getHelp(value)}</small>}
                                        </span>
                                    </label>
                                ))}
                            </div>
                            <div className="which-episodes-editor-actions">
                                <button type="button" className="btn" onClick={toggle}>Cancel</button>
                                <button type="button" className="btn btn-primary" onClick={() => setOpen(false)}>Done</button>
                            </div>
                        </div>
                    )}
                </li>
                )}
                {sponsorBlockShown && <SponsorBlockLine form={form}/>}
            </ul>
            <div className="help">
                <ReadMore summary="Only shown for YouTube Collections.">
                    {autoShown && <>
                        <p>YouTube makes subtitles automatically for most videos. They follow the languages of the Local Media Profile.</p>
                        <p><strong>Only when there are no real ones</strong> uses an auto-generated subtitle for a language that has no subtitle a person made.</p>
                        <p><strong>Always</strong> also adds it next to a real one, as its own track marked auto-generated.</p>
                    </>}
                    <p>SponsorBlock is a community database of parts of YouTube videos, such as sponsor reads and “like and subscribe” reminders.
                        A part becomes a chapter your player can skip, or is cut out of the file. Most parts are submitted in the days after a video comes out,
                        so a download right after upload may have few of them. The episode page shows what was found.</p>
                </ReadMore>
            </div>
        </div>
    )
}
