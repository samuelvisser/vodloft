import {useEffect, useId, useMemo, useState} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import Select from '../../components/common/ReactSelect'
import toast from '../../lib/toast'
import {z} from 'zod'

import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {faIcon} from '../../icons/faIcon'
import {OperationStartError, useStartOperation} from '../../lib/operations'
import {useCollectionEpisodeTags} from '../../lib/queries'
import {
  buildLocalMediaProfileSelectRegistry,
  type CollectionLocalMediaProfileContext,
  isCollectionLocalMediaProfileAvailableFor,
  isLocalMediaProfileAvailableForSite,
} from '../../types/local_media_profile'
import type {LocalMediaProfileRead} from '../../types/schemas/local_media_profile'
import type {SeasonRead} from '../../types/schemas/season'
import {createSelectRegistry} from '../../utils/selectRegistry'
import NumberInput from '../../components/common/NumberInput'
import './CollectionDownloadAllDialog.css'
import {apiUrl} from '../../lib/api'
import {collectionWords, CollectionWords, downloadsBySeason} from '../../lib/collectionWords'

const LimitByReg = createSelectRegistry('DownloadAllLimitBy', {
  none: {label: 'No limits'},
  date: {label: 'Date'},
  episodes: {label: 'Number of episodes'},
})

const downloadAllFormSchema = z.object({
  localMediaProfileId: z.number().int().positive(),
  seasonIds: z.array(z.number().int().positive()),
  episodeTypes: z.array(z.string()),
  limitBy: z.enum(['none', 'date', 'episodes']),
  downloadDaysInPast: z.number().int().positive(),
  downloadEpisodeCount: z.number().int().positive(),
  downloadStartingFrom: z.iso.date().nullable(),
})

type DownloadAllForm = z.infer<typeof downloadAllFormSchema>

type Props = {
  collectionSlug: string
  collectionTitle: string
  collectionType: CollectionLocalMediaProfileContext
  siteKey: string | null | undefined
  seasons: readonly SeasonRead[]
  localMediaProfiles: readonly LocalMediaProfileRead[]
  onDismiss: () => void
  /** The dialog closes as soon as the download starts; the page shows the starting state instead. */
  onStartingChange?: (starting: boolean) => void
  /** What the collection calls its seasons and the downloads of its episodes, such as albums and tracks. */
  words?: CollectionWords
}

