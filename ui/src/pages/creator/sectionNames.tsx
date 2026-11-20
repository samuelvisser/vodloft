import type {Names} from '../../types/schemas/source'
import {groupNames, joinedNames} from '../../types/creator'
import type {AccountSection} from './CreatorSectionsEditor'

/** One name for the sections, joined from the names each goes by among them: "playlists", "feeds and playlists". */
export function sectionNouns(items: AccountSection[]): Names {
    const sections = items.map(({section}) => section)
    const names = sections.map((section) => groupNames(section, sections))
    return joinedNames([...new Map(names.map((name) => [name.plural, name])).values()])
}

/** "Yacht Rebuild", or "12 playlists" or "3 feeds and playlists", in the words of the sections' Sites. */
export function namedSections(items: AccountSection[]): string {
    if (items.length === 1) return items[0].section.title
    return `${items.length.toLocaleString()} ${sectionNouns(items).plural}`
}

/** The titles of what a bulk action changes, the first few of them. */
export function TitleList({titles}: {titles: string[]}) {
    const shown = titles.slice(0, 6)
    return (
        <ul className="bulk-delete-list">
            {shown.map((title, index) => <li key={`${index}-${title}`}>{title}</li>)}
            {titles.length > shown.length && <li className="is-more">and {(titles.length - shown.length).toLocaleString()} more</li>}
        </ul>
    )
}
