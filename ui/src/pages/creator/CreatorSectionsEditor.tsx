import {useMemo, useState} from 'react'
import {useNavigate} from 'react-router-dom'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import {can} from '../../lib/access'
import {addCreatorSections, moveCreatorSection, splitCreatorAccount} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import NewCreatorCollectionDialog from './NewCreatorCollectionDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {capitalized, joinedNames} from '../../types/creator'
import {toImageUrl} from '../../components/Episode/EpisodeCard'
import type {CreatorPageAccountRead, CreatorPageRead, CreatorSectionRead, SectionPlan} from '../../types/schemas/creator'
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

/** The ways a section of a creator in the Library can be added, in the words of this creator. */
export function choices(creator: CreatorPageRead, {account, section}: AccountSection): {label: string, description: string, plan: SectionPlan}[] {
    const mainTitle = mainTitleOf(creator, account)
    const season = mainSeasonOf(creator, account)
    const main = `the ${creator.creatorNames.singular}'s main collection`
    const options: {label: string, description: string, plan: SectionPlan}[] = []
    if (isMovie(account, section)) {
        // A movie in the library joins the creator; another one goes into the library as one of theirs.
        return [section.movieSlug
            ? {label: `Join ${creator.title}`, description: `${section.movieTitle ?? section.title} in your library becomes one of ${creator.title}'s movies`, plan: {ref: section.ref, target: 'own'}}
            : {label: 'Add to your library', description: `The movie goes into your library, as one of ${creator.title}'s`, plan: {ref: section.ref, target: 'own'}}]
    }
    if (section.kind === 'feed') {
        options.push({label: `Add to ${mainTitle}`, description: `Its ${account.site.mediaNames.plural} go into ${main}`, plan: {ref: section.ref, target: 'main'}})
    } else if (section.kind === 'list' && account.site.linkSeasons) {
        options.push({label: `${season.Singular} of ${mainTitle}`, description: `${capitalized(season.a)} of ${main}`, plan: {ref: section.ref, target: 'main'}})
    }
    options.push({label: 'Own collection', description: 'A collection of its own in your library', plan: {ref: section.ref, target: 'own'}})
    return options
}

type Place = 'main' | 'own' | 'skip'

/** What moving a playlist does, in words, before the user says yes. */
function moveNote({account, section}: AccountSection, to: Place, mainTitle: string, season: Noun): string {
    const noun = section.names.singular
    const media = account.site.mediaNames.plural
    const others = account.site.creatorNames.plural
    if (to === 'own') {
        return `${section.title} becomes a collection of its own, and takes its ${media} out of ${mainTitle}. Downloaded ${media} `
            + 'take their files along, renamed into the new collection as manual downloads, since it has no Download '
            + 'Profiles yet.'
    }
    if (to === 'main') {
        return `${section.title} becomes ${season.a} of ${mainTitle}, and its ${media} move there. Downloaded ${media} take their `
            + `files along: renamed when ${mainTitle} downloads them with the same Local Media Profile or not at all, and `
            + `downloaded again there when it uses another one; the old files go once that succeeded. The collection `
            + `${section.collectionTitle ?? section.title} goes once it is empty.`
    }
    return `${section.title} is no longer ${season.a} of ${mainTitle}. Its ${media} go to the ${season.singular} of ${media} in no ${noun}, `
        + `and ${media} of other ${others} that only this ${noun} brought in leave ${mainTitle}, files and all. It stays listed `
        + 'on this page, so you can add it again.'
}

/** The places a playlist in the Library can go, in words. */
function placeLabels(mainTitle: string, season: Noun): Record<Place, string> {
    return {main: `${season.Singular} of ${mainTitle}`, own: 'Collection of its own', skip: 'Not in your library'}
}

/** Where one of the creator's playlists is, and a select to move it, with its videos, somewhere else. */
function SectionPlace({section, place, mainTitle, season, busy, fitLabels, onMove}: {
    section: CreatorSectionRead, place: Place, mainTitle: string, season: Noun, busy: boolean, fitLabels: readonly string[],
    onMove: (to: Place) => void,
}) {
    const registry = useMemo(() => {
        const labels = placeLabels(mainTitle, season)
        return createSelectRegistry(`SectionPlace-${place}-${mainTitle}-${season.singular}`, {
            main: {label: labels.main},
            own: {label: labels.own},
            ...(place === 'main' ? {skip: {label: labels.skip}} : {}),
        } as Record<Place, {label: string}>)
    }, [place, mainTitle, season])
    const inputId = `section-place-${section.ref}`
    return (
        <div className="creator-section-place">
            <label className="sr-only" htmlFor={inputId}>Where {section.title} goes</label>
            <SimpleSelect
                inputId={inputId} registry={registry} value={place} isDisabled={busy} fitLabels={fitLabels}
                menuPortalTarget={document.body} menuPlacement="auto"
                styles={{menuPortal: (base) => ({...base, zIndex: 1100})}}
                onChange={(value) => { if (value && value !== place) onMove(value as Place) }}
            />
        </div>
    )
}

/**
 * What the creator has on their Sites and where it is in the Library: new playlists and shows to decide on, where the
 * ones in the Library go, the ones not in it, and the creator's accounts.
 */
