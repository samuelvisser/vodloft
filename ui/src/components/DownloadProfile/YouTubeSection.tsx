import {useEffect, useRef, useState} from 'react'
import {Controller, useWatch, type UseFormReturn} from 'react-hook-form'

import {useLocalMediaProfiles, useSiteOptions} from '../../lib/queries'
import {AutoSubtitlesReg} from '../../types/quality'
import ReadMore from '../../utils/ReadMore'
import SimpleSelect from '../common/SimpleSelect'
import SponsorBlockFields from './SponsorBlockFields'
import './YouTubeSection.css'

type Props = {
    form: UseFormReturn<any>
    collectionId?: number
    sourceKey?: string
    collectionUrl?: string
}

/** Choices only YouTube Collections have: auto-generated subtitles and SponsorBlock. */
export default function YouTubeSection({form, collectionId, sourceKey, collectionUrl}: Props) {
    const {control} = form
    const localMediaProfileId = useWatch({control, name: 'localMediaProfileId'}) as number | string | undefined
    const {data: site} = useSiteOptions({collectionId, sourceKey, url: collectionUrl})
    const {data: mediaProfiles} = useLocalMediaProfiles()
    const [highlight, setHighlight] = useState(false)
    const subtitlesRow = useRef<HTMLDivElement>(null)

    const mediaProfile = mediaProfiles?.find((profile) => String(profile.id) === String(localMediaProfileId))
    // A profile that is still being made in the same flow counts as storing subtitles.
    const storesSubtitles = !mediaProfile || mediaProfile.subtitleMode !== 'no_subtitles'
    const autoShown = !!site?.autoSubtitles && storesSubtitles
    const sponsorBlockShown = !!site?.sponsorblock

    // The Local Media Profile links here with #youtube-subtitles: scroll to it and briefly highlight it.
    useEffect(() => {
        if (!autoShown || window.location.hash !== '#youtube-subtitles') return
        subtitlesRow.current?.scrollIntoView({behavior: 'smooth', block: 'center'})
        setHighlight(true)
        const timer = window.setTimeout(() => setHighlight(false), 2000)
        return () => window.clearTimeout(timer)
    }, [autoShown])

    if (!autoShown && !sponsorBlockShown) return null

    return (
        <section className="youtube-section" aria-labelledby="youtube-section-heading">
            <h3 className="youtube-section-heading" id="youtube-section-heading">YouTube</h3>
            {autoShown && (
                <div className={`form-row${highlight ? ' is-highlighted' : ''}`} id="youtube-subtitles" ref={subtitlesRow}>
                    <label htmlFor="auto-subtitles">Use auto-generated subtitles</label>
                    <Controller control={control} name="autoSubtitles" render={({field}) => (
                        <SimpleSelect
                            inputId="auto-subtitles"
                            registry={AutoSubtitlesReg}
                            value={field.value ?? 'fallback'}
                            onChange={field.onChange}
                            onBlur={field.onBlur}
                            aria-describedby="auto-subtitles-help"
                        />
                    )}/>
                    <div className="help" id="auto-subtitles-help">
                        <ReadMore summary="Subtitles YouTube makes itself, in the languages of the Local Media Profile.">
                            <p>YouTube makes subtitles automatically for most videos. They follow the languages of the Local Media Profile.</p>
                            <p><strong>Only when there are no real ones</strong> uses an auto-generated subtitle for a language that has no subtitle a person made.</p>
                            <p><strong>Always</strong> also adds it next to a real one, as its own track marked auto-generated.</p>
                        </ReadMore>
                    </div>
                </div>
            )}
            {sponsorBlockShown && <SponsorBlockFields form={form}/>}
            <div className="help">Only shown for YouTube Collections.</div>
        </section>
    )
}
