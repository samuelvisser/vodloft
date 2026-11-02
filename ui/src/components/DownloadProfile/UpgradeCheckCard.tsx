import {Controller, useWatch, type UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'

import ReadMore from '../../utils/ReadMore'
import {createSelectRegistry} from '../../utils/selectRegistry'
import SimpleSelect from '../common/SimpleSelect'
import {useCollections, useLocalMediaProfiles, useSiteOptions, useSourceLookup} from '../../lib/queries'
import {sourceControls} from '../../lib/sourceControls'
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
}

type Improvement = 'resolution' | 'sponsorblock' | 'subtitles' | 'codec'

const SWITCH = {onColor: '#0ea5e9', offColor: '#d1d5db', uncheckedIcon: false, checkedIcon: false} as const

/**
 * The upgrade check: download an episode again later, and keep the new file only when it is better. It only
 * shows what can improve for the Collection's site; The Daily Wire's countdown downloads live here too.
 */
export default function UpgradeCheckCard({form, collectionId, sourceKey, collectionUrl}: Props) {
    const {control, register, setValue, formState: {errors}} = form
    const [withCountdown, upgradeCheck, afterDays, improvements, sponsorblockEnabled, localMediaProfileId] = useWatch({
        control,
        name: ['downloadWithCountdown', 'upgradeCheck', 'upgradeAfterDays', 'upgradeImprovements', 'sponsorblockEnabled', 'localMediaProfileId'],
    }) as [boolean, boolean, number, Improvement[] | undefined, boolean, number | string | undefined]

    const {data: collections} = useCollections()
    const collection = collections?.find((item) => item.id === collectionId)
    const newCollectionSource = useSourceLookup().get(sourceKey)
    const controls = sourceControls(collection ?? (newCollectionSource ? {sourceFeatures: newCollectionSource.features} : undefined))
    const offersCountdown = controls.countdownDownloads || !!withCountdown
    const {data: site} = useSiteOptions({collectionId, sourceKey, url: collectionUrl})
    const offersUpgrades = !!site?.upgradeChecks
    const {data: mediaProfiles} = useLocalMediaProfiles()
    const mediaProfile = mediaProfiles?.find((profile) => String(profile.id) === String(localMediaProfileId))

    if (!offersCountdown && !offersUpgrades) return null

    const days = Number.isFinite(afterDays) && afterDays > 0 ? afterDays : 7
    const repeatReg = createSelectRegistry('UpgradeRepeat', {
        once: {label: 'Once, then stop'},
        twice: {label: 'Twice, again after 30 days'},
        every: {label: `Every ${days} ${days === 1 ? 'day' : 'days'}, up to 3 times`},
    })
    const chosen = new Set(improvements ?? [])
    const toggle = (improvement: Improvement, on: boolean) => {
        const next = new Set(chosen)
        if (on) next.add(improvement)
        else next.delete(improvement)
        setValue('upgradeImprovements', (['resolution', 'sponsorblock', 'subtitles', 'codec'] as Improvement[]).filter((key) => next.has(key)), {shouldDirty: true})
    }
    const audioOnly = mediaProfile?.preferredFormat === 'format_audio_only'
    // A profile that is still being made in the same flow counts as storing subtitles.
    const storesSubtitles = !mediaProfile || mediaProfile.subtitleMode !== 'no_subtitles'
    const choices: {key: Improvement, label: string, help: string, shown: boolean}[] = [
        {key: 'resolution', label: 'A higher resolution', help: 'up to the Local Media Profile’s quality', shown: !audioOnly},
        {key: 'sponsorblock', label: 'New SponsorBlock segments', help: 'of the types you mark or cut out', shown: !!site?.sponsorblock && sponsorblockEnabled},
        {key: 'subtitles', label: 'New subtitles', help: 'in a language the Local Media Profile asks for', shown: storesSubtitles},
        {key: 'codec', label: 'The preferred codec', help: 'the first allowed codec in the Local Media Profile', shown: !audioOnly},
    ]

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

                {offersUpgrades && (
                    <div className="upgrade-check-row">
                        <label htmlFor="upgrade-check-on">Download again when a better version is out</label>
                        <Controller control={control} name="upgradeCheck" render={({field}) => (
                            <Switch id="upgrade-check-on" checked={!!field.value} onChange={field.onChange} {...SWITCH}/>
                        )}/>
                        <div className="help">
                            <ReadMore summary={<span>The new file replaces the old one only when it is better</span>}>
                                Sites often improve a video after it is uploaded: a higher resolution can appear hours later, and
                                SponsorBlock segments and subtitles are added over days. VODLoft first asks the site what it has now,
                                and only downloads again when one of the improvements you check below is there. The old file stays
                                until the new one is complete. Kept downloads are checked too.
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
                            {choices.filter((choice) => choice.shown).map((choice) => (
                                <label key={choice.key} className="upgrade-check-choice">
                                    <input
                                        type="checkbox" checked={chosen.has(choice.key)}
                                        onChange={(event) => toggle(choice.key, event.target.checked)}
                                    />
                                    <span>{choice.label} <span className="upgrade-check-choice-help">{choice.help}</span></span>
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
