import {useRef, useState, type MouseEvent, type PointerEvent} from 'react'
import {capitalized, groupNames} from '../../types/creator'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addCreatorSections} from '../../lib/queries'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import CollectionTileArt from '../../components/CollectionTileArt/CollectionTileArt'
import ActionMenu from '../../components/ActionMenu/ActionMenu'
import type {CreatorPageRead, SectionPlan} from '../../types/schemas/creator'
import {choices, isMovie, placeMove, sectionFacts, type AccountSection} from './CreatorSectionsEditor'
import AnotherCollectionDialog, {otherCollections} from './AnotherCollectionDialog'
import NewCreatorCollectionDialog from './NewCreatorCollectionDialog'
import CreatorBulkBar from './CreatorBulkEdit'
import {PageHeaderAction} from '../../components/common/PageHeader'
import '../../components/ProfileBulkEdit/ProfileBulkEdit.css'

// Tiles shown before "Show all": two rows on a computer, two on a phone.
const DESKTOP_TILES = 12
const PHONE_TILES = 4

function listed(titles: string[]) {
    if (titles.length <= 3) return titles.length > 1 ? `${titles.slice(0, -1).join(', ')} and ${titles[titles.length - 1]}` : titles[0]
    return `${titles.slice(0, 3).join(', ')} and ${titles.length - 3} more`
}

/**
 * The creator's playlists or shows that are not in the Library: one folded line until the user opens it, then faded
 * Library tiles with a button that adds each one.
 */
