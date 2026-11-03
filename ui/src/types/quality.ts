import {createSelectRegistry} from '../utils/selectRegistry'

/** The "up to" steps of a Local Media Profile, lowest first, then Audio only (and HLS for The Daily Wire). */
export const LADDER_STEPS = [
    'format_360p', 'format_480p', 'format_720p', 'format_1080p', 'format_1440p', 'format_4k', 'format_8k',
] as const
export type LadderStep = (typeof LADDER_STEPS)[number]

export const QualityGoalReg = createSelectRegistry('QualityGoal', {
    compatibility: {label: 'Compatibility', help: 'H.264 in MP4. Plays on every device, also older TVs.'},
    quality: {label: 'Quality', help: 'The best the site has: AV1, then VP9. MKV.'},
    small: {label: 'Small files', help: 'AV1 first, then VP9. Needs a recent player.'},
    custom: {label: 'Your own', help: 'Choose the codecs and container below.'},
})
export type QualityGoal = (typeof QualityGoalReg)['values'][number]

export const VideoCodecReg = createSelectRegistry('VideoCodec', {
    av1: {label: 'AV1', help: 'Smallest files at the same quality. Plays on devices from about 2020 on.'},
    h264: {label: 'H.264', help: 'Plays on everything. Largest files.'},
    vp9: {label: 'VP9', help: 'YouTube’s usual codec. Not on older Apple devices.'},
    h265: {label: 'H.265 (HEVC)', help: 'Rare on video sites. Good on Apple and recent TVs.'},
})
export type VideoCodec = (typeof VideoCodecReg)['values'][number]
/** A small warning tag next to a codec that older devices can't play. */
export const CODEC_TAGS: Partial<Record<VideoCodec, string>> = {av1: 'Not on older TVs'}

export const CodecFallbackReg = createSelectRegistry('CodecFallback', {
    best: {label: 'Take the best version there is'},
    skip: {label: 'Skip the episode', help: 'The Collection page says why it was skipped.'},
})
export const ContainerReg = createSelectRegistry('VideoContainer', {
    mp4: {label: 'MP4'},
    mkv: {label: 'MKV'},
})
export const AudioCodecReg = createSelectRegistry('AudioCodec', {
    opus: {label: 'Opus'},
    aac: {label: 'AAC'},
})
export const AudioFormatReg = createSelectRegistry('AudioFormat', {
    m4a: {label: 'M4A (AAC)', help: 'Plays everywhere, including podcast apps and older Apple devices.'},
    opus: {label: 'Opus', help: 'Smallest at the same quality. Not every podcast app plays it.'},
    mp3: {label: 'MP3', help: 'For very old players. Converted, so a little quality is lost.'},
})

export type CodecChoice = {codec: VideoCodec; allowed: boolean}
type Preset = {videoCodecs: CodecChoice[]; container: 'mp4' | 'mkv'; audioCodec: 'aac' | 'opus'}

const MODERN: CodecChoice[] = [
    {codec: 'av1', allowed: true}, {codec: 'vp9', allowed: true}, {codec: 'h264', allowed: true}, {codec: 'h265', allowed: false},
]
/** What each goal stands for; the backend applies the same presets. */
export const GOAL_PRESETS: Record<Exclude<QualityGoal, 'custom'>, Preset> = {
    compatibility: {
        videoCodecs: [
            {codec: 'h264', allowed: true}, {codec: 'av1', allowed: false}, {codec: 'vp9', allowed: false}, {codec: 'h265', allowed: false},
        ],
        container: 'mp4',
        audioCodec: 'aac',
    },
    quality: {videoCodecs: MODERN, container: 'mkv', audioCodec: 'opus'},
    small: {videoCodecs: MODERN, container: 'mkv', audioCodec: 'opus'},
}

/** "AV1, then H.264, as MKV" */
export function codecSummary(codecs: readonly CodecChoice[], container: string): string {
    const allowed = codecs.filter((choice) => choice.allowed).map((choice) => VideoCodecReg.getLabelLoose(choice.codec))
    if (!allowed.length) return 'No codec allowed'
    return `${allowed.join(', then ')}, as ${container.toUpperCase()}`
}

export const SubtitleLanguageModeReg = createSelectRegistry('SubtitleLanguageMode', {
    listed: {label: 'Download every language on the list'},
    first: {label: 'Only the first one available'},
    site: {label: 'Every language the site offers', help: 'Can be dozens on YouTube when auto-generated subtitles are included.'},
})

export const AutoSubtitlesReg = createSelectRegistry('AutoSubtitles', {
    never: {label: 'Never'},
    fallback: {label: 'Only when there are no real ones'},
    always: {label: 'Always', help: 'As a track of its own next to a real one, marked auto-generated.'},
})

/** Languages to choose from by name; a code stays valid even when it isn't listed here. */
export const LANGUAGES: Record<string, string> = {
    en: 'English', nl: 'Dutch', de: 'German', fr: 'French', es: 'Spanish', it: 'Italian', pt: 'Portuguese',
    'pt-BR': 'Portuguese (Brazil)', sv: 'Swedish', no: 'Norwegian', da: 'Danish', fi: 'Finnish', pl: 'Polish',
    cs: 'Czech', hu: 'Hungarian', ro: 'Romanian', el: 'Greek', tr: 'Turkish', ru: 'Russian', uk: 'Ukrainian',
    ar: 'Arabic', he: 'Hebrew', hi: 'Hindi', id: 'Indonesian', ja: 'Japanese', ko: 'Korean', th: 'Thai',
    vi: 'Vietnamese', zh: 'Chinese', 'zh-Hans': 'Chinese (Simplified)', 'zh-Hant': 'Chinese (Traditional)',
}
export function languageName(code: string): string {
    return LANGUAGES[code] ?? code
}

export const AudioLanguageReg = createSelectRegistry(
    'AudioLanguage',
    {original: {label: 'Original'}, ...Object.fromEntries(Object.entries(LANGUAGES).map(([code, name]) => [code, {label: name}]))},
)
