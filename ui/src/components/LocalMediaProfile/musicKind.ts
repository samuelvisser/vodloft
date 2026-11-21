import {useWatch, type UseFormReturn} from 'react-hook-form'

import {useLocalMediaProfileView} from '../../lib/queries'
import {defaultSubtitleModeForProfile, musicKind, type CollectionLocalMediaProfileScope, type MusicKind} from '../../types/local_media_profile'
import {DEFAULT_COLLECTION_OUTPUT_TEMPLATE} from '../../types/schemas/collection_local_media_profile'
import {parseOutputTemplate, renderCompactOutputTemplate} from './outputTemplateFormatting'
import {outputTemplatePreset} from './outputTemplatePresets'

/** What a Collection profile keeps a Music collection as, by what it is available for and what it downloads. */
export type ProfileKind = {scope: string | null | undefined, format: string | null | undefined}

/** The preset a new profile for Music starts from, and the folder it starts in. */
const MUSIC_PRESETS: Record<Exclude<MusicKind, null>, {key: string, base: string}> = {
    tracks: {key: 'music', base: '/downloads/music'},
    music_videos: {key: 'music_videos', base: '/downloads/music-videos'},
}

function presetTemplate(kind: Exclude<MusicKind, null>): string {
    const {key, base} = MUSIC_PRESETS[kind]
    return renderCompactOutputTemplate(parseOutputTemplate(outputTemplatePreset(key)!.template(base), 'editor'))
}

/**
 * Sets what a Collection profile needs for what it now keeps of a Music collection: tracks are tagged audio, which may
 * be FLAC, and music videos get a musicvideo NFO. A new profile also starts from the preset that fits, and a saved one
 * keeps its own template. When the download changes, a new profile only moves to the other preset while its template
 * is still the preset it started from, so a template of your own stays. Returns the fields it changed.
 */
export function switchProfileKind(
    form: UseFormReturn<any>,
    previous: ProfileKind,
    next: ProfileKind,
    isCreating: boolean,
): string[] {
    const {getValues} = form
    const changed: string[] = []
    const options = {shouldDirty: true, shouldValidate: true}
    const setValue = (name: string, value: unknown) => {
        if (getValues(name) === value) return
        form.setValue(name, value, options)
        changed.push(name)
    }
    const was = musicKind(previous.scope, previous.format)
    const becomes = musicKind(next.scope, next.format)
    if (was === becomes) return changed
    // Only the download changed: a template of your own is kept.
    const ownTemplate = was !== null && becomes !== null && getValues('outputTemplate') !== presetTemplate(was)
    const startFrom = (kind: Exclude<MusicKind, null>) => {
        if (!isCreating || ownTemplate) return
        setValue('outputTemplate', presetTemplate(kind))
        for (const [name, value] of Object.entries(outputTemplatePreset(MUSIC_PRESETS[kind].key)!.choices)) setValue(name, value)
    }

    if (becomes === 'tracks') {
        // Tracks carry their cover art.
        if (isCreating) setValue('thumbnailMode', 'embed')
        startFrom('tracks')
    } else if (was === 'tracks' && getValues('audioFormat') === 'flac') {
        setValue('audioFormat', 'm4a')
    }
    if (becomes === 'music_videos') {
        setValue('episodeNfo', 'music_video')
        startFrom('music_videos')
    } else if (was === 'music_videos') {
        setValue('episodeNfo', 'episode')
    }
    if (isCreating && was !== null && becomes === null) {
        setValue('outputTemplate', DEFAULT_COLLECTION_OUTPUT_TEMPLATE)
    }
    // A new profile that keeps the subtitle default follows the new one, as when what it is available for changes.
    if (isCreating && previous.scope === next.scope) {
        const scope = next.scope as CollectionLocalMediaProfileScope
        if (getValues('subtitleMode') === defaultSubtitleModeForProfile('collection', scope, previous.format)) {
            setValue('subtitleMode', defaultSubtitleModeForProfile('collection', scope, next.format))
        }
    }
    return changed
}

/**
 * Whether a saved profile can still start or stop keeping music tracks. A profile for Music that downloads audio only
 * keeps tracks, so once a profile has downloads it can't switch between audio only and video while it is for Music,
 * though it can change between video qualities.
 */
export function useTracksLock(form: UseFormReturn<any>, isCreating: boolean) {
    const slug = useWatch({control: form.control, name: 'slug'}) as string | undefined
    const {data: view} = useLocalMediaProfileView(isCreating ? undefined : slug)
    const hasDownloads = !isCreating && (view?.statistics.managedMediaCount ?? 0) > 0
    const saved = view?.profile.type === 'collection' ? view.profile : undefined
    const savedTracks = musicKind(saved?.collectionScope, saved?.preferredFormat) === 'tracks'
    return {hasDownloads, savedTracks}
}

export const KEEPS_TRACKS_REASON = 'This profile already has downloaded music tracks, so it keeps downloading audio only. Duplicate it to start one for music videos.'
export const NO_TRACKS_REASON = 'This profile already has downloads, so it can\'t switch to audio only, which keeps music tracks. It can change between video qualities. Duplicate it to start one for tracks.'
