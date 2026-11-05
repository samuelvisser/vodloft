import {useEffect} from 'react'
import {Controller, useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'

import ReadMore from '../../utils/ReadMore'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import {useLocalMediaProfiles, useSiteOptions} from '../../lib/queries'
import type {UpgradeImprovement} from '../../types/schemas/download_profile'
import NumberInput from '../common/NumberInput'
import './UpgradeCheckCard.css'

type Props = {
    form: UseFormReturn<any>
    /** The saved collection the profile is for. */
    collectionId?: number
    /** The Source of a collection that is not saved yet. */
    sourceKey?: string
    /** The link of a collection that is not saved yet. */
    collectionUrl?: string
    /** A profile that is not saved yet starts with the upgrade check its collection's Site suggests. */
    newProfile?: boolean
}

const SWITCH = {onColor: '#0ea5e9', offColor: '#d1d5db', uncheckedIcon: false, checkedIcon: false} as const

const CHOICES: Record<Exclude<UpgradeImprovement, 'length'>, {label: string, help: string}> = {
    resolution: {label: 'A higher resolution', help: 'up to the Local Media Profile’s quality'},
    sponsorblock: {label: 'New SponsorBlock segments', help: 'of the types you mark or cut out'},
    subtitles: {label: 'New subtitles', help: 'in a language the Local Media Profile asks for'},
    codec: {label: 'The preferred codec', help: 'the first allowed codec in the Local Media Profile'},
}

/**
 * The upgrade check: download an episode again later, and keep the new file only when it is better. The
 * Collection's Site decides what shows: whether it has countdown downloads, and what can count as better.
 * A Site with neither has no upgrade check at all.
 */
export default function UpgradeCheckCard({form, collectionId, sourceKey, collectionUrl, newProfile}: Props) {
    const {control, register, setValue, getValues, formState: {errors}} = form
    const [withCountdown, upgradeCheck, afterDays, improvements, sponsorblockEnabled, localMediaProfileId] = useWatch({
        control,
        name: ['downloadWithCountdown', 'upgradeCheck', 'upgradeAfterDays', 'upgradeImprovements', 'sponsorblockEnabled', 'localMediaProfileId'],
    }) as [boolean, boolean, number, UpgradeImprovement[] | undefined, boolean, number | string | undefined]

    const {data: site} = useSiteOptions({collectionId, sourceKey, url: collectionUrl})
    // A profile that already downloads with the countdown keeps the switches, so it can turn them off.
    const offersCountdown = !!site?.countdownDownloads || !!withCountdown
    const offered = site?.upgradeChecks.improvements ?? []
    const offersUpgrades = offered.length > 0
    const {data: mediaProfiles} = useLocalMediaProfiles()
    const mediaProfile = mediaProfiles?.find((profile) => String(profile.id) === String(localMediaProfileId))

    // A new profile starts with the Site's own suggestion, unless it already checks for something the Site offers.
    useEffect(() => {
        if (!newProfile || !site) return
        const current: UpgradeImprovement[] = getValues('upgradeImprovements') ?? []
        if (current.some((improvement) => site.upgradeChecks.improvements.includes(improvement))) return
        setValue('upgradeCheck', site.upgradeChecks.onByDefault)
        setValue('upgradeImprovements', [...site.upgradeChecks.checked])
    }, [newProfile, site, getValues, setValue])

    if (!offersCountdown && !offersUpgrades) return null

    const days = Number.isFinite(afterDays) && afterDays > 0 ? afterDays : 7
    const repeatReg = createSelectRegistry('UpgradeRepeat', {
        once: {label: 'Once, then stop'},
        twice: {label: 'Twice, again after 30 days'},
        every: {label: `Every ${days} ${days === 1 ? 'day' : 'days'}, up to 3 times`},
    })
    const chosen = new Set(improvements ?? [])
    const toggle = (improvement: UpgradeImprovement, on: boolean) => {
        const next = new Set(chosen)
        if (on) next.add(improvement)
        else next.delete(improvement)
        setValue('upgradeImprovements', offered.filter((key) => next.has(key)), {shouldDirty: true})
    }
    const audioOnly = mediaProfile?.preferredFormat === 'format_audio_only'
    // A profile that is still being made in the same flow counts as storing subtitles.
    const storesSubtitles = !mediaProfile || mediaProfile.subtitleMode !== 'no_subtitles'
    // Only what the Site offers, and of that only what the profile can use.
    const usable: Record<UpgradeImprovement, boolean> = {
        resolution: !audioOnly,
        sponsorblock: sponsorblockEnabled,
        subtitles: storesSubtitles,
        codec: !audioOnly,
        length: true,
    }
    const choices = offered.filter((key) => usable[key])

    return (
        <div className="form-row which-episodes upgrade-check" id="upgrade-check">
            <span style={{fontWeight: 600}}>Upgrade check</span>
            <div className="upgrade-check-body">
                {offersCountdown && (
                    <div className="upgrade-check-row">
                        <label htmlFor="with-countdown">Download with countdown</label>
                        <Controller control={control} name="downloadWithCountdown" render={({field}) => (
                            <Switch id="with-countdown" checked={!!field.value} onChange={field.onChange} {...SWITCH}/>
                        )}/>
                        <div className="help">
                            <ReadMore summary={<span>Download live episodes while their countdown is still on</span>}>
                                Some live podcast episodes appear with a countdown timer before the final media is available.
                                With this on, VODLoft downloads the episode while the countdown is still there.
                            </ReadMore>
                        </div>
                    </div>
                )}

                {offersCountdown && withCountdown && (
                    <div className="upgrade-check-row">
                        <label htmlFor="redownload-final">Download again as <b>the final version</b></label>
                        <Controller control={control} name="redownloadFinal" render={({field}) => (
                            <Switch id="redownload-final" checked={!!field.value} onChange={field.onChange} {...SWITCH}/>
                        )}/>
                        <div className="help">As soon as it is out, usually 1.5 to 2 hours after the episode was published.</div>
                    </div>
                )}

                {offersCountdown && offersUpgrades && <div className="upgrade-check-divider"/>}

                {offersUpgrades && (
                    <div className="upgrade-check-row">
                        <label htmlFor="upgrade-check-on">Download again when a better version is out</label>
                        <Controller control={control} name="upgradeCheck" render={({field}) => (
                            <Switch id="upgrade-check-on" checked={!!field.value} onChange={field.onChange} {...SWITCH}/>
                        )}/>
                        <div className="help">
                            <ReadMore summary={<span>The new file replaces the old one only when it is better</span>}>
                                Sites often change a video after it is uploaded: a higher resolution can appear hours later,
                                SponsorBlock segments and subtitles are added over days, and a long live stream can be cut down.
                                VODLoft first asks the site what it has now, and only downloads again when one of the changes you
                                check below is there. A different length is also checked as soon as the metadata refresh sees one.
                                The old file stays until the new one is complete. Kept downloads are checked too.
                            </ReadMore>
                        </div>
                    </div>
                )}

                {offersUpgrades && upgradeCheck && (
                    <>
                        <div className="upgrade-check-fields">
                            <div className="upgrade-check-field">
                                <label htmlFor="upgrade-after-days">Check after … days</label>
                                <NumberInput
                                    id="upgrade-after-days" inputMode="numeric" min={1} max={365} step={1}
                                    {...register('upgradeAfterDays', {valueAsNumber: true})}
                                    aria-invalid={!!errors.upgradeAfterDays}
                                />
                                {errors.upgradeAfterDays && (
                                    <div className="error" role="alert">{errors.upgradeAfterDays.message as string}</div>
                                )}
                            </div>
                            <div className="upgrade-check-field">
                                <label htmlFor="upgrade-repeat">How often</label>
                                <Controller control={control} name="upgradeRepeat" render={({field}) => (
                                    <SimpleSelect inputId="upgrade-repeat" registry={repeatReg} value={field.value ?? 'once'} onChange={field.onChange}/>
                                )}/>
                            </div>
                        </div>
                        <fieldset className="upgrade-check-improvements">
                            <legend>Better means</legend>
                            {choices.map((key) => key === 'length' ? (
                                <div key={key} className="upgrade-check-choice upgrade-check-length">
                                    <input
                                        id="upgrade-length" type="checkbox" checked={chosen.has(key)}
                                        onChange={(event) => toggle(key, event.target.checked)}
                                    />
                                    <label htmlFor="upgrade-length">A different length</label>
                                    <span className="upgrade-check-choice-help">longer or shorter by more than</span>
                                    <NumberInput
                                        id="upgrade-length-minutes" inputMode="numeric" min={1} max={600} step={1}
                                        wrapperClassName="upgrade-check-minutes" aria-label="Minutes" suffix="minutes"
                                        disabled={!chosen.has(key)}
                                        {...register('upgradeLengthMinutes', {valueAsNumber: true})}
                                        aria-invalid={!!errors.upgradeLengthMinutes}
                                    />
                                    {errors.upgradeLengthMinutes && (
                                        <div className="error" role="alert">{errors.upgradeLengthMinutes.message as string}</div>
                                    )}
                                </div>
                            ) : (
                                <label key={key} className="upgrade-check-choice">
                                    <input
                                        type="checkbox" checked={chosen.has(key)}
                                        onChange={(event) => toggle(key, event.target.checked)}
                                    />
                                    <span>{CHOICES[key].label} <span className="upgrade-check-choice-help">{CHOICES[key].help}</span></span>
                                </label>
                            ))}
                            <div className="help">Checks stop early once an episode can’t get any better.</div>
                        </fieldset>
                    </>
                )}
            </div>
        </div>
    )
}
