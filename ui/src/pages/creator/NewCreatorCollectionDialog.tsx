import {useEffect, useRef} from 'react'
import {Controller, useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQueryClient} from '@tanstack/react-query'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {toast} from 'react-hot-toast'
import {faIcon} from '../../icons/faIcon'
import {creatorSectionsRequest} from '../../lib/queries'
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../../components/common/SimpleSelect'
import {useCollectionDefaults} from '../../components/AddCollectionPage/collectionDefaults'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import {CollectionTypeReg, EpisodeIdentifierReg, episodeIdentifierRegFor, musicIdentificationAdvice} from '../../types/collection'
import {
    CreatorCollectionFormSchema,
    CreatorPageReadSchema,
    type CreatorCollectionFormIn,
    type CreatorCollectionFormOut,
    type CreatorPageRead,
} from '../../types/schemas/creator'
import type {AccountSection} from './CreatorSectionsEditor'
import {TitleList, namedSections} from './sectionNames'

/**
 * Asks how a creator's playlists or shows that each become a collection of their own identify their episodes, and
 * what type of collection they are, before adding them. It suggests what Add collection suggests for the first one's
 * link.
 */
export default function NewCreatorCollectionDialog({creator, items, onDismiss, onAdded, onChoose}: {
    creator: CreatorPageRead
    items: AccountSection[]
    onDismiss: () => void
    onAdded?: () => void
    /** Instead of adding them: what the user chose, for a list waiting for an answer, which the move dialog adds. */
    onChoose?: (values: CreatorCollectionFormOut) => void
}) {
    const queryClient = useQueryClient()
    const {account, section} = items[0]
    const one = items.length === 1
    const named = namedSections(items)
    const suggestion = useCollectionDefaults(section.url)
    const form = useForm<CreatorCollectionFormIn, unknown, CreatorCollectionFormOut>({
        resolver: zodResolver(CreatorCollectionFormSchema),
        defaultValues: getZodDefaults(CreatorCollectionFormSchema),
    })
    const {control, reset, formState: {errors, isSubmitting}} = form

    // The suggestion arrives after the lookup; it fills the form once, unless the user already chose.
    const settled = useRef(false)
    useEffect(() => {
        if (!suggestion.defaults || settled.current) return
        settled.current = true
        reset(suggestion.defaults)
    }, [suggestion.defaults, reset])

    const submit = buildServerAwareSubmit<CreatorCollectionFormIn, CreatorCollectionFormOut, CreatorPageRead>(
        form,
        async (values) => {
            // One request for each account, as the sections of an account are added together.
            const accounts = [...new Set(items.map((item) => item.account.id))]
            let response: Response | undefined
            for (const id of accounts) {
                const sections = items.filter((item) => item.account.id === id).map((item) => ({ref: item.section.ref, target: 'own' as const}))
                response = await creatorSectionsRequest(creator.slug, id, {sections, ...values})
                if (!response.ok) break
            }
            return response as Response
        },
        {
            parseSuccess: async (response) => CreatorPageReadSchema.parse(await response.json()),
            onSuccess: async (page) => {
                queryClient.setQueryData(['creator', creator.slug], page)
                await Promise.all([
                    queryClient.invalidateQueries({queryKey: ['creators']}),
                    queryClient.invalidateQueries({queryKey: ['collection']}),
                    queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                ])
                toast.success(`Added ${named}`)
                onAdded?.()
                onDismiss()
            },
        },
    )

    const field = (
        name: 'type' | 'episodeIdentifier', label: string, registry: typeof CollectionTypeReg | typeof EpisodeIdentifierReg,
    ) => {
        const id = `new-creator-collection-${name}`
        return (
            <div className="form-row">
                <label htmlFor={id}>{label}</label>
                <Controller
                    control={control}
                    name={name}
                    render={({field: {value, onChange, onBlur}}) => (
                        <>
                            <SimpleSelect
                                inputId={id} registry={registry} value={value || null}
                                onChange={(next) => {settled.current = true; onChange(next)}} onBlur={onBlur}
                                isDisabled={suggestion.isLoading || isSubmitting}
                                placeholder={suggestion.isLoading ? 'Looking it up…' : 'Choose…'}
                                aria-invalid={!!errors[name]}
                            />
                            {errors[name]
                                ? <div className="error" role="alert">{errors[name]?.message}</div>
                                : value && <div className="help">{registry.meta(value as never)?.help}</div>}
                        </>
                    )}
                />
            </div>
        )
    }

    return (
        <ConfirmDialog
            open
            title={`Add ${named}`}
            icon={faIcon('fass', 'plus')}
            onDismiss={() => {if (!isSubmitting) onDismiss()}}
            confirmButton={{
                label: onChoose ? 'Next' : isSubmitting ? 'Adding…' : one ? 'Add collection' : `Add ${items.length} collections`,
                onClick: () => void (onChoose ? form.handleSubmit((values) => onChoose(values))() : submit()),
                disabled: suggestion.isLoading || isSubmitting,
            }}
        >
            {one ? (
                <p>
                    {section.title} becomes a collection of its own in your library, and VODLoft keeps adding what {creator.title}
                    {' '}puts in it.
                </p>
            ) : (
                <>
                    <p>
                        Each becomes a collection of its own in your library, with the type and episode identification you
                        choose here, and VODLoft keeps adding what {creator.title} puts in them.
                    </p>
                    <TitleList titles={items.map((item) => item.section.title)}/>
                </>
            )}
            {suggestion.isLoading && (
                <p className="help"><FontAwesomeIcon icon={faIcon('fass', 'spinner')} spin/> Looking {section.title} up on {account.site.name}…</p>
            )}
            {suggestion.error && (
                <p className="help">
                    VODLoft could not look {section.title} up on {account.site.name} to suggest these, so choose them yourself.
                </p>
            )}
            {field('type', 'Collection type', CollectionTypeReg)}
            {field('episodeIdentifier', 'Episode identification', episodeIdentifierRegFor(form.watch('type')))}
            {musicIdentificationAdvice(form.watch('type'), form.watch('episodeIdentifier')) && (
                <p className="help form-advice" role="status">{musicIdentificationAdvice(form.watch('type'), form.watch('episodeIdentifier'))}</p>
            )}
            {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}
        </ConfirmDialog>
    )
}
