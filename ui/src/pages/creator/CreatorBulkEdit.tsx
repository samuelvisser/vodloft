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
import {isMovie, mainSeasonOf, mainTitleOf, type AccountSection} from './CreatorSectionsEditor'
import NewCreatorCollectionDialog from './NewCreatorCollectionDialog'
import {TitleList, namedSections, sectionNouns} from './sectionNames'

type BulkAction = {
    id: 'main' | 'own' | 'movie' | 'skip' | 'show'
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
    const actions: (BulkAction | false)[] = [
        toMain.length > 0 && {id: 'main', label: mainLabel(), icon: faIcon('fass', 'plus'), items: toMain},
        sections.length > 0 && {
            id: 'own', label: sections.length === 1 ? 'Own collection' : 'Own collections', icon: faIcon('fass', 'folder-plus'),
            items: sections,
        },
        movies.length > 0 && {id: 'movie', label: movieLabel(), icon: faIcon('fass', 'film'), items: movies},
        hideable.length > 0 && {
            id: 'skip', label: onEdit ? 'Hide on creator page' : 'Do not show here again', icon: faIcon('fass', 'eye-slash'), items: hideable,
        },
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

const TARGETS: Record<'main' | 'movie' | 'skip', 'main' | 'own' | 'skip'> = {main: 'main', movie: 'own', skip: 'skip'}

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
    const none = chosen.length === 0
    // While none is chosen, the bar shows what the list's sections can have, unavailable.
    const actions = bulkActions(creator, none ? items : chosen, onEdit)
    const nouns = sectionNouns(items).plural

    const apply = async (action: BulkAction) => {
        try {
            for (const id of new Set(action.items.map(({account}) => account.id))) {
                const refs = action.items.filter(({account}) => account.id === id).map(({section}) => section.ref)
                queryClient.setQueryData(['creator', creator.slug], action.id === 'show'
                    ? await showCreatorSections(creator.slug, id, refs)
                    : await addCreatorSections(creator.slug, id, refs.map((ref) => ({ref, target: TARGETS[action.id as keyof typeof TARGETS]}))))
            }
            await Promise.all([
                queryClient.invalidateQueries({queryKey: ['creators']}),
                queryClient.invalidateQueries({queryKey: ['collection']}),
                queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                ...(action.id === 'movie' ? [queryClient.invalidateQueries({queryKey: ['movies']})] : []),
            ])
            const named = namedSections(action.items)
            toast.success(
                action.id === 'skip' ? `Hid ${named} on ${onEdit ? `${creator.title}'s page` : 'this page'}`
                    : action.id === 'show' ? `${named} ${action.items.length === 1 ? 'shows' : 'show'} on ${creator.title}'s page again`
                        : `Added ${named}`,
            )
            onDone(action.items)
        } catch (exc) {
            toast.error(exc instanceof Error ? exc.message : String(exc))
        } finally {
            setConfirming(null)
        }
    }

    const choose = (action: BulkAction) => {
        if (action.id === 'own') setOwning(action.items)
        else setConfirming(action)
    }

    const title = (action: BulkAction) => {
        const named = namedSections(action.items)
        if (action.id === 'show') return `Show ${named} on ${creator.title}'s page again?`
        if (action.id === 'skip') return onEdit ? `Hide ${named} on ${creator.title}'s page?` : `Stop showing ${named} here?`
        if (action.id === 'main') {
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
                    {confirming.items.length > 1 && <TitleList titles={confirming.items.map(({section}) => section.title)}/>}
                    {left > 0 && (
                        <p className="help">
                            This doesn't apply to the other {left === 1 ? 'one' : left.toLocaleString()} you chose, which {left === 1 ? 'stays' : 'stay'} as {left === 1 ? 'it is' : 'they are'}.
                        </p>
                    )}
                </ConfirmDialog>
            )}
            {owning && (
                <NewCreatorCollectionDialog
                    creator={creator} items={owning} onDismiss={() => setOwning(null)} onAdded={() => onDone(owning)}
                />
            )}
        </>
    )
}
