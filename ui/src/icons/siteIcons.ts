import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {faIcon} from './faIcon'

/**
 * Every icon a Site contract names (its `icon`, as `prefix:name`), by that name. The Font Awesome compiler only
 * bundles icons it finds in a literal `faIcon()` call, so a Site's icon needs its entry here as well.
 */
const SITE_ICONS: Record<string, IconProp> = {
    'fab:bandcamp': faIcon('fab', 'bandcamp'),
    'fab:bilibili': faIcon('fab', 'bilibili'),
    'fab:dailymotion': faIcon('fab', 'dailymotion'),
    'fab:facebook': faIcon('fab', 'facebook'),
    'fab:instagram': faIcon('fab', 'instagram'),
    'fab:odysee': faIcon('fab', 'odysee'),
    'fab:patreon': faIcon('fab', 'patreon'),
    'fab:reddit': faIcon('fab', 'reddit'),
    'fab:soundcloud': faIcon('fab', 'soundcloud'),
    'fab:tiktok': faIcon('fab', 'tiktok'),
    'fab:twitch': faIcon('fab', 'twitch'),
    'fab:vimeo-v': faIcon('fab', 'vimeo-v'),
    'fab:x-twitter': faIcon('fab', 'x-twitter'),
    'fab:youtube': faIcon('fab', 'youtube'),
}

/** The Site's own icon, or null for a Site without one, which shows a globe with its initials (see SiteIcon). */
export function siteIcon(icon: string | null | undefined): IconProp | null {
    return icon ? SITE_ICONS[icon] ?? null : null
}
