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

/**
 * Asks how a creator's playlist or show that becomes a collection of its own identifies its episodes, and what type
 * of collection it is, before adding it. It suggests what Add collection suggests for the same link.
 */
export default function NewCreatorCollectionDialog({creator, item, onDismiss}: {
    creator: CreatorPageRead
    item: AccountSection
    onDismiss: () => void
}) {
    const queryClient = useQueryClient()
    const {account, section} = item
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
        (values) => creatorSectionsRequest(creator.slug, account.id, {
            sections: [{ref: section.ref, target: 'own'}], ...values,
        }),
        {
            parseSuccess: async (response) => CreatorPageReadSchema.parse(await response.json()),
            onSuccess: async (page) => {
                queryClient.setQueryData(['creator', creator.slug], page)
                await Promise.all([
                    queryClient.invalidateQueries({queryKey: ['creators']}),
                    queryClient.invalidateQueries({queryKey: ['collection']}),
                    queryClient.invalidateQueries({queryKey: ['collectionsView']}),
                ])
                toast.success(`Added ${section.title}`)
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
            title={`Add ${section.title}`}
            icon={faIcon('fass', 'plus')}
            onDismiss={() => {if (!isSubmitting) onDismiss()}}
            confirmButton={{
                label: isSubmitting ? 'Adding…' : 'Add collection',
                onClick: () => void submit(),
                disabled: suggestion.isLoading || isSubmitting,
            }}
        >
            <p>
                {section.title} becomes a collection of its own in your library, and VODLoft keeps adding what {creator.title}
                {' '}puts in it.
            </p>
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
