import {useState} from 'react'
import {useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'

import {faIcon} from '../../icons/faIcon'
import {useLocalMediaProfileSites} from '../../lib/queries'
import {profileSitesWithSetting, siteNames, type LocalMediaProfileType} from '../../types/local_media_profile'
import type {SponsorBlockSegments} from '../../types/schemas/local_media_profile_base'
import {SPONSORBLOCK_GROUPS, SponsorBlockCategoryReg} from '../../types/sponsorblock'
import ReadMore from '../../utils/ReadMore'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {SponsorBlockSegmentsGrid} from './SponsorBlockFields'
import './SiteSettingsSection.css'

const CATEGORIES = SPONSORBLOCK_GROUPS.flatMap((group) => group.categories)

function joinAnd(items: string[]): string {
    return items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** What the segment choices do, in a sentence or two. */
export function sponsorBlockSummary(segments: SponsorBlockSegments | undefined): string {
    const named = (action: string) => CATEGORIES
        .filter((category) => (segments?.[category] ?? 'keep') === action)
        .map((category, index) => {
            const label = SponsorBlockCategoryReg.getLabel(category)
            return index === 0 ? label : label.toLowerCase()
        })
    const chapters = named('chapter')
    const cut = named('cut')
    const parts = [
        chapters.length ? `${joinAnd(chapters)} ${chapters.length === 1 ? 'becomes a chapter' : 'become chapters'}.` : '',
        cut.length ? `${joinAnd(cut)} ${cut.length === 1 ? 'is' : 'are'} cut out.` : '',
    ].filter(Boolean)
    if (!parts.length) return 'Every part is kept as it is.'
    return `${parts.join(' ')}${cut.length ? '' : ' Nothing is cut out.'} The rest is kept.`
}

/** Whether one of the profile's Sites has SponsorBlock, so the section has something to show. */
export function useOffersSponsorBlock(form: UseFormReturn<any>, mode: LocalMediaProfileType): boolean {
    const [siteKeys, includeUpcomingSites] = useWatch({control: form.control, name: ['siteKeys', 'includeUpcomingSites']}) as [string[] | null, boolean]
    const {data: sites} = useLocalMediaProfileSites()
    const withSponsorBlock = profileSitesWithSetting(sites, mode, siteKeys, includeUpcomingSites, 'sponsorblock')
    return withSponsorBlock.sites.length > 0 || withSponsorBlock.upcoming
}

/** SponsorBlock: a switch and a sentence; the segment choices open in a dialog. */
export default function SponsorBlockSection({form, mode}: {form: UseFormReturn<any>; mode: LocalMediaProfileType}) {
    const {control, setValue} = form
    const [siteKeys, includeUpcomingSites, enabled, segments] = useWatch({
        control, name: ['siteKeys', 'includeUpcomingSites', 'sponsorblockEnabled', 'sponsorblockSegments'],
    }) as [string[] | null, boolean, boolean | undefined, SponsorBlockSegments | undefined]
    const {data: sites} = useLocalMediaProfileSites()
    const withSponsorBlock = profileSitesWithSetting(sites, mode, siteKeys, includeUpcomingSites, 'sponsorblock')
    // The dialog works on a copy, so Cancel leaves the profile as it was.
    const [draft, setDraft] = useState<Record<string, string> | null>(null)
    const draftChanged = draft !== null && CATEGORIES.some((category) => (draft[category] ?? 'keep') !== (segments?.[category] ?? 'keep'))
    const marked = CATEGORIES.filter((category) => (segments?.[category] ?? 'keep') !== 'keep').length

    return (
        <>
            <div className="form-row">
                <label htmlFor="mp-sponsorblock-enabled">Use SponsorBlock</label>
                <Switch
                    id="mp-sponsorblock-enabled"
                    checked={!!enabled}
                    onChange={(value) => setValue('sponsorblockEnabled', value, {shouldDirty: true})}
                    onColor="#0ea5e9" offColor="#d1d5db" uncheckedIcon={false} checkedIcon={false}
                    aria-describedby="mp-sponsorblock-help"
                />
                {enabled && (
                    <div className="sponsorblock-summary">
                        <div>{sponsorBlockSummary(segments)}</div>
                        <div className="sponsorblock-summary__foot">
                            <span className="help">{marked} of {CATEGORIES.length} parts marked or cut</span>
                            <button type="button" className="btn btn-small" onClick={() => setDraft({...(segments ?? {})})}>
                                <FontAwesomeIcon icon={faIcon('fass', 'pen')}/> Edit segments
                            </button>
                        </div>
                    </div>
                )}
                <div className="help" id="mp-sponsorblock-help">
                    <ReadMore summary={`Mark or cut out sponsor reads and other parts of a video. Applies to ${siteNames(withSponsorBlock)}.`}>
                        <p>SponsorBlock is a community database of parts of YouTube videos, such as sponsor reads and “like and subscribe” reminders.
                            A part becomes a chapter your player can skip, or is cut out of the file. Most parts are submitted in the days after a video comes out,
                            so a download right after upload may have few of them. The episode page shows what was found.</p>
                        <p><strong>Chapter</strong> is the safe choice: nothing is removed, and your player can skip it.
                            {' '}<strong>Cut out</strong> is final; the cut part isn’t kept anywhere.</p>
                    </ReadMore>
                </div>
            </div>

            <ConfirmDialog
                open={draft !== null}
                title="SponsorBlock segments"
                className="sponsorblock-dialog"
                onDismiss={() => setDraft(null)}
                dismissOnEscape={!draftChanged}
                cancelButton={{label: 'Cancel', onClick: () => setDraft(null)}}
                confirmButton={{
                    label: 'Done',
                    onClick: () => {
                        if (draft) setValue('sponsorblockSegments', draft, {shouldDirty: true})
                        setDraft(null)
                    },
                }}
            >
                <section className="site-settings-section" aria-label="SponsorBlock segments">
                    <SponsorBlockSegmentsGrid
                        idPrefix="mp-dialog"
                        segments={draft ?? {}}
                        onChoose={(category, action) => setDraft((current) => ({...(current ?? {}), [category]: action}))}
                    />
                </section>
                <p className="help">Applies to {siteNames(withSponsorBlock)}. The Highlight and viewer chapters mark a moment or name a part, so they can only be kept or made a chapter.</p>
            </ConfirmDialog>
        </>
    )
}
