import {useMemo, useState} from 'react'
import {useNavigate} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addCreatorSections, showCreatorSections, splitCreatorAccount} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import NewCreatorCollectionDialog from './NewCreatorCollectionDialog'
import {isWaitingList, useAnswerList} from './useAnswerList'
import AddToCollectionDialog, {collectionChoices, hasCollectionChoice} from './AddToCollectionDialog'
import CreatorBulkBar from './CreatorBulkEdit'
import {sectionNouns} from './sectionNames'
import {SECTION_ACTIONS} from './sectionActions'
import {PageHeaderAction} from '../../components/common/PageHeader'
import '../../components/ProfileBulkEdit/ProfileBulkEdit.css'
import ProgressSelect from '../../components/common/ProgressSelect'
import SimpleSelect from '../../components/common/SimpleSelect'
import {frontendOperationDefinitions} from '../../lib/operationDefinitions'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {capitalized, groupNames, joinedNames} from '../../types/creator'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import type {CreatorPageAccountRead, CreatorPageRead, CreatorSectionRead, SectionPlaces, SectionPlan} from '../../types/schemas/creator'
import type {Names} from '../../types/schemas/source'
import {collectionWords, type Noun} from '../../lib/collectionWords'

/** What the section is and holds, in the words of its Site: "Album · 12 tracks", "Playlist · 4 videos". */
export function sectionFacts(section: CreatorSectionRead, site: {mediaNames: Names}) {
    // A feed is named after its type already, so it only counts what it has in its own words: "12 shorts".
    const feed = section.kind === 'feed'
    const media = feed ? section.names : site.mediaNames
    return [feed ? null : capitalized(section.names.singular), section.itemCount != null ? `${section.itemCount} ${section.itemCount === 1 ? media.singular : media.plural}` : null]
        .filter(Boolean).join(' · ')
}

/** A single item that is a movie VODLoft adds from the creator's page, unlike a single track. */
export function isMovie(account: CreatorPageAccountRead, section: CreatorSectionRead) {
    return section.kind === 'item' && account.movies
}

/** One section of one of the creator's accounts. */
export type AccountSection = {account: CreatorPageAccountRead, section: CreatorSectionRead}

/** The title of the collection named after the creator that takes the account's uploads. */
export function mainTitleOf(creator: CreatorPageRead, account: CreatorPageAccountRead): string {
    return creator.collections.find((collection) => collection.slug === account.mainCollectionSlug)?.title ?? creator.title
}

/** What the collection named after the creator calls a season: an album in a Music collection. */
export function mainSeasonOf(creator: CreatorPageRead, account: CreatorPageAccountRead): Noun {
    return collectionWords(creator.collections.find((collection) => collection.slug === account.mainCollectionSlug)?.type).season
}

/** The ways a section of a creator in the Library can be added besides into one of the creator's collections, which
 * the Add to collection dialog asks for, in the words of this creator. */
export function choices(creator: CreatorPageRead, {account, section}: AccountSection): {label: string, description: string, plan: SectionPlan}[] {
    const options: {label: string, description: string, plan: SectionPlan}[] = []
    if (isMovie(account, section)) {
        // A movie in the library joins the creator; another one goes into the library as one of theirs.
        return [section.movieSlug
            ? {label: `Join ${creator.title}`, description: `${section.movieTitle ?? section.title} in your library becomes one of ${creator.title}'s movies`, plan: {ref: section.ref, target: 'own'}}
            : {label: 'Add to your library', description: `The movie goes into your library, as one of ${creator.title}'s`, plan: {ref: section.ref, target: 'own'}}]
    }
    options.push({label: SECTION_ACTIONS.own, description: 'A collection of its own in your library', plan: {ref: section.ref, target: 'own'}})
    return options
}

/** Where a feed or list goes: one of the targets, or main@<slug> and main_loose@<slug> for another of the creator's
 * collections, as a season of it or not. */
export type Place = string
type Target = SectionPlan['target']

/** The move to a place, as the API takes it. */
export function placeMove(place: Place): {target: Target, collectionSlug?: string} {
    const at = place.indexOf('@')
    return at < 0 ? {target: place as Target} : {target: place.slice(0, at) as Target, collectionSlug: place.slice(at + 1)}
}

/** The key of a feed or list of one of the creator's accounts, by which the Edit page keeps where it goes. */
export function placeKey(account: CreatorPageAccountRead, ref: string) {
    return `${account.id}:${ref}`
}

