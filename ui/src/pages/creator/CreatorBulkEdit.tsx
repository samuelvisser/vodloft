import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import type {IconProp} from '@fortawesome/fontawesome-svg-core'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import {addCreatorSections, showCreatorSections} from '../../lib/queries'
import {capitalized, joinedNames} from '../../types/creator'
import type {CreatorPageRead} from '../../types/schemas/creator'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import {BulkBar} from '../../components/ProfileBulkEdit/BulkEditControls'
import {isMovie, mainSeasonOf, mainTitleOf, placeLabel, placeMove, type AccountSection, type Place} from './CreatorSectionsEditor'
import NewCreatorCollectionDialog from './NewCreatorCollectionDialog'
import AnotherCollectionDialog, {otherCollections} from './AnotherCollectionDialog'
import {TitleList, namedSections, sectionNouns} from './sectionNames'
import {isWaitingList, useAnswerList} from './useAnswerList'

type BulkAction = {
    id: 'main' | 'contents' | 'own' | 'another' | 'movie' | 'skip' | 'keep_out' | 'show'
    label: string
    icon: IconProp
    /** The chosen sections the action applies to. */
    items: AccountSection[]
}

/** What can be done with the chosen sections, each with the ones it applies to: the choices of each section's + menu. */
function bulkActions(creator: CreatorPageRead, chosen: AccountSection[], onEdit: boolean): BulkAction[] {
    const movies = chosen.filter(({account, section}) => isMovie(account, section))
    const sections = chosen.filter(({account, section}) => !isMovie(account, section))
    const toMain = sections.filter(({account, section}) => section.kind === 'feed' || (section.kind === 'list' && account.site.linkSeasons))
    const contents = sections.filter(({account, section}) => section.kind === 'list' && account.site.linkSeasons)
    // Another collection of the creator: the ones of one account, which share its collections.
    const gatherable = sections.filter((item) => otherCollections(creator, item).length > 0)
    const another = gatherable.filter(({account}) => account.id === gatherable[0]?.account.id)
    const lists = sections.filter(({section}) => section.kind === 'list')
    // Those already hidden on the creator page stay hidden.
    const hideable = chosen.filter(({section}) => section.status !== 'ignored')
    const hidden = chosen.filter(({section}) => section.status === 'ignored')
    const mains = new Set(toMain.map(({account}) => mainTitleOf(creator, account)))
    const mainLabel = () => {
        if (mains.size !== 1) return 'Add to main collections'
        const main = [...mains][0]
        if (toMain.every(({section}) => section.kind === 'list')) return `${mainSeasonOf(creator, toMain[0].account).Plural} of ${main}`
        return `Add to ${main}`
    }
    const movieLabel = () => {
        if (movies.every(({section}) => section.movieSlug)) return `Join ${creator.title}`
        if (movies.every(({section}) => !section.movieSlug)) return 'Add to your library'
        return `Add ${joinedNames([...new Map(movies.map(({section}) => [section.names.plural, section.names])).values()]).plural}`
    }
    const contentsMains = new Set(contents.map(({account}) => mainTitleOf(creator, account)))
    const actions: (BulkAction | false)[] = [
        toMain.length > 0 && {id: 'main', label: mainLabel(), icon: faIcon('fass', 'plus'), items: toMain},
        contents.length > 0 && {
            id: 'contents', label: contentsMains.size === 1 ? `Add contents to ${[...contentsMains][0]}` : 'Add contents to main collections',
            icon: faIcon('fass', 'layer-group'), items: contents,
        },
        sections.length > 0 && {
            id: 'own', label: sections.length === 1 ? 'Own collection' : 'Own collections', icon: faIcon('fass', 'folder-plus'),
            items: sections,
        },
        another.length > 0 && {id: 'another', label: 'Another collection…', icon: faIcon('fass', 'folder-tree'), items: another},
        movies.length > 0 && {id: 'movie', label: movieLabel(), icon: faIcon('fass', 'film'), items: movies},
        hideable.length > 0 && {
            id: 'skip', label: onEdit ? 'Hide on creator page' : 'Do not show here again', icon: faIcon('fass', 'eye-slash'), items: hideable,
        },
        lists.length > 0 && {id: 'keep_out', label: lists.length === 1 ? 'Keep its videos out' : 'Keep their videos out', icon: faIcon('fass', 'ban'), items: lists},
        hidden.length > 0 && {id: 'show', label: 'Show on creator page', icon: faIcon('fass', 'eye'), items: hidden},
    ]
    return actions.filter((action): action is BulkAction => !!action)
}

