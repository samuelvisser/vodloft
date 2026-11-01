/** How the user editor names areas and levels, and describes an access list in words. */
import type {Area, Level} from './access'
import type {SourceRead} from '../types/schemas/source'
import type {UserAccessInput} from '../types/schemas/user'

export const AREA_LABELS: Record<Area, {label: string, group: string, help: string}> = {
    library: {label: 'Library', group: 'Library', help: 'Collections, movies, videos and their episodes. Manage: edit, sync and delete them.'},
    add_media: {label: 'Add media', group: 'Library', help: 'Browse, search and add collections, movies and videos.'},
    managed_downloads: {label: 'Managed downloads', group: 'Downloads', help: 'The Downloads page. Manage: start, retry and cancel downloads.'},
    quick_downloads: {label: 'Quick downloads', group: 'Downloads', help: 'Quick download links as files. View: their own; Manage: everyone’s.'},
    download_profiles: {label: 'Download Profiles', group: 'Profiles', help: 'View: use them when adding media. Manage: create and change them.'},
    local_media_profiles: {label: 'Local Media Profiles', group: 'Profiles', help: 'View: use them when adding media. Manage: create and change them.'},
    stream_profiles: {label: 'Stream Profiles', group: 'Profiles', help: 'RSS feeds. View: their own feeds; Manage: everyone’s.'},
    tasks: {label: 'Tasks', group: 'VODLoft', help: 'Scheduled tasks and every operation. Without it, users see only their own operations.'},
    logs: {label: 'Log', group: 'VODLoft', help: 'The application log.'},
    settings: {label: 'Settings', group: 'VODLoft', help: 'Settings › General, Downloads, Quick download, Automation and Advanced.'},
    sources: {label: 'Sources', group: 'VODLoft', help: 'Settings › Sources: sign-ins, cookies, API keys. Needs Settings too.'},
    users: {label: 'Users (administrator)', group: 'VODLoft', help: 'Settings › Users. Gives every other area at its highest level.'},
}

export const LEVEL_LABELS: Record<Level, string> = {none: 'Hidden', view: 'View', manage: 'Manage'}

export function levelLabel(area: Area, level: Level): string {
    if (level === 'view' && (area === 'download_profiles' || area === 'local_media_profiles')) return 'Use'
    if (level === 'view' && area === 'add_media') return 'On'
    if (level === 'view' && (area === 'quick_downloads' || area === 'stream_profiles')) return 'Own'
    if (level === 'manage' && (area === 'quick_downloads' || area === 'stream_profiles')) return 'Everyone’s'
    return LEVEL_LABELS[level]
}

/** Sites people often limit yt-dlp to; picking one adds all its usual domains. */
export const DOMAIN_SUGGESTIONS: Array<{label: string, domains: string[]}> = [
    {label: 'YouTube', domains: ['youtube.com', 'youtu.be']},
    {label: 'Vimeo', domains: ['vimeo.com']},
    {label: 'Twitch', domains: ['twitch.tv']},
    {label: 'Rumble', domains: ['rumble.com']},
    {label: 'X', domains: ['x.com', 'twitter.com']},
    {label: 'Instagram', domains: ['instagram.com']},
    {label: 'TikTok', domains: ['tiktok.com']},
    {label: 'SoundCloud', domains: ['soundcloud.com']},
]

export function sourceTakesAnyDomain(source: SourceRead): boolean {
    return source.domains.includes('*')
}

/** The access list in plain words, for the summary under the editor. */
export function describeAccess(access: UserAccessInput, sources: SourceRead[], username = 'This user'): string[] {
    const lines: string[] = []
    if (access.levels.users === 'manage') {
        return [`${username} is an administrator: everything, including managing users.`]
    }
    const visible = (Object.keys(AREA_LABELS) as Area[])
        .filter((area) => (access.levels[area] ?? 'none') !== 'none')
        .map((area) => `${AREA_LABELS[area].label} (${levelLabel(area, access.levels[area] as Level).toLowerCase()})`)
    lines.push(visible.length ? `${username} sees ${visible.join(', ')}.` : `${username} sees nothing yet but their own account.`)
    if (access.levels.add_media !== 'none' || access.levels.quick_downloads !== 'none') {
        if (access.sources === null) {
            lines.push('They may use every Source.')
        } else if (access.sources.length === 0) {
            lines.push('They may not use any Source, so they cannot look up links.')
        } else {
            const names = access.sources.map((limit) => {
                const name = sources.find((source) => source.id === limit.sourceKey)?.name ?? limit.sourceKey
                return limit.domains ? `${name} on ${limit.domains.join(', ')}` : name
            })
            lines.push(`They may only use ${names.join('; ')}. Other links are refused with the reason.`)
        }
        lines.push(access.membersOnly ? 'They may use members-only media.' : 'They get only what a free account gets, not members-only media.')
    }
    if (access.deleteFiles) lines.push('They may delete downloaded files from disk.')
    return lines
}

/** ``https://www.YouTube.com/watch`` -> ``youtube.com``, as the server stores it. */
export function cleanDomain(value: string): string {
    let host = value.trim().toLowerCase()
    if (!host) return ''
    host = host.replace(/^[a-z][a-z0-9+.-]*:\/\//, '').split(/[/?#]/)[0].split(':')[0].replace(/^\.+/, '').replace(/\.+$/, '')
    return host.startsWith('www.') ? host.slice(4) : host
}