export default function CreatorSectionsEditor({creator, part}: {
    creator: CreatorPageRead
    /** The new playlists and shows waiting for a choice, or everything else. */
    part: 'new' | 'rest'
}) {
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const [busy, setBusy] = useState<string | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [moving, setMoving] = useState<{item: AccountSection, to: Place} | null>(null)
    const [sectionBusy, setSectionBusy] = useState(false)
    const [splitting, setSplitting] = useState<CreatorPageAccountRead | null>(null)
    // The section that becomes a collection of its own, while the user chooses its type and identification.
    const [adding, setAdding] = useState<AccountSection | null>(null)

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
    const moveSection = async () => {
        if (!moving) return
        setSectionBusy(true)
        try {
            const page = await moveCreatorSection(slug, moving.item.account.id, moving.item.section.ref, moving.to)
            queryClient.setQueryData(['creator', slug], page)
            await refresh()
            toast.success(`Moved ${moving.item.section.title}`)
            setMoving(null)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setSectionBusy(false)
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
    const placed = all.filter(({account, section}) => (
        account.site.linkSeasons && account.mainCollectionSlug && section.kind === 'list'
        && creator.collections.some((collection) => collection.slug === section.collectionSlug)
    ))
    const placeOf = ({account, section}: AccountSection): Place => section.collectionSlug === account.mainCollectionSlug ? 'main' : 'own'
    // Every select in the list is as wide as the longest choice of any of them, where the row has room for it.
    const placeChoiceLabels = placed.flatMap((item) => Object.values(placeLabels(mainTitleOf(creator, item.account), mainSeasonOf(creator, item.account))))
    const found = all.filter(({section}) => section.status === 'new' && !section.collectionSlug)
    // Movies that aren't the creator's yet are here too, so one hidden on the creator page can still be added.
    const left = all.filter(({account, section}) => section.status !== 'new' && (
        section.kind === 'item' ? isMovie(account, section) && !section.movieJoined : !section.collectionSlug
    ))
    const checkedAt = creator.accounts.map((account) => account.checkedAt).filter(Boolean).sort().pop()

    const sectionArt = (section: CreatorSectionRead) => section.imageUrl
        ? <img className="creator-section-art" src={toImageUrl(section.imageUrl)} alt="" loading="lazy"/>
        : <span className="creator-section-art" aria-hidden="true"><FontAwesomeIcon icon={faIcon('fass', section.kind === 'feed' ? 'rss' : section.kind === 'item' ? 'film' : 'list')}/></span>
    const facts = ({account, section}: AccountSection, ...more: (string | null)[]) => (
        [sectionFacts(section, account.site), several ? account.site.name : null, ...more].filter(Boolean).join(' · ')
    )
    const addButtons = (item: AccountSection, ignore: boolean) => mayAdd && (
        <div className="creator-row-actions">
            {choices(creator, item).map((choice) => (
                <button key={choice.label} type="button" className="btn" disabled={busy !== null}
                        onClick={() => choice.plan.target === 'own' && item.section.kind !== 'item' ? setAdding(item) : void place(item.account, choice.plan)}>
                    {busy === sectionKey(item.account, item.section.ref) ? 'Adding…' : choice.label}
                </button>
            ))}
            {ignore && (
                <button type="button" className="btn btn-link" disabled={busy !== null}
                        onClick={() => void place(item.account, {ref: item.section.ref, target: 'skip'})}>
                    Ignore
                </button>
            )}
        </div>
    )

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
                                {addButtons(item, true)}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {part === 'rest' && placed.length > 0 && (
                <div className="creator-section-group">
                    <h2>Where the {joinedNames(placed.map(({section}) => section.names)).plural} go</h2>
                    <div className="creator-section-list">
                        {placed.map((item) => {
                            const mainTitle = mainTitleOf(creator, item.account)
                            const season = mainSeasonOf(creator, item.account)
                            return (
                                <div key={sectionKey(item.account, item.section.ref)} className="creator-section-row">
                                    {sectionArt(item.section)}
                                    <div className="creator-section-copy">
                                        <b>{item.section.title}</b>
                                        <span>{facts(item)}</span>
                                    </div>
                                    {mayManage ? (
                                        <SectionPlace
                                            section={item.section} place={placeOf(item)} mainTitle={mainTitle} season={season} busy={sectionBusy}
                                            fitLabels={placeChoiceLabels}
                                            onMove={(to) => setMoving({item, to})}
                                        />
                                    ) : (
                                        <span className="creator-section-note">
                                            {placeLabels(mainTitle, season)[placeOf(item) === 'main' ? 'main' : 'own']}
                                        </span>
                                    )}
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}

            {part === 'rest' && left.length > 0 && (
                <div className="creator-section-group">
                    <h2>Not in your library</h2>
                    <div className="creator-section-list">
                        {left.map((item) => (
                            <div key={sectionKey(item.account, item.section.ref)} className="creator-section-row">
                                {sectionArt(item.section)}
                                <div className="creator-section-copy">
                                    <b>{item.section.title}</b>
                                    <span>
                                        {item.section.access
                                            ? 'Only some members can watch this.'
                                            : facts(item, item.section.movieSlug ? 'In your library' : null, item.section.status === 'ignored' ? 'Hidden on the creator page' : null)}
                                    </span>
                                </div>
                                {addButtons(item, false)}
                            </div>
                        ))}
                    </div>
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
                open={moving !== null}
                title={moving ? `Move ${moving.item.section.title}` : 'Move'}
                icon={faIcon('fass', 'arrow-right-arrow-left')}
                onDismiss={() => setMoving(null)}
                confirmButton={{label: sectionBusy ? 'Moving…' : 'Move', onClick: moveSection, disabled: sectionBusy}}
            >
                {moving && <p>{moveNote(moving.item, moving.to, mainTitleOf(creator, moving.item.account), mainSeasonOf(creator, moving.item.account))}</p>}
            </ConfirmDialog>

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

            {adding && <NewCreatorCollectionDialog creator={creator} item={adding} onDismiss={() => setAdding(null)}/>}
        </>
    )
}
