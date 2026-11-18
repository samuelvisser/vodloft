import {type FieldValues, UseFormReturn} from 'react-hook-form'

import {LocalMediaProfileServerErrors} from '../../types/schemas/local_media_profile'
import type {LocalMediaProfileType} from '../../types/local_media_profile'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import LocalMediaProfileCommonFields from './LocalMediaProfileCommonFields'
import LocalMediaProfileSection from './LocalMediaProfileSection'
import MediaFilesFields from './MediaFilesFields'
import CollectionLocalMediaProfileForm from './CollectionLocalMediaProfileForm'
import ChaptersSection, {useOffersChapters} from './ChaptersSection'
import QualityField from './QualityField'
import SponsorBlockSection, {useOffersSponsorBlock} from './SponsorBlockSection'
import SubtitleFields, {useOffersSubtitles} from './SubtitleFields'
import VideoLocalMediaProfileForm from './VideoLocalMediaProfileForm'
import {useLocalMediaProfileSummaries} from './useLocalMediaProfileSummaries'
import {useSubtitleModeDefaults} from './useSubtitleModeDefaults'

type Props = {
    mode: LocalMediaProfileMode
    form: UseFormReturn<any>
    isCreating: boolean
}

export type LocalMediaProfileMode = 'collection' | 'video'

/** Which form a profile type uses: a Music profile is a Collection profile that keeps audio only. */
export function profileMode(type: LocalMediaProfileType): LocalMediaProfileMode {
    return type === 'video' ? 'video' : 'collection'
}

// The form fields in each section, so a section with an error opens.
const PROFILE_FIELDS = ['name', 'slug', 'collectionScope', 'siteKeys', 'includeUpcomingSites'] as const
const QUALITY_FIELDS = ['preferredFormat', 'qualityGoal', 'videoCodecs', 'codecFallback', 'container', 'audioCodec', 'audioFormat', 'audioLanguage'] as const
const FILES_FIELDS = ['thumbnailMode', 'metadataMode', 'kodiSafeNfo', 'showNfo', 'episodeNfo', 'downloadCollectionAssets', 'fileDateFromPublishDate', 'saveInfoJson', 'episodeTitleTemplate', 'episodeDescriptionTemplate', 'downloadMode'] as const
const SUBTITLE_FIELDS = ['subtitleMode', 'subtitleLanguageMode', 'subtitleLanguages', 'autoSubtitles'] as const
const SPONSORBLOCK_FIELDS = ['sponsorblockEnabled', 'sponsorblockSegments'] as const
const CHAPTER_FIELDS = ['keepChapters', 'cutChapters'] as const
const OUTPUT_FIELDS = ['outputTemplate', 'filenameRestrictionMode', 'indexingValues'] as const

export function buildLocalMediaProfileOnSubmit<TIn extends FieldValues, TOut extends FieldValues = TIn>(
    form: UseFormReturn<TIn>,
    submitFn: (data: TOut) => Promise<Response>,
    opts?: { mode?: 'create' | 'update'; onSuccess?: (result: any, ctx: any) => void }
) {
    const mode = opts?.mode ?? 'update'
    return buildServerAwareSubmit(form, submitFn, {
        onSuccess: opts?.onSuccess,
        successStatuses: mode === 'create' ? [201] : undefined,
        fallbackField: 'name' as any,
        mapMessage: LocalMediaProfileServerErrors,
        fieldAlias: {slug: 'name'},
    })
}

/**
 * The Local Media Profile form, in folding sections. A new profile opens the sections that need a choice; the others
 * start from good defaults and show their values while folded.
 */
export default function LocalMediaProfileForm({form, mode, isCreating}: Props) {
    const {register, formState: {errors}} = form
    const {onSubtitleModeChange, onScopeChange} = useSubtitleModeDefaults(form, mode, isCreating)
    const summaries = useLocalMediaProfileSummaries(form, mode)
    const offersSubtitles = useOffersSubtitles(form, mode)
    const offersSponsorBlock = useOffersSponsorBlock(form, mode)
    const offersChapters = useOffersChapters(form, mode)

    return (
        <>
            {errors.root && (
                <div className="form-error-card" role="alert" aria-live="polite">
                    {String(errors.root.message)}
                </div>
            )}

            {/* Hidden fields for id and slug to include them in submit when present */}
            <input type="hidden" {...register('id', {setValueAs: (v) => (v === '' || v == null ? undefined : Number(v))})} />
            <input type="hidden" {...register('slug')} />
            <input type="hidden" {...register('type')} />

            <LocalMediaProfileSection
                form={form} title="Profile" description="Name, where it is offered and for which Sites"
                summary={summaries.profile} fields={PROFILE_FIELDS} defaultOpen={isCreating}
            >
                <LocalMediaProfileCommonFields form={form} mode={mode} isCreating={isCreating} onScopeChange={onScopeChange}/>
            </LocalMediaProfileSection>

            <LocalMediaProfileSection
                form={form} title="Quality" description="How video and audio are downloaded"
                summary={summaries.quality} fields={QUALITY_FIELDS} defaultOpen={isCreating}
            >
                <QualityField form={form} mode={mode}/>
            </LocalMediaProfileSection>

            <LocalMediaProfileSection
                form={form} title="Files and metadata" description="What VODLoft saves besides the media"
                summary={summaries.files} fields={FILES_FIELDS}
            >
                <MediaFilesFields form={form} mode={mode}/>
            </LocalMediaProfileSection>

            {offersSubtitles && (
                <LocalMediaProfileSection
                    form={form} title="Subtitles" description="Which subtitles are saved, and where"
                    summary={summaries.subtitles} fields={SUBTITLE_FIELDS}
                >
                    <SubtitleFields form={form} mode={mode} onSubtitleModeChange={onSubtitleModeChange}/>
                </LocalMediaProfileSection>
            )}

            {offersChapters && (
                <LocalMediaProfileSection
                    form={form} title="Chapters" description="The chapters a video comes with"
                    summary={summaries.chapters} fields={CHAPTER_FIELDS}
                >
                    <ChaptersSection form={form} mode={mode}/>
                </LocalMediaProfileSection>
            )}

            {offersSponsorBlock && (
                <LocalMediaProfileSection
                    form={form} title="SponsorBlock" description="Sponsor reads and other parts of a video"
                    summary={summaries.sponsorblock} fields={SPONSORBLOCK_FIELDS}
                >
                    <SponsorBlockSection form={form} mode={mode}/>
                </LocalMediaProfileSection>
            )}

            <LocalMediaProfileSection
                form={form} title="Output path" description="Where files go and how they are named"
                summary={summaries.outputPath} fields={OUTPUT_FIELDS} defaultOpen={isCreating}
            >
                {mode === 'video' && <VideoLocalMediaProfileForm form={form}/>}
                {mode === 'collection' && <CollectionLocalMediaProfileForm form={form}/>}
            </LocalMediaProfileSection>
        </>
    )
}
