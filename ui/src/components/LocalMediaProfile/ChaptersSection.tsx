import {useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useLocalMediaProfileSites} from '../../lib/queries'
import {profileSitesWithSetting, siteNames, type LocalMediaProfileType} from '../../types/local_media_profile'
import ReadMore from '../../utils/ReadMore'
import './SiteSettingsSection.css'

const OPTIONS = {shouldDirty: true, shouldValidate: true} as const
export const MAX_CUT_CHAPTERS = 20

/** Whether one of the profile's Sites has chapters, so the section has something to show. */
export function useOffersChapters(form: UseFormReturn<any>, mode: LocalMediaProfileType): boolean {
    const [siteKeys, includeUpcomingSites] = useWatch({control: form.control, name: ['siteKeys', 'includeUpcomingSites']}) as [string[] | null, boolean]
    const {data: sites} = useLocalMediaProfileSites()
    const withChapters = profileSitesWithSetting(sites, mode, siteKeys, includeUpcomingSites, 'chapters')
    return withChapters.sites.length > 0 || withChapters.upcoming
}

/** What the chapter choices do, in one line. */
export function chaptersSummary(keep: boolean | undefined, cut: string[] | undefined): string {
    const count = (cut ?? []).length
    return [
        keep ? 'Kept' : 'Not kept',
        count ? `${count} ${count === 1 ? 'title' : 'titles'} cut out` : '',
    ].filter(Boolean).join(' · ')
}

/** The chapters a video comes with: keep them in the file, and cut out the ones whose title matches. */
export default function ChaptersSection({form, mode}: {form: UseFormReturn<any>; mode: LocalMediaProfileType}) {
    const {control, setValue, register, formState: {errors}} = form
    const [siteKeys, includeUpcomingSites, keep, cut] = useWatch({
        control, name: ['siteKeys', 'includeUpcomingSites', 'keepChapters', 'cutChapters'],
    }) as [string[] | null, boolean, boolean | undefined, string[] | undefined]
    const {data: sites} = useLocalMediaProfileSites()
    const withChapters = siteNames(profileSitesWithSetting(sites, mode, siteKeys, includeUpcomingSites, 'chapters'))
    const patterns = cut ?? []
    const fieldErrors = errors.cutChapters as any

    return (
        <>
            <div className="form-row">
                <label htmlFor="mp-keep-chapters">Keep the video's chapters</label>
                <Switch
                    id="mp-keep-chapters"
                    checked={!!keep}
                    onChange={(value) => setValue('keepChapters', value, OPTIONS)}
                    onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                    aria-describedby="mp-keep-chapters-help"
                />
                <div className="help" id="mp-keep-chapters-help">
                    <ReadMore summary={`Write the chapters a video comes with into the file, so your player can jump between them. Applies to ${withChapters}.`}>
                        <p>Many videos split themselves into named chapters, such as “Intro” or “Q&A”. VODLoft writes those into MP4, MKV and M4A files.
                            SponsorBlock chapters bring the video's own chapters along, even when this is off.</p>
                    </ReadMore>
                </div>
            </div>

            <div className="form-row">
                <label htmlFor="mp-cut-chapters-0">Cut out chapters by title</label>
                <div className="cut-chapters">
                    {patterns.map((_pattern, index) => (
                        <div key={index} className="cut-chapters__row">
                            <input
                                id={`mp-cut-chapters-${index}`}
                                className="input cut-chapters__input"
                                placeholder="^Sponsor"
                                spellCheck={false}
                                aria-invalid={!!fieldErrors?.[index]}
                                {...register(`cutChapters.${index}`)}
                            />
                            <button
                                type="button" className="btn btn-small" aria-label="Remove this title"
                                onClick={() => setValue('cutChapters', patterns.filter((_value, other) => other !== index), OPTIONS)}
                            >
                                <FontAwesomeIcon icon={faIcon('fass', 'trash')}/>
                            </button>
                            {fieldErrors?.[index]?.message && <div className="field-error">{String(fieldErrors[index].message)}</div>}
                        </div>
                    ))}
                    {patterns.length < MAX_CUT_CHAPTERS && (
                        <button
                            type="button" className="btn btn-small cut-chapters__add"
                            onClick={() => setValue('cutChapters', [...patterns, ''], {shouldDirty: true})}
                        >
                            <FontAwesomeIcon icon={faIcon('fass', 'plus')}/> Add a title
                        </button>
                    )}
                </div>
                {fieldErrors?.message && <div className="field-error">{String(fieldErrors.message)}</div>}
                <div className="help">
                    <ReadMore summary={`A chapter whose title matches is cut out of the file. Applies to ${withChapters}.`}>
                        <p>Each line is a regular expression, matched anywhere in the chapter's title.
                            {' '}<code>^Sponsor</code> cuts chapters whose title starts with “Sponsor”; start with <code>(?i)</code> to ignore upper and lower case.
                            Cutting is final: the cut part isn't kept anywhere.</p>
                    </ReadMore>
                </div>
            </div>
        </>
    )
}
