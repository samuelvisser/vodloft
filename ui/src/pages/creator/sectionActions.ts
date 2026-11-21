import type {Names} from '../../types/schemas/source'

/** What every menu and dropdown for a creator's feeds and lists calls each thing it can do with one, so they all
 * offer the same actions by the same names: the + menus and the bulk edit bar on the creator page, the dropdowns of
 * the Edit page, and the Add creator page. Where a section is now, such as "Season of Workshop", comes from
 * ``placeLabel``. */
export const SECTION_ACTIONS = {
    /** Into one of the creator's collections, their main one to start with, as a season or not: the dialog asks. */
    collection: 'Add to collection…',
    own: 'Collection of its own',
    /** Out of the library; one not in the library yet is also hidden on the creator page. */
    skip: 'Skip',
    /** Out of the library, and its videos blacklisted: out of every other collection of the creator, in the words of its Site,
     * such as tracks on SoundCloud. */
    keepOut: (media: Names) => `Blacklist its ${media.plural}`,
    show: 'Show on creator page',
} as const

/** The same actions for several sections at once, in the bulk edit bar. */
export const SECTIONS_ACTIONS = {
    own: 'Collections of their own',
    keepOut: (media: Names) => `Blacklist their ${media.plural}`,
} as const
