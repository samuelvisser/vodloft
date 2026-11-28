import {useEffect, useId, useMemo, useRef, useState, type ReactNode} from 'react'
import {zodResolver} from '@hookform/resolvers/zod'
import {useFieldArray, useForm} from 'react-hook-form'
import {useQueryClient, type QueryKey} from '@tanstack/react-query'
import toast from '../../lib/toast'
import {faIcon} from '../../icons/faIcon'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import Modal from '../Modal/Modal'
import {useCustomMetadataFields} from '../../lib/customMetadataFields'
import {
    CustomMetadataFormSchema,
    customMetadataToEntries,
    entriesToCustomMetadata,
    type CustomMetadataFormValues,
} from '../../types/schemas/custom_metadata'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import './CustomMetadataEditor.css'
import {apiUrl} from '../../lib/api'

export type CustomMetadataScope = 'collection' | 'movie'

type Props = {
    open: boolean
    title: string
    scope: CustomMetadataScope
    /** The saved values of what is being edited; left out, with the endpoint, while nothing is chosen yet. */
    metadata?: Record<string, string>
    endpoint?: string
    /** Comes first in the dialog and chooses what to edit, such as a collection picker. The fields show below it
     * once it has chosen. */
    picker?: ReactNode
    /** Fields to start with as new rows, such as ones an output template uses that do not exist yet. */
    addFields?: readonly string[]
    invalidateQueryKeys?: QueryKey[]
    onDismiss: () => void
}

const NO_METADATA: Record<string, string> = {}
const NO_FIELDS: readonly string[] = []

type PendingRemoval = {
    fieldId: string
    key: string
}

const VARIABLE_PREFIX: Record<CustomMetadataScope, string> = {
    collection: 'meta_collection_',
    movie: 'meta_movie_',
}

const SCOPE_LABEL: Record<CustomMetadataScope, {singular: string; plural: string}> = {
    collection: {singular: 'collection', plural: 'collections'},
    movie: {singular: 'movie', plural: 'movies'},
}