export default function CollectionDownloadAllDialog({
  collectionSlug,
  collectionTitle,
  collectionType,
  siteKey,
  seasons,
  localMediaProfiles,
  onDismiss,
  onStartingChange,
  words = collectionWords(collectionType),
}: Props) {
  const {season, episode} = words
  const selectId = useId()
  const startOperation = useStartOperation()
  // Series and Music collections are downloaded by season; a podcast by date or number of episodes.
  const bySeason = downloadsBySeason(collectionType)
  const [starting, setStarting] = useState(false)

  const compatibleProfiles = useMemo(
    () => localMediaProfiles.filter((profile) => (
      isCollectionLocalMediaProfileAvailableFor(profile, collectionType)
      && isLocalMediaProfileAvailableForSite(profile, siteKey)
    )),
    [localMediaProfiles, collectionType, siteKey],
  )
  const profileRegistry = useMemo(
    () => buildLocalMediaProfileSelectRegistry(compatibleProfiles, 'collection', collectionType),
    [compatibleProfiles, collectionType],
  )
  const seasonRegistry = useMemo(() => {
    const spec: Record<string, {label: string}> = {}
    const values: string[] = []
    for (const season of seasons) {
      const id = String(season.id)
      spec[id] = {label: season.name}
      values.push(id)
    }
    return createSelectRegistry('DownloadAllSeason', spec, values)
  }, [seasons])

  const schema = useMemo(
    () => downloadAllFormSchema.superRefine((data, context) => {
      if (bySeason && data.seasonIds.length === 0) {
        context.addIssue({
          code: 'custom',
          path: ['seasonIds'],
          message: `Select at least one ${season.singular}.`,
        })
      }
      if (data.episodeTypes.length === 0) {
        context.addIssue({
          code: 'custom',
          path: ['episodeTypes'],
          message: 'Select at least one episode type.',
        })
      }
      if (!bySeason && data.limitBy === 'date' && data.downloadDaysInPast < 1) {
        context.addIssue({
          code: 'custom',
          path: ['downloadDaysInPast'],
          message: 'Enter a positive number of days.',
        })
      }
      if (!bySeason && data.limitBy === 'episodes' && data.downloadEpisodeCount < 1) {
        context.addIssue({
          code: 'custom',
          path: ['downloadEpisodeCount'],
          message: `Enter a positive number of ${episode.plural}.`,
        })
      }
    }),
    [collectionType],
  )
  const {control, handleSubmit, setValue, watch, formState: {errors, dirtyFields}} = useForm<DownloadAllForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      seasonIds: [],
      episodeTypes: [],
      limitBy: 'none',
      downloadDaysInPast: 180,
      downloadEpisodeCount: 5,
      downloadStartingFrom: null,
    },
  })

  const limitBy = watch('limitBy')

  // Each selector initializes as its data arrives, without overwriting edits to another field.
  useEffect(() => {
    if (!dirtyFields.localMediaProfileId && compatibleProfiles[0]) {
      setValue('localMediaProfileId', compatibleProfiles[0].id)
    }
  }, [compatibleProfiles, dirtyFields.localMediaProfileId, setValue])

  // Episode types are the tags of the collection's Source; all of them start selected.
  const {data: tags} = useCollectionEpisodeTags({collectionSlug})
  const tagOptions = useMemo(() => (tags ?? []).map((tag) => ({value: tag.key, label: tag.label})), [tags])
  useEffect(() => {
    if (!dirtyFields.episodeTypes && tagOptions.length > 0) {
      setValue('episodeTypes', tagOptions.map((option) => option.value))
    }
  }, [tagOptions, dirtyFields.episodeTypes, setValue])

  useEffect(() => {
    if (!dirtyFields.seasonIds && seasons.length > 0) {
      setValue('seasonIds', seasons.map((season) => season.id))
    }
  }, [seasons, dirtyFields.seasonIds, setValue])

  const submit = handleSubmit(async (values) => {
    if (starting) return
    setStarting(true)
    onStartingChange?.(true)
    onDismiss()
    try {
      const base = apiUrl()
      const result = await startOperation<{
        operationId: string
        queued: boolean
        episodesQueued: number
      }>(`${base}/collections/${encodeURIComponent(collectionSlug)}/download-all`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          localMediaProfileId: values.localMediaProfileId,
          seasonIds: bySeason ? values.seasonIds : [],
          episodeTypes: values.episodeTypes,
          downloadDaysInPast: !bySeason && values.limitBy === 'date' ? values.downloadDaysInPast : 0,
          downloadEpisodeCount: !bySeason && values.limitBy === 'episodes' ? values.downloadEpisodeCount : 0,
          downloadStartingFrom: !bySeason && values.limitBy === 'none' ? values.downloadStartingFrom : null,
        }),
      })
      toast.success(result.queued
        ? `Queued ${result.episodesQueued} ${episode.singular} downloads for ${collectionTitle}`
        : `No new ${episode.plural} to download for ${collectionTitle}`)
    } catch (error) {
      const detail = error instanceof OperationStartError ? error.message : undefined
      toast.error(detail || `Could not queue downloads for ${collectionTitle}`)
    } finally {
      setStarting(false)
      onStartingChange?.(false)
    }
  })

  return (
    <ConfirmDialog
      open
      title="Bulk download"
      onDismiss={() => {if (!starting) onDismiss()}}
      icon={faIcon('fass', 'download')}
      className="collection-download-all-dialog"
      dismissOnOverlayClick={!starting}
      cancelButton={{disabled: starting}}
      confirmButton={{
        label: starting ? 'Starting…' : 'Bulk download',
        onClick: () => void submit(),
        disabled: starting || !compatibleProfiles.length,
      }}
    >
      <p>Download the selected {episode.plural} from "{collectionTitle}". Existing downloaded files will not be replaced.</p>
      {bySeason ? (
        <div className="form-row">
          <div className="collection-download-all-label-row">
            <label htmlFor={`${selectId}-season`}>{season.Plural} to download</label>
            <button
              type="button"
              className="btn btn-link"
              disabled={starting || seasons.length === 0}
              onClick={() => setValue('seasonIds', seasons.map((season) => season.id), {
                shouldDirty: true,
                shouldValidate: true,
              })}
            >
              Select all
            </button>
          </div>
          <Controller
            name="seasonIds"
            control={control}
            render={({field}) => (
              <Select
                inputId={`${selectId}-season`}
                classNamePrefix="select"
                isMulti
                options={seasonRegistry.options}
                value={seasonRegistry.options.filter((option) => field.value.includes(Number(option.value)))}
                onChange={(options) => field.onChange(options.map((option) => Number(option.value)))}
                onBlur={field.onBlur}
                closeMenuOnSelect={false}
                isDisabled={starting || seasons.length === 0}
                placeholder={seasons.length ? `Select ${season.plural}` : `No ${season.plural} available`}
                aria-invalid={!!errors.seasonIds}
              />
            )}
          />
          {errors.seasonIds && <div className="error" role="alert">{errors.seasonIds.message}</div>}
        </div>
      ) : null}
      <div className="form-row">
        <div className="collection-download-all-label-row">
            <label htmlFor={`${selectId}-type`}>{episode.Singular} types to download</label>
            <button
              type="button"
              className="btn btn-link"
              disabled={starting}
              onClick={() => setValue('episodeTypes', tagOptions.map((option) => option.value), {
                shouldDirty: true,
                shouldValidate: true,
              })}
            >
              Select all
            </button>
          </div>
          <Controller
            name="episodeTypes"
            control={control}
            render={({field}) => (
              <Select
                inputId={`${selectId}-type`}
                classNamePrefix="select"
                isMulti
                options={tagOptions}
                value={tagOptions.filter((option) => field.value.includes(option.value))}
                onChange={(options) => field.onChange(options.map((option) => option.value))}
                onBlur={field.onBlur}
                closeMenuOnSelect={false}
                isDisabled={starting}
                aria-invalid={!!errors.episodeTypes}
              />
            )}
          />
          {errors.episodeTypes && <div className="error" role="alert">{errors.episodeTypes.message}</div>}
      </div>
      {!bySeason && (
        <>
          <div className="form-row">
            <label htmlFor={`${selectId}-limit`}>Limit by</label>
            <Controller
              name="limitBy"
              control={control}
              render={({field}) => (
                <SimpleSelect
                  inputId={`${selectId}-limit`}
                  registry={LimitByReg}
                  value={field.value}
                  onChange={(value) => {
                    field.onChange(value)
                    if (value !== 'date') setValue('downloadDaysInPast', 180)
                    if (value !== 'episodes') setValue('downloadEpisodeCount', 5)
                    if (value !== 'none') setValue('downloadStartingFrom', null)
                  }}
                  onBlur={field.onBlur}
                  isDisabled={starting}
                />
              )}
            />
          </div>
          {limitBy === 'date' ? (
                <div className="form-row">
                  <label htmlFor={`${selectId}-days`}>Download days in past</label>
                  <Controller
                    name="downloadDaysInPast"
                    control={control}
                    render={({field}) => (
                      <NumberInput
                        {...field}
                        id={`${selectId}-days`}
                        min={1}
                        step={1}
                        disabled={starting}
                        onChange={(event) => field.onChange(event.currentTarget.valueAsNumber)}
                        aria-invalid={!!errors.downloadDaysInPast}
                      />
                    )}
                  />
                  {errors.downloadDaysInPast && (
                    <div className="error" role="alert">{errors.downloadDaysInPast.message}</div>
                  )}
                </div>
              ) : limitBy === 'episodes' ? (
                <div className="form-row">
                  <label htmlFor={`${selectId}-count`}>Latest episodes to download</label>
                  <Controller
                    name="downloadEpisodeCount"
                    control={control}
                    render={({field}) => (
                      <NumberInput
                        {...field}
                        id={`${selectId}-count`}
                        min={1}
                        step={1}
                        disabled={starting}
                        onChange={(event) => field.onChange(event.currentTarget.valueAsNumber)}
                        aria-invalid={!!errors.downloadEpisodeCount}
                      />
                    )}
                  />
                  {errors.downloadEpisodeCount && (
                    <div className="error" role="alert">{errors.downloadEpisodeCount.message}</div>
                  )}
                </div>
              ) : (
                <div className="form-row">
                  <label htmlFor={`${selectId}-start`}>Download starting from</label>
                  <Controller
                    name="downloadStartingFrom"
                    control={control}
                    render={({field}) => (
                      <input
                        id={`${selectId}-start`}
                        className="input"
                        type="date"
                        value={field.value ?? ''}
                        name={field.name}
                        onChange={(event) => field.onChange(event.target.value || null)}
                        onBlur={field.onBlur}
                        ref={field.ref}
                        disabled={starting}
                        aria-invalid={!!errors.downloadStartingFrom}
                      />
                    )}
                  />
                  <div className="help">Optional. Leave blank to include all eligible {episode.plural}.</div>
                </div>
              )}
        </>
      )}
      <div className="form-row">
        <label htmlFor={`${selectId}-profile`}>Local Media Profile</label>
        <Controller
          name="localMediaProfileId"
          control={control}
          render={({field}) => (
            <SimpleSelect
              inputId={`${selectId}-profile`}
              registry={profileRegistry}
              value={field.value ? String(field.value) : null}
              onChange={(value) => field.onChange(Number(value))}
              onBlur={field.onBlur}
              isDisabled={starting || compatibleProfiles.length === 0}
              placeholder={compatibleProfiles.length ? 'Select a profile' : 'No compatible Local Media Profiles'}
              aria-invalid={!!errors.localMediaProfileId}
            />
          )}
        />
        {errors.localMediaProfileId && (
          <div className="error" role="alert">Select a Local Media Profile.</div>
        )}
      </div>
    </ConfirmDialog>
  )
}