/** What an action does, in words, before the user says yes. */
function ActionNote({creator, action, onEdit}: {creator: CreatorPageRead, action: BulkAction, onEdit: boolean}) {
    const {items} = action
    if (action.id === 'main') {
        const main = mainTitleOf(creator, items[0].account)
        const feeds = items.filter(({section}) => section.kind === 'feed')
        const lists = items.filter(({section}) => section.kind === 'list')
        const season = mainSeasonOf(creator, items[0].account)
        const listed = (titles: string[]) => titles.length === 1 ? titles[0] : `${titles.slice(0, -1).join(', ')} and ${titles[titles.length - 1]}`
        const listNoun = joinedNames([...new Map(lists.map(({section}) => [section.names.singular, section.names])).values()]).singular
        const parts = [
            feeds.length > 0 && `${listed(feeds.map(({section}) => section.title))} ${feeds.length === 1 ? 'goes' : 'go'} into ${main}`,
            lists.length === 1 && `${lists[0].section.title} becomes ${season.a} of ${main}`,
            lists.length > 1 && `each ${listNoun} becomes ${season.a} of ${main}`,
        ].filter((part): part is string => !!part)
        return (
            <p>
                {capitalized(parts.join(', and '))}. VODLoft keeps adding what {creator.title} puts in {items.length === 1 ? 'it' : 'them'}.
            </p>
        )
    }
    if (action.id === 'contents') {
        const main = mainTitleOf(creator, items[0].account)
        const season = mainSeasonOf(creator, items[0].account)
        return (
            <p>
                {items.length === 1 ? `${items[0].section.title}'s` : 'Their'} {items[0].account.site.mediaNames.plural} join the others in {main},
                without {season.a} of their own. VODLoft keeps adding what {creator.title} puts in {items.length === 1 ? 'it' : 'them'}.
            </p>
        )
    }
    if (action.id === 'movie') {
        const owned = items.filter(({section}) => section.movieSlug).length
        const added = items.length - owned
        return (
            <p>
                {added > 0 && `${added === items.length ? (items.length === 1 ? 'It goes' : 'They go') : `${added} of them go`} into your library, as ${creator.title}'s. `}
                {owned > 0 && `${owned === items.length ? (items.length === 1 ? 'It is' : 'They are') : `${owned} are`} in your library already and become ${creator.title}'s.`}
            </p>
        )
    }
    if (action.id === 'show') {
        return (
            <p>
                {items.length === 1 ? 'It shows' : 'They show'} on {creator.title}'s page again, under what is not in your library, and
                {' '}{items.length === 1 ? 'stays' : 'stay'} out of your library.
            </p>
        )
    }
    const isNew = items.some(({section}) => section.status === 'new')
    const them = items.length === 1 ? 'it' : 'them'
    if (onEdit) {
        return (
            <p>
                {items.length === 1 ? 'It no longer shows' : 'They no longer show'} on {creator.title}'s page{isNew ? ' and stay out of your library' : ''}.
                {' '}{items.length === 1 ? 'It stays' : 'They stay'} in this list, so you can still add {them} here.
            </p>
        )
    }
    return (
        <p>
            {items.length === 1 ? 'It leaves' : 'They leave'} this list{isNew ? `${items.length === 1 ? ' and stays' : ', and the new ones stay'} out of your library` : ''}.
            {' '}You can still add {them} from the Edit page.
        </p>
    )
}

const TARGETS: Record<'main' | 'contents' | 'movie' | 'skip', 'main' | 'main_loose' | 'own' | 'exclude'> = {
    main: 'main', contents: 'main_loose', movie: 'own', skip: 'exclude',
}

/** The actions that move a list's videos: a list that waits for the user's choice goes through the move dialog. */
const MOVING = new Set<BulkAction['id']>(['main', 'contents'])

/**
 * The bar of actions for the creator's chosen sections that are not in the Library, and what each opens: a question
 * first, or, for collections of their own, the dialog that asks for their type.
 */
