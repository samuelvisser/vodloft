import {useWatch, type UseFormReturn} from 'react-hook-form'

import {useLocalMediaProfileSites} from '../../lib/queries'
import {sitesForLocalMediaProfileType, type LocalMediaProfileType} from '../../types/local_media_profile'
import type {SiteDownloadChoices} from '../../types/schemas/local_media_profile_base'
import {AutoSubtitlesReg} from '../../types/quality'
import ReadMore from '../../utils/ReadMore'
import SimpleSelect from '../common/SimpleSelect'
import SponsorBlockFields from './SponsorBlockFields'
import './SiteSettingsSection.css'

/**
 * Settings only some Sites show, such as YouTube's auto-generated subtitles and SponsorBlock: a section per
 * Site the profile is offered for. A Site without settings of its own in the profile shows what it starts with.
 */
export default function SiteSettingsSections({form, mode}: {form: UseFormReturn<any>; mode: LocalMediaProfileType}) {
    const {control, setValue} = form
    const [siteKeys, siteSettings, subtitleMode] = useWatch({
        control, name: ['siteKeys', 'siteSettings', 'subtitleMode'],
    }) as [string[] | null, Record<string, SiteDownloadChoices> | undefined, string]
    const {data: sites} = useLocalMediaProfileSites()
    const storesSubtitles = !!subtitleMode && subtitleMode !== 'no_subtitles'

    const shown = sitesForLocalMediaProfileType(sites, mode).filter((site) => (
        (siteKeys ?? []).includes(site.key)
        && (site.settings.includes('sponsorblock') || (storesSubtitles && site.settings.includes('autoSubtitles')))
    ))
    if (!shown.length) return null

    const change = (siteKey: string, choices: SiteDownloadChoices) =>
        setValue('siteSettings', {...(siteSettings ?? {}), [siteKey]: choices}, {shouldDirty: true})

    return (
        <>
            {shown.map((site) => {
                const choices = siteSettings?.[site.key] ?? site.defaults
                const id = `site-${site.key.replace(/[^a-z0-9]+/gi, '-')}`
                return (
                    <section key={site.key} className="site-settings-section" aria-labelledby={`${id}-heading`}>
                        <hr className="form-section-divider" aria-hidden="true"/>
                        <h3 className="site-settings-heading" id={`${id}-heading`}>{site.name}</h3>
                        {storesSubtitles && site.settings.includes('autoSubtitles') && (
                            <div className="form-row">
                                <label htmlFor={`${id}-auto-subtitles`}>Use auto-generated subtitles</label>
                                <SimpleSelect
                                    inputId={`${id}-auto-subtitles`}
                                    registry={AutoSubtitlesReg}
                                    value={choices.autoSubtitles}
                                    onChange={(value) => change(site.key, {...choices, autoSubtitles: value as SiteDownloadChoices['autoSubtitles']})}
                                    aria-describedby={`${id}-auto-subtitles-help`}
                                />
                                <div className="help" id={`${id}-auto-subtitles-help`}>
                                    <ReadMore summary={`Subtitles ${site.name} makes itself, in the languages above.`}>
                                        <p>{site.name} can make subtitles automatically. They follow the languages above.</p>
                                        <p><strong>Only when there are no real ones</strong> uses an auto-generated subtitle for a language that has no subtitle a person made.</p>
                                        <p><strong>Always</strong> also adds it next to a real one, as its own track marked auto-generated.</p>
                                    </ReadMore>
                                </div>
                            </div>
                        )}
                        {site.settings.includes('sponsorblock') && (
                            <SponsorBlockFields
                                idPrefix={id}
                                enabled={choices.sponsorblockEnabled}
                                segments={choices.sponsorblockSegments}
                                onChange={(enabled, segments) => change(site.key, {
                                    ...choices, sponsorblockEnabled: enabled, sponsorblockSegments: segments as SiteDownloadChoices['sponsorblockSegments'],
                                })}
                            />
                        )}
                    </section>
                )
            })}
        </>
    )
}