export default function CustomMetadataEditor({
    open,
    title,
    scope,
    metadata = NO_METADATA,
    endpoint,
    picker,
    addFields = NO_FIELDS,
    invalidateQueryKeys = [],
    onDismiss,
}: Props) {
    const queryClient = useQueryClient()
    const titleId = `custom-metadata-title-${useId()}`
    const descriptionId = `custom-metadata-description-${useId()}`
    const variablePrefix = VARIABLE_PREFIX[scope]
    const scopeLabel = SCOPE_LABEL[scope]
    const [pendingRemovedFields, setPendingRemovedFields] = useState<Set<string>>(() => new Set())
    const [confirmRemoval, setConfirmRemoval] = useState<PendingRemoval | null>(null)
    const {
        data: sharedFields,
        isLoading: fieldsLoading,
        isError: fieldsFailed,
    } = useCustomMetadataFields(scope, open)

    const metadataFields = useMemo(() => (
        [...new Set([...(sharedFields ?? []), ...Object.keys(metadata)])]
            .sort((left, right) => left.localeCompare(right))
    ), [metadata, sharedFields])
    const persistedFields = useMemo(() => new Set(metadataFields), [metadataFields])
    const startFields = useMemo(() => [
        ...metadataFields, ...addFields.filter((field) => !persistedFields.has(field)),
    ], [addFields, metadataFields, persistedFields])

    const form = useForm<CustomMetadataFormValues>({
        resolver: zodResolver(CustomMetadataFormSchema),
        defaultValues: {
            entries: customMetadataToEntries(metadata, startFields),
        },
        mode: 'onBlur',
        shouldFocusError: true,
    })
    const {
        fields,
        append,
        remove,
    } = useFieldArray({control: form.control, name: 'entries'})
    const {errors, isDirty, isSubmitting} = form.formState
    const wasOpen = useRef(false)
    const shownEndpoint = useRef(endpoint)

    useEffect(() => {
        // Choosing something else in the picker starts over on its values.
        const switched = shownEndpoint.current !== endpoint
        shownEndpoint.current = endpoint
        const justOpened = (open && !wasOpen.current) || switched
        wasOpen.current = open
        if (justOpened) {
            setPendingRemovedFields(new Set())
            setConfirmRemoval(null)
        }
        if (!open || (!justOpened && isDirty)) return
        form.reset({
            entries: customMetadataToEntries(metadata, startFields),
        })
    }, [endpoint, form, isDirty, metadata, open, startFields])

    const submit = buildServerAwareSubmit<CustomMetadataFormValues>(
        form,
        async ({entries}) => {
            if (endpoint === undefined) throw new Error('Choose what to save metadata for first')
            const activeFields = new Set(entries.map(({key}) => key))
            const removedFields = [...pendingRemovedFields]
                .filter((key) => !activeFields.has(key))
                .sort()
            return fetch(`${apiUrl()}${endpoint}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                credentials: 'include',
                body: JSON.stringify({
                    customMetadata: entriesToCustomMetadata(entries),
                    removedFields,
                }),
            })
        },
        {
            successStatuses: [200],
            genericMessage: 'Could not save metadata',
            onSuccess: async () => {
                await Promise.all([
                    ...invalidateQueryKeys.map((queryKey) => queryClient.invalidateQueries({queryKey})),
                    queryClient.invalidateQueries({queryKey: ['customMetadataFields']}),
                    queryClient.invalidateQueries({queryKey: ['localMediaProfileTemplateVariables']}),
                    queryClient.invalidateQueries({queryKey: ['localMediaProfileTemplateSources']}),
                ])
                toast.success('Metadata saved')
                onDismiss()
            },
        },
    )

    if (!open) return null

    const confirmFieldRemoval = () => {
        if (!confirmRemoval) return
        const index = fields.findIndex(({id}) => id === confirmRemoval.fieldId)
        if (index >= 0) remove(index)
        setPendingRemovedFields((current) => {
            const next = new Set(current)
            next.add(confirmRemoval.key)
            return next
        })
        setConfirmRemoval(null)
    }

    return (
        <>
            <Modal
                onDismiss={() => !isSubmitting && onDismiss()}
                // Escape cancels, so it only closes while there are no edits to lose.
                dismissOnEscape={!isDirty && pendingRemovedFields.size === 0}
                className="modal custom-metadata-modal"
                labelledBy={titleId}
                describedBy={descriptionId}
            >
                <div className="modal-header">
                    <h2 id={titleId} className="modal-title">{title}</h2>
                </div>

                <form
                    onSubmit={(event) => {
                        // A dialog opened from inside another form, such as a Local Media Profile's, is portaled out of it
                        // in the page but not in React, so its submit would also submit that form.
                        event.stopPropagation()
                        void submit(event)
                    }}
                    noValidate
                >
                    <div className="custom-metadata-content">
                        {picker}
                        {endpoint !== undefined && <>
                        <p className="custom-metadata-intro">
                            Add custom metadata fields to a {scopeLabel.singular} here.
                        </p>
                        <p id={descriptionId} className="custom-metadata-description">
                            Metadata fields can be used in output templates as <code>{`{{ ${variablePrefix}field_name }}`}</code>.
                            This can therefore be a very powerful way to add any arbitrary metadata to the output path of downloaded files for this {scopeLabel.singular}.
                        </p>
                        <p className="custom-metadata-note">
                            Adding a field here makes it available to every {scopeLabel.singular}; leave its value empty where it does not apply. Field names use lowercase letters, numbers, and underscores. Existing downloaded files are not moved automatically when metadata changes.
                        </p>

                        {errors.root && (
                            <div className="form-error-card" role="alert" aria-live="polite">
                                {String(errors.root.message)}
                            </div>
                        )}
                        {fieldsFailed && (
                            <div className="form-error-card" role="alert">
                                VODLoft could not load metadata fields used by other {scopeLabel.plural}. Existing values can still be edited.
                            </div>
                        )}

                        {fieldsLoading ? (
                            <p className="custom-metadata-empty">Loading metadata fields…</p>
                        ) : (
                            <div className="custom-metadata-rows">
                                {fields.length === 0 && (
                                    <p className="custom-metadata-empty">No custom metadata fields have been added to any {scopeLabel.plural} yet.</p>
                                )}
                                {fields.map((field, index) => {
                                    const key = form.watch(`entries.${index}.key`)
                                    const isPersistedField = persistedFields.has(key) && !pendingRemovedFields.has(key)
                                    return (
                                        <div className="custom-metadata-row" key={field.id}>
                                            <div className="custom-metadata-field">
                                                <label htmlFor={`custom-metadata-key-${field.id}`}>Field</label>
                                                <input
                                                    id={`custom-metadata-key-${field.id}`}
                                                    className="input"
                                                    placeholder="name"
                                                    autoComplete="off"
                                                    readOnly={isPersistedField}
                                                    title={isPersistedField ? `This field is shared by all ${scopeLabel.plural}` : undefined}
                                                    aria-invalid={!!errors.entries?.[index]?.key}
                                                    {...form.register(`entries.${index}.key`)}
                                                />
                                                {errors.entries?.[index]?.key && (
                                                    <div className="error">{String(errors.entries[index]?.key?.message)}</div>
                                                )}
                                            </div>
                                            <div className="custom-metadata-field custom-metadata-value">
                                                <label htmlFor={`custom-metadata-value-${field.id}`}>Value</label>
                                                <input
                                                    id={`custom-metadata-value-${field.id}`}
                                                    className="input"
                                                    placeholder="data"
                                                    aria-invalid={!!errors.entries?.[index]?.value}
                                                    {...form.register(`entries.${index}.value`)}
                                                />
                                                {errors.entries?.[index]?.value && (
                                                    <div className="error">{String(errors.entries[index]?.value?.message)}</div>
                                                )}
                                            </div>
                                            <button
                                                type="button"
                                                className="btn custom-metadata-remove"
                                                onClick={() => {
                                                    if (isPersistedField) {
                                                        setConfirmRemoval({fieldId: field.id, key})
                                                    } else {
                                                        remove(index)
                                                    }
                                                }}
                                                disabled={isSubmitting}
                                            >
                                                Remove
                                            </button>
                                            <code className="custom-metadata-variable">
                                                {`{{ ${variablePrefix}${key || '<field>'} }}`}
                                            </code>
                                        </div>
                                    )
                                })}
                            </div>
                        )}

                        <button
                            type="button"
                            className="btn custom-metadata-add"
                            onClick={() => append({key: '', value: ''})}
                            disabled={isSubmitting || fieldsLoading || fields.length >= 100}
                        >
                            Add field
                        </button>
                        </>}
                    </div>

                    <div className="modal-actions">
                        <button type="button" className="btn" onClick={onDismiss} disabled={isSubmitting}>Cancel</button>
                        <button type="submit" className="btn btn-primary" disabled={isSubmitting || fieldsLoading || endpoint === undefined}>
                            {isSubmitting ? 'Saving…' : 'Save metadata'}
                        </button>
                    </div>
                </form>
            </Modal>

            <ConfirmDialog
                open={confirmRemoval !== null}
                title="Remove metadata field?"
                onDismiss={() => setConfirmRemoval(null)}
                icon={faIcon('fass', 'triangle-exclamation')}
                iconTone="danger"
                confirmButton={{
                    label: 'Remove field',
                    className: 'btn btn-danger',
                    onClick: confirmFieldRemoval,
                }}
            >
                <p>
                    <strong>{confirmRemoval?.key}</strong> is a shared metadata field for all {scopeLabel.plural}. Removing it will remove the field and its saved value from every {scopeLabel.singular}. Are you sure?
                </p>
            </ConfirmDialog>

        </>
    )
}