/** Where a feed or list in the Library is now: in the creator's own collection or another one that holds several,
 *  as a season or not, or in a collection of its own. */
export function placeOf({account, section}: AccountSection): Place {
    const target = section.asSeason === false ? 'main_loose' : 'main'
    if (section.collectionSlug === account.mainCollectionSlug) return target
    if (section.collectionSlug && account.gatheringSlugs.includes(section.collectionSlug)) return `${target}@${section.collectionSlug}`
    return 'own'
}

/** The feeds and lists in the Library whose place can change: a feed, and a list where lists can be seasons. */
export function placedSections(creator: CreatorPageRead): AccountSection[] {
    const all = creator.accounts.flatMap((account) => account.sections.map((section) => ({account, section})))
    return all.filter(({account, section}) => (
        account.mainCollectionSlug && creator.collections.some((collection) => collection.slug === section.collectionSlug)
        && (section.kind === 'feed' || (section.kind === 'list' && account.site.linkSeasons))
    )).sort((a, b) => Number(a.section.kind !== 'feed') - Number(b.section.kind !== 'feed'))
}

/** The choice that asks which of the creator's collections a feed or list goes into, and as what. */
const PICK = 'pick'


/** A place of a feed or a playlist, in words. */
export function placeLabel(creator: CreatorPageRead, {account, section}: AccountSection, place: Place): string {
    if (place === PICK) return SECTION_ACTIONS.collection
    const {target, collectionSlug} = placeMove(place)
    const collection = creator.collections.find((collection) => collection.slug === (collectionSlug ?? account.mainCollectionSlug))
    const title = collection?.title ?? creator.title
    const season = collectionWords(collection?.type).season
    return {
        main: section.kind === 'feed' ? `In ${title}` : `${season.Singular} of ${title}`,
        main_loose: `Add its contents to ${title}`,
        own: SECTION_ACTIONS.own,
        exclude: SECTION_ACTIONS.skip,
        keep_out: SECTION_ACTIONS.keepOut,
    }[target]
}

/** The places a feed or list can go from where it is: where it is and where the user moved it, the dialog that asks
 * for another collection or, for a list, whether it is a season there, a collection of its own, and out of the
 * Library. One in a collection of its own goes elsewhere by deleting that collection. The main feed, such as YouTube's
 * Videos, has the own collection's link, so it never goes anywhere else. */
function placeChoices(creator: CreatorPageRead, item: AccountSection, current: Place, value: Place): Place[] {
    const {section} = item
    const list = section.kind === 'list'
    const own = !(section.kind === 'feed' && section.role === 'main')
    const out = ['own', 'exclude', 'keep_out']
    return [...new Set([
        ...[current, value].filter((place) => !out.includes(place)),
        ...(hasCollectionChoice(creator, item, value) ? [PICK] : []),
        ...(own || current === 'own' ? ['own'] : []),
        ...(current !== 'own' ? ['exclude'] : []),
        // Its videos also leave the creator's other collections, such as a list of reuploads.
        ...(current !== 'own' && list ? ['keep_out'] : []),
    ])]
}

/** Where one of the creator's feeds or playlists goes. A change moves it when the Edit page is saved; while the
 * collection it moved to numbers its episodes again and renames their files, the field shows that progress. */
function SectionPlace({creator, item, current, value, fitLabels, collectionId, onChange, onPick}: {
    creator: CreatorPageRead, item: AccountSection, current: Place, value: Place, fitLabels: readonly string[],
    collectionId?: number, onChange: (to: Place) => void, onPick: () => void,
}) {
    const {account, section} = item
    const choices = placeChoices(creator, item, current, value)
    const registry = useMemo(() => createSelectRegistry(
        `SectionPlace-${account.id}-${section.ref}-${choices.join('-')}`,
        Object.fromEntries(choices.map((place) => [place, {label: placeLabel(creator, item, place)}])) as Record<Place, {label: string}>,
    ), [creator, item, choices.join('-')])
    const inputId = `section-place-${account.id}-${section.ref}`
    const key = placeKey(account, section.ref)
    return (
        <div className="creator-section-place">
            <label className="sr-only" htmlFor={inputId}>Where {section.title} goes</label>
            <ProgressSelect
                inputId={inputId} registry={registry} value={value} fitLabels={fitLabels}
                className={value !== current ? 'is-changed' : ''}
                menuPortalTarget={document.body} menuPlacement="auto"
                styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                definition={frontendOperationDefinitions['collection.renumber']}
                resourceId={collectionId}
                appliesTo={(operation) => {
                    const sections = operation.context?.sections
                    return Array.isArray(sections) && sections.includes(key)
                }}
                activeLabel={`Moving ${section.kind === 'feed' ? section.names.plural : account.site.mediaNames.plural}`}
                busyReason={`VODLoft is still moving ${section.title} into place: numbering the episodes again, renaming their files and rewriting their metadata.`}
                onChange={(place) => { if (place === PICK) onPick(); else if (place) onChange(place as Place) }}
            />
        </div>
    )
}

