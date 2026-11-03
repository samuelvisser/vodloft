import {Controller, UseFormReturn} from 'react-hook-form'
import Switch from 'react-switch'
import ReadMore from '../../utils/ReadMore'
import {createSelectRegistry} from '../../utils/selectRegistry'
import DateInput from '../common/DateInput'
import SimpleSelect from '../common/SimpleSelect'

type Props = {
    form: UseFormReturn<any>
}

// Read after the line's header, "Only download if published …".
const LimitModeReg = createSelectRegistry('DownloadLimitMode', {
    none: {label: 'at any time'},
    date: {label: 'in the last … days'},
    episodes: {label: 'as one of the latest … episodes'},
})
type LimitMode = (typeof LimitModeReg)['values'][number]

/** The date line of Which episodes: when episodes were published, or how long each download is kept. */
export default function DownloadProfileDateFilters({form}: Props) {
    const {control, register, watch, setValue, clearErrors, formState: {errors}} = form

    const watchedDaysRaw = watch('downloadDaysInPast') ?? 0
    const watchedEpisodeCountRaw = watch('downloadEpisodeCount') ?? 0
    const watchedDays = Number.isFinite(watchedDaysRaw) ? watchedDaysRaw : 0
    const watchedEpisodeCount = Number.isFinite(watchedEpisodeCountRaw) ? watchedEpisodeCountRaw : 0
    const daysInputInvalid = typeof watchedDaysRaw === 'number' && Number.isNaN(watchedDaysRaw)
    const episodeCountInputInvalid = typeof watchedEpisodeCountRaw === 'number' && Number.isNaN(watchedEpisodeCountRaw)
    const limitMode: LimitMode = watchedEpisodeCount > 0 || episodeCountInputInvalid
        ? 'episodes'
        : watchedDays > 0 || daysInputInvalid
            ? 'date'
            : 'none'

    // Published or downloaded is chosen in the date line's header.
    const dateField = (watch('retentionFrom') ?? 'published') as 'published' | 'downloaded'

    const updateLimitMode = (mode: LimitMode) => {
        if (mode === 'none') {
            setValue('downloadDaysInPast', 0, {shouldDirty: true, shouldValidate: true})
            setValue('downloadEpisodeCount', 0, {shouldDirty: true, shouldValidate: true})
            return
        }

        setValue('downloadStartingFrom', null, {shouldDirty: true, shouldValidate: true})

        if (mode === 'date') {
            setValue('downloadEpisodeCount', 0, {shouldDirty: true, shouldValidate: true})
            setValue('downloadDaysInPast', watchedDays > 0 ? watchedDays : 180, {shouldDirty: true, shouldValidate: true})
            return
        }

        setValue('downloadDaysInPast', 0, {shouldDirty: true, shouldValidate: true})
        setValue('downloadEpisodeCount', watchedEpisodeCount > 0 ? watchedEpisodeCount : 5, {
            shouldDirty: true,
            shouldValidate: true,
        })
    }

    const oldestDateText = (() => {
        if (limitMode !== 'date' || !watchedDays || watchedDays <= 0) return null
        const d = new Date()
        d.setHours(0, 0, 0, 0)
        d.setDate(d.getDate() - watchedDays)
        const yyyy = d.getFullYear()
        const mm = String(d.getMonth() + 1).padStart(2, '0')
        const dd = String(d.getDate()).padStart(2, '0')
        return `${yyyy}-${mm}-${dd}`
    })()

    return (
        <>
            {dateField === 'published' && (
            <div className="form-row">
                <SimpleSelect
                    inputId="download-limit-mode"
                    aria-label="Published when"
                    registry={LimitModeReg}
                    value={limitMode}
                    onChange={(value) => updateLimitMode(value as LimitMode)}
                />
            </div>
            )}

            {limitMode === 'none' && (
                <div className="form-row">
                    <label htmlFor="download-starting-from">On or after</label>
                    <Controller
                        control={control}
                        name="downloadStartingFrom"
                        render={({field}) => (
                            <DateInput
                                {...field}
                                id="download-starting-from"
                                aria-invalid={!!errors.downloadStartingFrom}
                                aria-describedby={errors.downloadStartingFrom ? 'download-starting-from-errors' : 'download-starting-from-help'}
                                clearButtonLabel="Clear download starting from date"
                                onClear={() => {
                                    setValue('downloadStartingFrom', null, {shouldDirty: true, shouldValidate: true})
                                    clearErrors('downloadStartingFrom')
                                }}
                            />
                        )}
                    />
                    {errors.downloadStartingFrom && (
                        <div id="download-starting-from-errors" className="error" role="alert" aria-live="polite">
                            {errors.downloadStartingFrom.message as string}
                        </div>
                    )}
                    <div className="help" id="download-starting-from-help">
                        Optional. Leave it empty to download episodes of any date. Episodes from before the date that are already
                        downloaded are not deleted.
                    </div>
                </div>
            )}

            {limitMode === 'date' && (
                <div className="form-row">
                    <label htmlFor="days-in-past">{dateField === 'downloaded' ? 'Keep each download for … days' : 'Days'}</label>
                    <input
                        id="days-in-past"
                        className="input"
                        type="number"
                        inputMode="numeric"
                        min={1}
                        step={1}
                        {...register('downloadDaysInPast', {valueAsNumber: true})}
                        aria-invalid={!!errors.downloadDaysInPast}
                        aria-describedby={errors.downloadDaysInPast ? 'days-in-past-errors' : 'days-in-past-help'}
                    />
                    {errors.downloadDaysInPast && (
                        <div id="days-in-past-errors" className="error" role="alert" aria-live="polite">
                            {errors.downloadDaysInPast.message as string}
                        </div>
                    )}
                    <div className="help" id="days-in-past-help">
                        {dateField === 'downloaded' ? 'Only episodes published in this many days are downloaded.' : null}
                        {oldestDateText ? (
                            <>
                                {dateField === 'downloaded' ? ' ' : ''}The oldest that will be downloaded: <strong>{oldestDateText}</strong>
                            </>
                        ) : null}
                    </div>
                </div>
            )}

            {limitMode === 'episodes' && (
                <div className="form-row">
                    <label htmlFor="episode-count">Episodes</label>
                    <input
                        id="episode-count"
                        className="input"
                        type="number"
                        inputMode="numeric"
                        min={1}
                        step={1}
                        {...register('downloadEpisodeCount', {valueAsNumber: true})}
                        aria-invalid={!!errors.downloadEpisodeCount}
                        aria-describedby={errors.downloadEpisodeCount ? 'episode-count-errors' : 'episode-count-help'}
                    />
                    {errors.downloadEpisodeCount && (
                        <div id="episode-count-errors" className="error" role="alert" aria-live="polite">
                            {errors.downloadEpisodeCount.message as string}
                        </div>
                    )}
                    <div className="help" id="episode-count-help">
                        How many of the newest episodes this profile downloads.
                    </div>
                </div>
            )}

            {limitMode !== 'none' && (
                <div className="form-row">
                    <label htmlFor="delete-older">{dateField === 'downloaded'
                        ? `And delete them ${watchedDays || '…'} ${watchedDays === 1 ? 'day' : 'days'} after downloading`
                        : limitMode === 'episodes' ? 'And delete them once they are no longer among the latest' : 'And delete them once they are older'}</label>
                    <Controller
                        control={control}
                        name="deleteOlderEpisodes"
                        render={({field}) => (
                            <Switch
                                id="delete-older"
                                checked={!!field.value}
                                onChange={(checked) => field.onChange(checked)}
                                onColor="#0ea5e9"
                                offColor="#d1d5db"
                                uncheckedIcon={false}
                                checkedIcon={false}
                                aria-invalid={!!errors.deleteOlderEpisodes}
                                aria-describedby={errors.deleteOlderEpisodes ? 'delete-older-errors' : 'delete-older-help'}
                            />
                        )}
                    />
                    {errors.deleteOlderEpisodes && (
                        <div id="delete-older-errors" className="error" role="alert" aria-live="polite">
                            {errors.deleteOlderEpisodes.message as string}
                        </div>
                    )}
                    <div className="help" id="delete-older-help">
                        <ReadMore summary={<span>Downloads you keep are never deleted</span>}>
                            {'Downloads you keep, and downloads a Keep filter matches, are never deleted. '}
                            {limitMode === 'date'
                                ? 'If enabled, downloaded episodes older than the date shown above will be automatically removed from disk.'
                                : `If enabled, downloaded episodes outside the latest ${watchedEpisodeCount || 'selected number of'} eligible episodes will be automatically removed from disk.`}
                        </ReadMore>
                    </div>
                </div>
            )}

        </>
    )
}