export default function CreatorNotInLibrary({creator}: {creator: CreatorPageRead}) {
    const queryClient = useQueryClient()
    const items: AccountSection[] = creator.accounts
        .flatMap((account) => account.sections.map((section) => ({account, section})))
        // A movie that isn't one of the creator's yet, also when it is in the library, can join them from here. What
        // the user no longer wants to see here is only on the Edit page.
        .filter(({account, section}) => section.status !== 'ignored' && (
            section.kind === 'item' ? isMovie(account, section) && !section.movieJoined : !section.collectionSlug
        ))
        // The new ones, which wait for a choice, first.
        .sort((a, b) => Number(b.section.status === 'new') - Number(a.section.status === 'new'))
    const newCount = items.filter(({section}) => section.status === 'new').length
    // Folded each time the page opens; the summary says how many are new.
    const [open, setOpen] = useState(false)
    const [showAll, setShowAll] = useState(false)
    const [busy, setBusy] = useState<string | null>(null)
    // Bulk edit: whether it is on, and the keys of the chosen sections.
    const [selecting, setSelecting] = useState(false)
    const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
    // The section that becomes a collection of its own, while the user chooses its type and identification.
    const [adding, setAdding] = useState<AccountSection | null>(null)
    // The feed or list that goes into another of the creator's collections, while the user picks which.
    const [picking, setPicking] = useState<AccountSection | null>(null)
    // Whether a tile's menu was open when the pointer went down on the tile.
    const menuWasOpen = useRef(false)
    if (!items.length) return null

    const mayAdd = can('add_media')
    const sites = new Set(items.map(({account}) => account.site.key))
    const several = creator.accounts.length > 1
    // What is not in the library, by the type of section in the words of its Site: "1 more show", "2 more albums and
    // playlists", or "3 more feeds" for several types of feed.
    const counts = new Map<string, {count: number, singular: string, plural: string}>()
    const sections = items.map(({section}) => section)
    for (const section of sections) {
        const names = groupNames(section, sections)
        const known = counts.get(names.plural) ?? {count: 0, ...names}
        counts.set(names.plural, {...known, count: known.count + 1})
    }
    const kinds = [...counts.values()]
    const nouns = kinds.length === 1
        ? (items.length === 1 ? kinds[0].singular : kinds[0].plural)
        : `${kinds.slice(0, -1).map((kind) => kind.plural).join(', ')} and ${kinds[kinds.length - 1].plural}`
    const counted = `${items.length} more ${nouns}`
    const onSite = sites.size === 1 ? ` on ${items[0].account.site.name}` : ''
    const arts = items.map(({section}) => toImageUrl(section.imageUrl)).filter((url): url is string => !!url).slice(0, 4)
    const key = ({account, section}: AccountSection) => `${account.id}:${section.ref}`

    const toggle = () => {
        if (open) setSelecting(false)
        setOpen(!open)
    }
    const chosen = items.filter((item) => selected.has(key(item)))
    const startSelecting = () => {
        setSelected(new Set())
        setSelecting(true)
        setOpen(true)
    }
    const choose = (item: AccountSection) => {
        const next = new Set(selected)
        if (!next.delete(key(item))) next.add(key(item))
        setSelected(next)
    }
    const allChosen = chosen.length === items.length
    const chooseAll = () => setSelected(allChosen ? new Set() : new Set(items.map(key)))
    // A click anywhere on a tile does what its + does: add it, or open its menu. A click that only closes the open
    // menu leaves it closed.
    const tileDown = (event: PointerEvent<HTMLDivElement>) => {
        menuWasOpen.current = !!event.currentTarget.querySelector('.action-menu.is-open')
    }
    const tileClick = (event: MouseEvent<HTMLDivElement>) => {
        if (selecting) return
        if ((event.target as Element).closest('.creator-more-add') || menuWasOpen.current) return
        event.currentTarget.querySelector<HTMLButtonElement>('.creator-more-plus, .action-menu-trigger')?.click()
    }
    const add = async (item: AccountSection, plan: SectionPlan) => {
        // A movie needs no collection settings.
        if (plan.target === 'own' && item.section.kind !== 'item') {
            setAdding(item)
            return
        }
        setBusy(key(item))
        try {
            queryClient.setQueryData(['creator', creator.slug], await addCreatorSections(creator.slug, item.account.id, [plan]))
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                ...(item.section.kind === 'item' ? [queryClient.invalidateQueries({queryKey: ['movies']})] : []),
            ])
            if (plan.target !== 'exclude') toast.success(`Added ${item.section.title}`)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(null)
        }
    }

    const addButton = (item: AccountSection) => {
        const options = choices(creator, item)
        const isNew = item.section.status === 'new'
        if (busy === key(item)) {
            return <span className="btn btn-secondary creator-more-plus" aria-label="Adding…"><FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin/></span>
        }
        return (
            <ActionMenu
                label={`Add ${item.section.title}`} triggerIcon={faIcon('fass', 'plus')}
                items={[
                    ...options.map((option) => ({
                        label: option.label, description: option.description, disabled: busy !== null,
                        onSelect: () => void add(item, option.plan),
                    })),
                    ...(item.section.kind !== 'item' && otherCollections(creator, item).length > 0 ? [{
                        label: 'Another collection…', description: `Into one of ${creator.title}'s other collections`,
                        disabled: busy !== null, onSelect: () => setPicking(item),
                    }] : []),
                    {
                        label: 'Do not show here again',
                        description: `It leaves this list${isNew ? ' and stays out of your library' : ''}. You can still add it from the Edit page`,
                        separatorBefore: true, disabled: busy !== null,
                        onSelect: () => void add(item, {ref: item.section.ref, target: 'exclude'}),
                    },
                ]}
            />
        )
    }

    const titles = items.map(({section}) => section.title)
    // A movie in the library that isn't the creator's is only away from them.
    const away = items.some(({section}) => section.movieSlug) ? `not with ${creator.title}` : 'not in your library'
    return (
        <section className={`creator-more${open ? ' is-open' : ''}`} aria-label="Not in your library">
            <div className="creator-more-head">
            <button type="button" className="creator-more-summary" aria-expanded={open} onClick={toggle}>
                {arts.length > 0 && (
                    <span className="creator-more-stack" aria-hidden="true">
                        {arts.map((url) => <img key={url} src={url} alt="" loading="lazy"/>)}
                    </span>
                )}
                <span className="creator-more-text">
                    <b>
                        <span className="creator-more-long">{creator.title} has {counted}{onSite}</span>
                        <span className="creator-more-short">{counted}</span>
                        {newCount > 0 && <span className="creator-more-new">{newCount} new</span>}
                    </b>
                    <span className="creator-more-sub">
                        {open
                            ? `${capitalized(away)} yet${mayAdd ? `: add ${items.length === 1 ? 'it' : 'any of them'} with its + button` : ''}`
                            : `${listed(titles)} ${items.length === 1 ? 'is' : 'are'} ${away}`}
                    </span>
                </span>
            </button>
            {open && mayAdd && (
                <PageHeaderAction
                    icon={selecting ? faIcon('fass', 'check') : faIcon('fass', 'list-check')}
                    label={selecting ? 'Done' : 'Bulk edit'}
                    variant="secondary"
                    toggled={selecting}
                    onClick={selecting ? () => setSelecting(false) : startSelecting}
                />
            )}
            <button type="button" className="btn btn-secondary creator-more-toggle" aria-expanded={open} onClick={toggle} tabIndex={-1}>
                <span className="creator-more-toggle-label">{open ? 'Hide' : 'Show'}</span>
                <FontAwesomeIcon icon={faIcon('fass', open ? 'chevron-up' : 'chevron-down')} aria-hidden="true"/>
            </button>
            </div>
            {open && (
                <div className="creator-more-body">
                    {selecting && (
                        <div className="creator-more-select">
                            <label className="bulk-select-all">
                                <input
                                    type="checkbox" className="bulk-check" checked={allChosen}
                                    ref={(element) => { if (element) element.indeterminate = chosen.length > 0 && !allChosen }}
                                    onChange={chooseAll}
                                />
                                <span>{allChosen ? 'Deselect all' : 'Select all'}</span>
                            </label>
                            <b>{items.length} {nouns}</b>
                        </div>
                    )}
                    <div className={`creator-more-grid${showAll || selecting ? '' : ' is-cut'}`} role="list">
                        {items.map((item) => {
                            const image = toImageUrl(item.section.imageUrl)
                            const isChosen = selected.has(key(item))
                            const facts = [sectionFacts(item.section, item.account.site), item.section.movieSlug ? 'In your library' : null, several ? item.account.site.name : null].filter(Boolean).join(' · ')
                            return (
                                <div
                                    key={key(item)} role="listitem"
                                    className={`creator-more-tile${mayAdd ? ' is-addable' : ''}${selecting ? ' bulk-tile' : ''}${isChosen ? ' is-selected' : ''}`}
                                    onPointerDownCapture={mayAdd && !selecting ? tileDown : undefined}
                                    onClick={selecting ? () => choose(item) : mayAdd ? tileClick : undefined}
                                >
                                    <span className="library-tile-art creator-more-art">
                                        {image
                                            ? <CollectionTileArt key={image} src={image}/>
                                            : <span className="collection-art-placeholder"><FontAwesomeIcon icon={faIcon('fass', item.section.kind === 'feed' ? 'rss' : item.section.kind === 'item' ? 'film' : 'list')}/></span>}
                                    </span>
                                    {item.section.status === 'new' && <span className="creator-more-new creator-more-tile-new">New</span>}
                                    {selecting ? (
                                        <label className="creator-more-check" onClick={(event) => event.stopPropagation()}>
                                            <input
                                                type="checkbox" className="bulk-check" checked={isChosen}
                                                aria-label={`Choose ${item.section.title}`} onChange={() => choose(item)}
                                            />
                                        </label>
                                    ) : mayAdd && <div className="creator-more-add">{addButton(item)}</div>}
                                    <span className="library-tile-copy">
                                        <span className="library-tile-title">{item.section.title}</span>
                                        {facts && <span className="library-tile-meta"><span>{facts}</span></span>}
                                    </span>
                                </div>
                            )
                        })}
                    </div>
                    {!showAll && !selecting && items.length > PHONE_TILES && (
                        <div className={`creator-more-all${items.length > DESKTOP_TILES ? '' : ' is-phone-only'}`}>
                            <button type="button" className="btn btn-secondary" onClick={() => setShowAll(true)}>Show all {items.length}</button>
                        </div>
                    )}
                </div>
            )}
            {open && selecting && (
                <CreatorBulkBar
                    creator={creator} items={items} chosen={chosen}
                    onClear={() => setSelected(new Set())} onStop={() => setSelecting(false)}
                    onDone={(done) => setSelected((current) => {
                        const next = new Set(current)
                        for (const item of done) next.delete(key(item))
                        return next
                    })}
                />
            )}
            {picking && (
                <AnotherCollectionDialog
                    creator={creator} item={picking} confirmLabel="Add" onDismiss={() => setPicking(null)}
                    onPick={async (place) => { setPicking(null); await add(picking, {ref: picking.section.ref, ...placeMove(place)}) }}
                />
            )}
            {adding && <NewCreatorCollectionDialog creator={creator} items={[adding]} onDismiss={() => setAdding(null)}/>}
        </section>
    )
}
