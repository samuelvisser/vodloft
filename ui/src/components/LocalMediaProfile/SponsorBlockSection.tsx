import {useWatch, type UseFormReturn} from 'react-hook-form'

import {useLocalMediaProfileSites} from '../../lib/queries'
import {profileSitesWithSetting, siteNames, type LocalMediaProfileType} from '../../types/local_media_profile'
import type {SponsorBlockSegments} from '../../types/schemas/local_media_profile_base'
import SponsorBlockFields from './SponsorBlockFields'
import './SiteSettingsSection.css'

/** SponsorBlock, as its own section, when one of the profile's Sites has it. */
export default function SponsorBlockSection({form, mode}: {form: UseFormReturn<any>; mode: LocalMediaProfileType}) {
    const {control, setValue} = form
    const [siteKeys, includeUpcomingSites, enabled, segments] = useWatch({
        control, name: ['siteKeys', 'includeUpcomingSites', 'sponsorblockEnabled', 'sponsorblockSegments'],
    }) as [string[] | null, boolean, boolean | undefined, SponsorBlockSegments | undefined]
    const {data: sites} = useLocalMediaProfileSites()
    const withSponsorBlock = profileSitesWithSetting(sites, mode, siteKeys, includeUpcomingSites, 'sponsorblock')
    if (!withSponsorBlock.sites.length && !withSponsorBlock.upcoming) return null

    return (
        <section className="site-settings-section" aria-label="SponsorBlock">
            <hr className="form-section-divider" aria-hidden="true"/>
            <SponsorBlockFields
                idPrefix="mp"
                enabled={!!enabled}
                segments={segments ?? {}}
                appliesTo={`Applies to ${siteNames(withSponsorBlock)}.`}
                onChange={(nextEnabled, nextSegments) => {
                    setValue('sponsorblockEnabled', nextEnabled, {shouldDirty: true})
                    setValue('sponsorblockSegments', nextSegments, {shouldDirty: true})
                }}
            />
        </section>
    )
}