export default function CreatorBulkBar({creator, items, chosen, onEdit = false, onClear, onStop, onDone}: {
    creator: CreatorPageRead
    /** On the creator's Edit page, where hiding a section keeps it in the list. */
    onEdit?: boolean
    /** Every section in the list, for the actions shown while none is chosen. */
    items: AccountSection[]
    chosen: AccountSection[]
    onClear: () => void
    onStop: () => void
    /** The sections an action took care of, which leave the list. */
    onDone: (items: AccountSection[]) => void
}) {
    const queryClient = useQueryClient()
    const [confirming, setConfirming] = useState<BulkAction | null>(null)
    const [owning, setOwning] = useState<AccountSection[] | null>(null)
    const [picking, setPicking] = useState<BulkAction | null>(null)
    // Lists that wait for the user's choice, and keeping lists out, move their videos, so the move dialog asks first.
    const {answerAll, dialog: answerDialog} = useAnswerList(creator, onDone)
    const none = chosen.length === 0
    // While none is chosen, the bar shows what the list's sections can have, unavailable.
    const actions = bulkActions(creator, none ? items : chosen, onEdit)
    const nouns = sectionNouns(items).plural

    /** Add ``items`` at ``place``: the ones that wait for a choice through the move dialog, the others at once. */
    const apply = async (action: BulkAction, place?: Place) => {
        const waiting = MOVING.has(action.id) || place ? action.items.filter(isWaitingList) : []
        const now = action.items.filter((item) => !waiting.includes(item))
        if (now.length) await add(action, now, place)
        else setConfirming(null)
        if (waiting.length) {
            const to = place ?? TARGETS[action.id as keyof typeof TARGETS]
            answerAll(waiting, placeMove(to), (item) => placeLabel(creator, item, to))
        }
    }

    const add = async (action: BulkAction, items: AccountSection[], place?: Place) => {
        try {
            for (const id of new Set(items.map(({account}) => account.id))) {
                const refs = items.filter(({account}) => account.id === id).map(({section}) => section.ref)
                queryClient.setQueryData(['creator', creator.slug], action.id === 'show'
                    ? await showCreatorSections(creator.slug, id, refs)
                    : await addCreatorSections(creator.slug, id, refs.map((ref) => (
                        {ref, ...placeMove(place ?? TARGETS[action.id as keyof typeof TARGETS])}
                    ))))
            }
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                ...(action.id === 'movie' ? [queryClient.invalidateQueries({queryKey: ['movies']})] : []),
            ])
            const named = namedSections(items)
            toast.success(
                action.id === 'skip' ? `Hid ${named} on ${onEdit ? `${creator.title}'s page` : 'this page'}`
                    : action.id === 'show' ? `${named} ${items.length === 1 ? 'shows' : 'show'} on ${creator.title}'s page again`
                        : `Added ${named}`,
            )
            onDone(items)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setConfirming(null)
        }
    }

    const choose = (action: BulkAction) => {
        if (action.id === 'own') setOwning(action.items)
        else if (action.id === 'another') setPicking(action)
        else if (action.id === 'keep_out') answerAll(action.items, {target: 'keep_out'}, 'Skip, and keep its videos out')
        // The move dialog asks instead, when every one waits for a choice.
        else if (MOVING.has(action.id) && action.items.every(isWaitingList)) void apply(action)
        else setConfirming(action)
    }

    const title = (action: BulkAction) => {
        const named = namedSections(action.items)
        if (action.id === 'show') return `Show ${named} on ${creator.title}'s page again?`
        if (action.id === 'skip') return onEdit ? `Hide ${named} on ${creator.title}'s page?` : `Stop showing ${named} here?`
        if (action.id === 'main' || action.id === 'contents') {
            const main = mainTitleOf(creator, action.items[0].account)
            return `Add ${named} to ${main}?`
        }
        if (action.items.every(({section}) => section.movieSlug)) return `Make ${named} ${creator.title}'s?`
        return `Add ${named} to your library?`
    }

    const left = confirming ? chosen.length - confirming.items.length : 0
    return (
        <>
            <BulkBar count={chosen.length} prompt={`Choose ${nouns} to add`} onClear={onClear} onStop={onStop}>
                {actions.map((action, index) => (
                    // The first action is the main one, as Change settings is for profiles.
                    <button key={action.id} type="button" className={index === 0 && action.id !== 'skip' ? 'btn btn-primary' : 'btn'} disabled={none} onClick={() => choose(action)}>
                        <FontAwesomeIcon icon={action.icon} aria-hidden="true"/> {action.label}
                        {!none && action.items.length < chosen.length && <span className="bulk-action-count">{action.items.length.toLocaleString()}</span>}
                    </button>
                ))}
            </BulkBar>
            {confirming && confirming.id !== 'own' && (
                <ConfirmDialog
                    open
                    title={title(confirming)}
                    icon={confirming.icon}
                    onDismiss={() => setConfirming(null)}
                    confirmButton={{
                        label: confirming.label,
                        className: confirming.id === 'skip' ? 'btn btn-danger' : 'btn btn-primary',
                        onClick: () => apply(confirming),
                    }}
                >
                    <ActionNote creator={creator} action={confirming} onEdit={onEdit}/>
                    {MOVING.has(confirming.id) && confirming.items.some(isWaitingList) && (
                        <p className="help">The ones that wait for your choice move their {confirming.items[0].account.site.mediaNames.plural} along: VODLoft shows what moves next.</p>
                    )}
                    {confirming.items.length > 1 && <TitleList titles={confirming.items.map(({section}) => section.title)}/>}
                    {left > 0 && (
                        <p className="help">
                            This doesn't apply to the other {left === 1 ? 'one' : left.toLocaleString()} you chose, which {left === 1 ? 'stays' : 'stay'} as {left === 1 ? 'it is' : 'they are'}.
                        </p>
                    )}
                </ConfirmDialog>
            )}
            {picking && (
                <AnotherCollectionDialog
                    creator={creator} item={picking.items[0]} confirmLabel="Add"
                    title={`Another collection for ${namedSections(picking.items)}`} several={picking.items.length > 1}
                    onDismiss={() => setPicking(null)}
                    onPick={async (place) => { setPicking(null); await apply(picking, place) }}
                />
            )}
            {answerDialog}
            {owning && (
                <NewCreatorCollectionDialog
                    creator={creator} items={owning} onDismiss={() => setOwning(null)} onAdded={() => onDone(owning)}
                />
            )}
        </>
    )
}
