import {type UseFormReturn, useWatch} from 'react-hook-form'

import {useLocalMediaProfileSites} from '../../lib/queries'
import {useLibraryDefaults} from '../../lib/settings'
import {
    CollectionLocalMediaProfileScopeReg,
    FilenameRestrictionModeReg,
    type LocalMediaProfileType,
} from '../../types/local_media_profile'
import {AudioFormatReg, AudioLanguageReg, QualityDownloadReg, QualityGoalReg, languageName} from '../../types/quality'
import type {SponsorBlockSegments} from '../../types/schemas/local_media_profile_base'
import {sponsorBlockSummary} from './SponsorBlockSection'
import {chaptersSummary} from './ChaptersSection'
import {useOffersInfoFile} from './MediaFilesFields'

function where(value: string | undefined, inside: string, beside: string): string {
    if (!value) return 'not saved'
    const parts = [
        value === 'embed' || value.startsWith('embed_and') ? 'inside' : '',
        value === 'sidecar' || value === 'nfo' || value.endsWith('_and_sidecar') || value.endsWith('_and_nfo') ? beside : '',
    ].filter(Boolean)
    return parts.length ? parts.join(' and ') : inside
}

/** Each section's values in one line, for when it is folded. */
export function useLocalMediaProfileSummaries(form: UseFormReturn<any>, mode: LocalMediaProfileType) {
    const values = useWatch({
        control: form.control,
        name: [
            'name', 'collectionScope', 'siteKeys', 'includeUpcomingSites',
            'preferredFormat', 'qualityGoal', 'audioFormat', 'audioLanguage',
            'thumbnailMode', 'metadataMode', 'showNfo', 'downloadCollectionAssets', 'fileDateFromPublishDate',
            'subtitleMode', 'subtitleLanguages',
            'sponsorblockEnabled', 'sponsorblockSegments',
            'filenameRestrictionMode',
            'keepChapters', 'cutChapters', 'saveInfoJson', 'episodeNfo',
        ],
    }) as [
        string, string, string[] | null, boolean,
        string, string, string, string | null,
        string, string, boolean, boolean | null, boolean,
        string, string[] | undefined,
        boolean, SponsorBlockSegments | undefined,
        string,
        boolean | undefined, string[] | undefined, boolean | undefined, string | undefined,
    ]
    const [
        name, scope, siteKeys, upcoming,
        format, goal, audioFormat, audioLanguage,
        thumbnailMode, metadataMode, showNfo, collectionAssets, publishDates,
        subtitleMode, subtitleLanguages,
        sponsorblockEnabled, sponsorblockSegments,
        filenameMode,
        keepChapters, cutChapters, saveInfoJson, episodeNfo,
    ] = values
    const {data: sites} = useLocalMediaProfileSites()
    const {data: defaults} = useLibraryDefaults()
    const offersInfoFile = useOffersInfoFile(form, mode)
    const follows = (value: string | undefined) => (value ?? 'system') === 'system'

    const siteNames = (siteKeys ?? []).map((key) => sites?.sites.find((site) => site.key === key)?.name ?? key)
    const profile = [
        name || 'No name yet',
        mode === 'collection' ? CollectionLocalMediaProfileScopeReg.getLabelLoose(scope ?? 'podcast-and-series') : '',
        [...siteNames, ...(upcoming ? ['upcoming sites'] : [])].join(', '),
    ].filter(Boolean).join(' · ')

    const quality = [
        format === 'format_audio_only'
            ? `Audio only, ${AudioFormatReg.getLabelLoose(audioFormat)}`
            : format === 'format_hls'
                ? 'HLS bundle'
                : `Video up to ${QualityDownloadReg.getLabelLoose(format)}, ${QualityGoalReg.getLabelLoose(goal)}`,
        `${AudioLanguageReg.getLabelLoose(audioLanguage ?? 'original')} audio`,
    ].join(' · ')

    const thumbnail = follows(thumbnailMode) ? defaults?.thumbnailMode : thumbnailMode
    const metadata = follows(metadataMode) ? defaults?.metadataMode : metadataMode
    const files = [
        `Thumbnail ${thumbnail === 'no_thumbnail' ? 'not saved' : where(thumbnail, 'inside', 'beside')}${follows(thumbnailMode) ? ' (Settings)' : ''}`,
        `metadata ${metadata === 'no_metadata' ? 'not saved' : where(metadata, 'inside', 'as NFO')}${follows(metadataMode) ? ' (Settings)' : ''}`,
        mode === 'collection' && episodeNfo === 'music_video' ? 'as music videos' : '',
        mode === 'collection' && showNfo ? 'show NFO' : '',
        mode === 'collection' && (collectionAssets ?? defaults?.downloadCollectionAssets) ? 'poster and background' : '',
        publishDates ? 'dated by publish date' : '',
        saveInfoJson && offersInfoFile ? 'info file' : '',
    ].filter(Boolean).join(' · ')

    const subtitles = !subtitleMode || subtitleMode === 'no_subtitles'
        ? 'Not saved'
        : [
            where(subtitleMode, 'inside', 'beside').replace(/^./, (c) => c.toUpperCase()) + ' the media',
            (subtitleLanguages ?? []).map(languageName).join(', '),
        ].filter(Boolean).join(' · ')

    const sponsorblock = sponsorblockEnabled ? sponsorBlockSummary(sponsorblockSegments) : 'Off'

    const filenameLabel = follows(filenameMode)
        ? `${defaults ? FilenameRestrictionModeReg.getLabelLoose(defaults.filenameRestrictionMode) : 'Settings'} (Settings)`
        : FilenameRestrictionModeReg.getLabelLoose(filenameMode)
    const outputPath = `Filenames: ${filenameLabel}`

    const chapters = chaptersSummary(keepChapters, cutChapters)

    return {profile, quality, files, subtitles, sponsorblock, chapters, outputPath}
}