/**
 * What the creator has on their Sites and where it is in the Library: new playlists and shows to decide on, where the
 * ones in the Library go, the ones not in it, and the creator's accounts.
 */
export default function CreatorSectionsEditor({creator, part, places = {}, onPlace}: {
    creator: CreatorPageRead
    /** The new playlists and shows waiting for a choice, where the feeds and lists in the Library go, or everything
     * else. */
    part: 'new' | 'places' | 'rest'
    /** Where the user moved feeds and lists to, by ``placeKey``, saved with the Edit page. */
    places?: SectionPlaces
    /** The user picked a place; null when it is where it is now again. */
    onPlace?: (key: string, place: Place | null) => void
}) {
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const [busy, setBusy] = useState<string | null>(null)
    const [unhiding, setUnhiding] = useState<string | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [splitting, setSplitting] = useState<CreatorPageAccountRead | null>(null)
    // The section that becomes a collection of its own, while the user chooses its type and identification.
    const [adding, setAdding] = useState<AccountSection | null>(null)
    // The feed or list that goes into another of the creator's collections, while the user picks which.
    const [picking, setPicking] = useState<{item: AccountSection, place?: Place, confirm: string, pick: (place: Place) => void | Promise<void>} | null>(null)
    // Bulk edit of what is not in the library: whether it is on, and the keys of the chosen sections.
    const [selecting, setSelecting] = useState(false)
    const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())

    // A waiting list's answer moves its videos, so it asks through the move dialog first.
    const {answer, dialog: answerDialog} = useAnswerList(creator)
    const mayAdd = can('add_media')
    const mayManage = can('library', 'manage')
    const slug = creator.slug
    const sectionKey = (account: CreatorPageAccountRead, ref: string) => `${account.id}:${ref}`
    const refresh = async () => {
        await queryClient.invalidateQueries({queryKey: ['creators']})
        await queryClient.invalidateQueries({queryKey: ['collection']})
        await queryClient.invalidateQueries({queryKey: ['collectionsView']})
    }
    const place = async (account: CreatorPageAccountRead, plan: SectionPlan) => {
        setBusy(sectionKey(account, plan.ref))
        setActionError(null)
        try {
            queryClient.setQueryData(['creator', slug], await addCreatorSections(slug, account.id, [plan]))
            await refresh()
        } catch (exc) {
            setActionError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setBusy(null)
        }
    }
    // A section hidden on the creator page shows there again.
    const unhide = async ({account, section}: AccountSection) => {
        setUnhiding(sectionKey(account, section.ref))
        setActionError(null)
        try {
            queryClient.setQueryData(['creator', slug], await showCreatorSections(slug, account.id, [section.ref]))
            toast.success(`${section.title} shows on ${creator.title}'s page again`)
        } catch (exc) {
            setActionError(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setUnhiding(null)
        }
    }
    const split = async () => {
        if (!splitting) return
        try {
            const page = await splitCreatorAccount(slug, splitting.id)
            await queryClient.invalidateQueries({queryKey: ['creator', slug]})
            await refresh()
            toast.success(`${page.title} is a creator of their own now`)
            setSplitting(null)
            navigate(`/creator/${page.slug}`)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        }
    }

    const several = creator.accounts.length > 1
    const all: AccountSection[] = creator.accounts.flatMap((account) => account.sections.map((section) => ({account, section})))
    const placed = placedSections(creator)
    const placedFeeds = placed.filter(({section}) => section.kind === 'feed')
    const placedLists = placed.filter(({section}) => section.kind !== 'feed')
    // Every select in the list is as wide as the longest choice of any of them, where the row has room for it.
    const placeChoiceLabels = placed.flatMap((item) => placeChoices(creator, item, placeOf(item), places[placeKey(item.account, item.section.ref)] ?? placeOf(item)).map((place) => placeLabel(creator, item, place)))
    const collectionIdOf = (slug?: string | null) => creator.collections.find((collection) => collection.slug === slug)?.id
    const found = all.filter(({section}) => section.status === 'new' && !section.collectionSlug)
    // Movies that aren't the creator's yet are here too, so one hidden on the creator page can still be added.
    const left = all.filter(({account, section}) => section.status !== 'new' && (
        section.kind === 'item' ? isMovie(account, section) && !section.movieJoined : !section.collectionSlug
    ))
    const leftKey = ({account, section}: AccountSection) => sectionKey(account, section.ref)
    const chosen = left.filter((item) => selected.has(leftKey(item)))
    const allChosen = left.length > 0 && chosen.length === left.length
    const choose = (item: AccountSection) => setSelected((current) => {
        const next = new Set(current)
        if (!next.delete(leftKey(item))) next.add(leftKey(item))
        return next
    })
    const checkedAt = creator.accounts.map((account) => account.checkedAt).filter(Boolean).sort().pop()

    const sectionArt = (section: CreatorSectionRead) => section.imageUrl
        ? <img className="creator-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
        : <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : section.kind === 'item' ? 'film' : 'list')}/></span>
    const facts = ({account, section}: AccountSection, ...more: (string | null)[]) => (
        [sectionFacts(section, account.site), several ? account.site.name : null, ...more].filter(Boolean).join(' · ')
    )
    const placeRows = (items: AccountSection[]) => (
        <div className="creator-section-list">
            {items.map((item) => {
                const key = placeKey(item.account, item.section.ref)
                const current = placeOf(item)
                const value = places[key] ?? current
                // The option is named after what it does, so where it was says what it is.
                const {target, collectionSlug} = placeMove(current)
                const holder = creator.collections.find((collection) => collection.slug === (collectionSlug ?? item.account.mainCollectionSlug))
                const was = current === 'own' ? 'a collection of its own' : target === 'main_loose'
                    ? `its contents added to ${holder?.title ?? creator.title}`
                    : placeLabel(creator, item, current).replace(/^In /, 'in ')
                return (
                    <div key={key} className="creator-section-row">
                        {sectionArt(item.section)}
                        <div className="creator-section-copy">
                            <b>
                                {item.section.title}
                                {value !== current && <span className="creator-section-changed">Changed</span>}
                            </b>
                            <span>{facts(item, value !== current ? `Was ${was}` : null)}</span>
                        </div>
                        {mayManage && onPlace ? (
                            <SectionPlace
                                creator={creator} item={item} current={current} value={value}
                                fitLabels={placeChoiceLabels} collectionId={collectionIdOf(item.section.collectionSlug)}
                                onChange={(to) => onPlace(key, to === current ? null : to)}
                                onPick={() => setPicking({item, place: value, confirm: 'Choose', pick: (to) => onPlace(key, to === current ? null : to)})}
                            />
                        ) : (
                            <span className="creator-section-note">{placeLabel(creator, item, current)}</span>
                        )}
                    </div>
                )
            })}
        </div>
    )
    // What the user can do with a section not in the library, in one select: the same actions as its + menu on the
    // creator page. Not in the library, a section is skipped or keeps its videos out already, so that one shows as its
    // choice, and choosing it again does nothing; a new one waits for a choice.
    const actionsOf = (item: AccountSection, ignore: boolean) => {
        const {account, section} = item
        const now = ignore || section.movieSlug ? null : section.status === 'kept_out' ? 'keep_out' : 'skip'
        const actions: {key: string, label: string, run: () => void}[] = []
        if (collectionChoices(creator, item).length > 0) {
            actions.push({
                key: 'collection', label: SECTION_ACTIONS.collection,
                run: () => setPicking({item, confirm: isWaitingList(item) ? 'Next' : 'Add', pick: (to) => isWaitingList(item)
                    ? answer(item, placeMove(to), placeLabel(creator, item, to))
                    : place(account, {ref: section.ref, ...placeMove(to)})}),
            })
        }
        actions.push(...choices(creator, item).map((choice, index) => ({
            key: `choice-${index}`, label: choice.label,
            run: () => choice.plan.target === 'own' && section.kind !== 'item'
                ? setAdding(item)
                : isWaitingList(item)
                    ? answer(item, {target: choice.plan.target}, choice.label)
                    : void place(account, choice.plan),
        })))
        if (!section.movieSlug) {
            actions.push({key: 'skip', label: SECTION_ACTIONS.skip, run: () => now !== 'skip' && void place(account, {ref: section.ref, target: 'exclude'})})
        }
        if (section.kind === 'list') {
            actions.push({
                key: 'keep_out', label: SECTION_ACTIONS.keepOut,
                run: () => now !== 'keep_out' && answer(item, {target: 'keep_out'}, SECTION_ACTIONS.keepOut),
            })
        }
        if (section.status === 'ignored') actions.push({key: 'show', label: SECTION_ACTIONS.show, run: () => void unhide(item)})
        return {actions, now}
    }
    const actionSelect = (item: AccountSection, ignore: boolean) => {
        if (!mayAdd) return null
        const key = sectionKey(item.account, item.section.ref)
        const {actions, now: current} = actionsOf(item, ignore)
        const registry = createSelectRegistry(
            `SectionAction-${key}-${actions.map((action) => action.label).join('-')}`,
            Object.fromEntries(actions.map((action) => [action.key, {label: action.label}])),
        )
        const working = busy === key || unhiding === key
        return (
            <div className="creator-section-choice">
                <SimpleSelect
                    aria-label={`What to do with ${item.section.title}`} registry={registry} value={working ? null : current}
                    placeholder={working ? 'Working…' : 'Choose…'} isLoading={working}
                    isDisabled={busy !== null || unhiding !== null}
                    menuPortalTarget={document.body} menuPlacement="auto"
                    styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                    onChange={(value) => actions.find((action) => action.key === value)?.run()}
                />
            </div>
        )
    }

    return (
        <>
            {actionError && <div className="form-error-card" role="alert">{actionError}</div>}

            {part === 'new' && found.length > 0 && (
                <div className="creator-section-group" id="new">
                    <h2>New on {creator.title}</h2>
                    <div className="creator-section-list creator-section-list--new">
                        {found.map((item) => (
                            <div key={sectionKey(item.account, item.section.ref)} className="creator-section-row" role="region" aria-label={`New: ${item.section.title}`}>
                                {sectionArt(item.section)}
                                <div className="creator-section-copy">
                                    <b>{item.section.title}</b>
                                    <span>{facts(item) || `Found on ${creator.title}`}</span>
                                </div>
                                {actionSelect(item, true)}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {part === 'places' && placed.length > 0 && (
                <div className="creator-section-group">
                    <h2>Where the {joinedNames(placed.map(({section}) => groupNames(section, placed.map((item) => item.section)))).plural} go</h2>
                    {placedFeeds.length > 0 && placedLists.length > 0 ? (
                        <>
                            <h3 className="creator-section-subhead">{capitalized(joinedNames(placedFeeds.map(({section}) => groupNames(section, placed.map((item) => item.section)))).plural)}</h3>
                            {placeRows(placedFeeds)}
                            <h3 className="creator-section-subhead">{capitalized(joinedNames(placedLists.map(({section}) => section.names)).plural)}</h3>
                            {placeRows(placedLists)}
                        </>
                    ) : placeRows(placed)}
                    {mayManage && onPlace && (
                        <div className="help">
                            A change moves when you save. VODLoft first shows what it does to the {creator.words.episode.plural} and their files.
                        </div>
                    )}
                </div>
            )}

            {part === 'rest' && left.length > 0 && (
                <div className="creator-section-group">
                    <div className="creator-section-group-head">
                        <h2>Not in your library</h2>
                        {mayAdd && (
                            <PageHeaderAction
                                icon={selecting ? faIcon('fass', 'check') : faIcon('fass', 'list-check')}
                                label={selecting ? 'Done' : 'Bulk edit'}
                                variant="secondary"
                                toggled={selecting}
                                onClick={() => { setSelected(new Set()); setSelecting(!selecting) }}
                            />
                        )}
                    </div>
                    {selecting && (
                        <div className="creator-more-select">
                            <label className="bulk-select-all">
                                <input
                                    type="checkbox" className="bulk-check" checked={allChosen}
                                    ref={(element) => { if (element) element.indeterminate = chosen.length > 0 && !allChosen }}
                                    onChange={() => setSelected(allChosen ? new Set() : new Set(left.map(leftKey)))}
                                />
                                <span>{allChosen ? 'Deselect all' : 'Select all'}</span>
                            </label>
                            <b>{left.length} {sectionNouns(left).plural}</b>
                        </div>
                    )}
                    <div className="creator-section-list">
                        {left.map((item) => (
                            <div
                                key={leftKey(item)}
                                className={`creator-section-row${selecting ? ' bulk-row' : ''}${selected.has(leftKey(item)) ? ' is-selected' : ''}`}
                                onClick={selecting ? () => choose(item) : undefined}
                            >
                                {selecting && (
                                    <input
                                        type="checkbox" className="bulk-check" checked={selected.has(leftKey(item))}
                                        aria-label={`Choose ${item.section.title}`}
                                        onClick={(event) => event.stopPropagation()} onChange={() => choose(item)}
                                    />
                                )}
                                {sectionArt(item.section)}
                                <div className="creator-section-copy">
                                    <b>{item.section.title}</b>
                                    <span>
                                        {item.section.access
                                            ? 'Only some members can watch this.'
                                            : facts(item, item.section.movieSlug ? 'In your library' : null, item.section.status === 'ignored' ? 'Hidden on the creator page' : null, item.section.status === 'kept_out' ? 'Keeps its videos out' : null)}
                                    </span>
                                </div>
                                {!selecting && actionSelect(item, false)}
                            </div>
                        ))}
                    </div>
                    {selecting && (
                        <CreatorBulkBar
                            creator={creator} items={left} chosen={chosen} onEdit
                            onClear={() => setSelected(new Set())} onStop={() => setSelecting(false)}
                            onDone={(done) => setSelected((current) => {
                                const next = new Set(current)
                                for (const item of done) next.delete(leftKey(item))
                                return next
                            })}
                        />
                    )}
                </div>
            )}

            {part === 'rest' && several && (
                <div className="creator-section-group">
                    <h2>Accounts</h2>
                    <div className="creator-section-list">
                        {creator.accounts.map((account) => (
                            <div key={account.id} className="creator-section-row">
                                <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', 'circle-user')}/></span>
                                <div className="creator-section-copy">
                                    <b>{account.site.name}</b>
                                    <span>{[account.handle, `${account.sections.length} ${account.sections.length === 1 ? 'section' : 'sections'}`].filter(Boolean).join(' · ')}</span>
                                </div>
                                {mayManage && (
                                    <div className="creator-row-actions">
                                        <button type="button" className="btn" onClick={() => setSplitting(account)}>Split off</button>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {part === 'rest' && checkedAt && (
                <p className="creator-note">
                    VODLoft looks for new {creator.newListNames.plural} once a day. Last look: {new Date(checkedAt).toLocaleString()}.
                </p>
            )}

            <ConfirmDialog
                open={splitting !== null}
                title={splitting ? `Split ${splitting.site.name} off ${creator.title}` : 'Split off'}
                icon={faIcon('fass', 'object-ungroup')}
                onDismiss={() => setSplitting(null)}
                confirmButton={{label: 'Split off', onClick: split}}
            >
                {splitting && (
                    <ul className="creator-order-note">
                        <li>The account on {splitting.site.name} becomes a creator of its own, named as {splitting.site.name} names them.</li>
                        <li>Its own collection and the collections of its {splitting.site.sectionGrowingNames.plural} go along. Collections that joined {creator.title} by another link stay.</li>
                        <li>Collections keep their {creator.words.season.plural}, {creator.words.episode.plural}, profiles and files. Nothing is indexed again.</li>
                    </ul>
                )}
            </ConfirmDialog>

            {picking && (
                <AddToCollectionDialog
                    creator={creator} item={picking.item} place={picking.place} confirmLabel={picking.confirm} onDismiss={() => setPicking(null)}
                    onPick={async (to) => { await picking.pick(to); setPicking(null) }}
                />
            )}
            {adding && (
                <NewCreatorCollectionDialog
                    creator={creator} items={[adding]} onDismiss={() => setAdding(null)}
                    onChoose={isWaitingList(adding) ? (values) => {
                        answer(adding, {target: 'own', type: values.type, episodeIdentifier: values.episodeIdentifier}, SECTION_ACTIONS.own)
                        setAdding(null)
                    } : undefined}
                />
            )}
            {answerDialog}
        </>
    )
}
