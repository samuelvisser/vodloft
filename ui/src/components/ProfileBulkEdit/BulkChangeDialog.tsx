import {type FormEvent, type ReactNode, useId, useMemo, useRef, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQuery} from '@tanstack/react-query'
import {Controller, useForm, useWatch} from 'react-hook-form'
import {z} from 'zod'
import {faIcon} from '../../icons/faIcon'
import {BulkResultSchema, type BulkResult, type BulkSummary} from '../../types/schemas/profile_bulk'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import type {SelectRegistry} from '../../utils/selectRegistry'
import {SegmentedOptions} from '../SegmentedOptions'
import ChoiceBar, {type ChoiceBarOption} from '../common/ChoiceBar'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'
import Modal from '../Modal/Modal'
import {SkippedList} from './BulkEditControls'
import {type BulkEndpoint, countOf, fetchBulkSummary, postBulkChange} from './bulkApi'

type FieldValue = boolean | string | number
type FieldSummary = BulkSummary['fields'][string]

/** One setting the bulk edit can change, by its name in the API's changes. */
export type BulkFieldSpec = {
    key: string
    label: string
    /** A text setting may be left empty, which clears it. A choice shows a few short options all in view. */
    kind: 'switch' | 'select' | 'number' | 'text' | 'choice'
    defaultValue: FieldValue
    /** The options of a choice. */
    options?: ChoiceBarOption<string>[]
    /** Sent inside this setting of the changes, by ``apiKey``, such as one feed among the feeds. */
    group?: string
    apiKey?: string
    /** What the items are set to now, for a setting the summary lists apart from its fields. */
    summary?: FieldSummary
    registry?: SelectRegistry
    min?: number
    /** The longest text a text setting takes. */
    maxLength?: number
    placeholder?: string
    /** How a value the profiles have now reads; the registry's label or On/Off when left out. */
    valueLabel?: (value: string | number | boolean | null) => string
    /** The value as the API takes it, such as a select's id as a number. */
    toApi?: (value: FieldValue) => unknown
    /** Shown under the control once the setting is ticked. */
    help?: string
}

function valueSchema(spec: BulkFieldSpec) {
    if (spec.kind === 'switch') return z.boolean()
    if (spec.kind === 'number') return z.number({error: 'Enter a number'}).int().min(spec.min ?? 0)
    if (spec.kind === 'text') return z.string().max(spec.maxLength ?? Infinity, `Keep it to ${spec.maxLength} characters`)
    return z.string({error: 'Choose one'}).min(1, 'Choose one')
}

/** Each setting as {apply, value}: only the ticked ones are sent, and their value is checked only then. */
function bulkFormSchema(specs: BulkFieldSpec[]) {
    return z.object(Object.fromEntries(specs.map((spec) => [
        spec.key,
        z.object({apply: z.boolean(), value: z.unknown()})
            .superRefine((field, context) => {
                if (!field.apply) return
                const result = valueSchema(spec).safeParse(field.value)
                if (!result.success) context.addIssue({code: 'custom', path: ['value'], message: result.error.issues[0].message})
            })
            .default({apply: false, value: spec.defaultValue}),
    ])))
}

type BulkFormValues = Record<string, {apply: boolean, value: unknown}>

function valueLabel(spec: BulkFieldSpec, value: string | number | boolean | null): string {
    if (spec.valueLabel) return spec.valueLabel(value)
    if (typeof value === 'boolean') return value ? 'on' : 'off'
    if (spec.registry && value !== null) return spec.registry.getLabelLoose(String(value))
    return String(value)
}

/** "The Daily Wire doesn't", or "The Daily Wire and NPO Start don't". */
function sitesWithout(sites: string[]): string {
    if (sites.length === 1) return `${sites[0]} doesn’t`
    return `${sites.slice(0, -1).join(', ')} and ${sites[sites.length - 1]} don’t`
}

/** "2 on, 1 off", or "All on" when they agree. */
function currentValues(spec: BulkFieldSpec, summary: FieldSummary): string {
    if (summary.values.length === 1) return `All ${valueLabel(spec, summary.values[0].value)}`
    if (spec.kind === 'number') return summary.values.map((item) => `${valueLabel(spec, item.value)} (${item.count})`).join(', ')
    return summary.values.map((item) => `${item.count} ${valueLabel(spec, item.value)}`).join(', ')
}

/** A look at what the changes do before they are saved, for changes that do more than set a value, such as moving
 * downloaded files. */
export type BulkReview = {
    /** Whether the ticked changes need it. */
    wanted: (changes: Record<string, unknown>) => boolean
    /** The step that shows what the changes do. It says when saving can go ahead, with what saving sends besides the
     * changes, such as a choice the user made there, and the items whose change takes long, which are saved one at a
     * time so it can show how far saving is; null while it is not ready. While saving, it shows ``saving``. */
    render: (props: {
        changes: Record<string, unknown>
        onReady: (ready: {extra: Record<string, unknown>, oneByOne: number[]} | null) => void
        onBack: () => void
        saving: BulkSaving | null
    }) => ReactNode
    /** What the save button says there, such as Save and move. */
    saveLabel: string
}

/** How far saving after a review is: the item it saves now, and the ones it saved or left as they were. */
export type BulkSaving = {at: number | null, saved: number[], skipped: Record<number, string>}

type BulkChangeDialogProps = {
    endpoint: BulkEndpoint
    ids: readonly number[]
    noun: [string, string]
    /** Names of the chosen items that are on screen, to show which ones change. */
    names: string[]
    fields: BulkFieldSpec[]
    /** Settings that depend on what the chosen items have, such as the feeds of their channels, once that is known. */
    moreFields?: (summary: BulkSummary) => BulkFieldSpec[]
    review?: BulkReview
    onClose: () => void
    onChanged: (result: BulkResult) => void
}

/** Change settings: tick the settings to give every chosen item, such as a profile; the rest keep their own value. */
export default function BulkChangeDialog({endpoint, ids, noun, names, fields: givenFields, moreFields, review, onClose, onChanged}: BulkChangeDialogProps) {
    const titleId = useId()
    const [result, setResult] = useState<BulkResult | null>(null)
    // On the review: what saving sends besides the changes, once the review is ready.
    const [reviewing, setReviewing] = useState(false)
    const [ready, setReady] = useState<{extra: Record<string, unknown>, oneByOne: number[]} | null>(null)
    const [saving, setSaving] = useState<BulkSaving | null>(null)

    const summary = useQuery({
        queryKey: ['profileBulkSummary', endpoint, ids] as const,
        queryFn: ({signal}) => fetchBulkSummary(endpoint, ids, signal),
        staleTime: 0,
    })
    const fields = useMemo(
        () => [...givenFields, ...(moreFields && summary.data ? moreFields(summary.data) : [])],
        [givenFields, moreFields, summary.data],
    )
    // Checked against the settings shown now, which grow once the summary says what the chosen items have.
    const schema = useRef(bulkFormSchema(givenFields))
    schema.current = useMemo(() => bulkFormSchema(fields), [fields])
    const form = useForm<BulkFormValues>({
        resolver: ((...args: Parameters<ReturnType<typeof zodResolver>>) => zodResolver(schema.current)(...args)) as never,
        defaultValues: getZodDefaults(bulkFormSchema(givenFields)) as BulkFormValues,
    })
    const values = useWatch({control: form.control})
    const ticked = fields.filter((spec) => values[spec.key]?.apply).length

    /** The ticked settings as the API takes them. */
    const changesOf = (data: Partial<BulkFormValues>) => {
        const changes: Record<string, unknown> = {}
        for (const spec of fields) {
            if (!data[spec.key]?.apply) continue
            const value = data[spec.key]!.value as FieldValue
            const sent = spec.toApi ? spec.toApi(value) : value
            if (spec.group) changes[spec.group] = {...(changes[spec.group] as object | undefined), [spec.apiKey ?? spec.key]: sent}
            else changes[spec.key] = sent
        }
        return changes
    }
    const reviewWanted = !!review && ticked > 0 && review.wanted(changesOf(values as BulkFormValues))

    const finished = (changed: BulkResult) => {
        onChanged(changed)
        if (changed.skipped.length) setResult(changed)
        else onClose()
    }
    const save = buildServerAwareSubmit<BulkFormValues, BulkFormValues, BulkResult>(
        form,
        async (data) => postBulkChange(endpoint, ids, changesOf(data)),
        {rootServerValidationMessage: 'Nothing was changed.', onSuccess: finished},
    )

    /** After the review: the items whose change takes long one at a time, each in a short save of its own, so the
     * review shows how far it is; then the others together. */
    const saveReviewed = async () => {
        if (!ready) return
        const changes = changesOf(form.getValues())
        const total: BulkResult = {done: 0, skipped: []}
        let progress: BulkSaving = {at: null, saved: [], skipped: {}}
        const rest = ids.filter((id) => !ready.oneByOne.includes(id))
        const batches = [...ready.oneByOne.filter((id) => ids.includes(id)).map((id) => [id]), ...(rest.length ? [rest] : [])]
        for (const batch of batches) {
            progress = {...progress, at: batch.length === 1 ? batch[0] : null}
            setSaving(progress)
            let changed: BulkResult
            try {
                const response = await postBulkChange(endpoint, batch, changes, ready.extra)
                if (!response.ok) {
                    const body = await response.json().catch(() => null)
                    throw new Error(response.status >= 500 && response.status !== 500
                        ? 'VODLoft took too long to answer. It may still be saving: look again in a minute.'
                        : typeof body?.detail === 'string' ? body.detail : `Could not save (HTTP ${response.status})`)
                }
                changed = BulkResultSchema.parse(await response.json())
            } catch (error) {
                // No answer at all, such as when the connection dropped: the save may have gone ahead regardless.
                const reason = error instanceof TypeError
                    ? 'No answer from VODLoft. It may still be saving: look again in a minute.'
                    : error instanceof Error ? error.message : 'Could not save'
                changed = {done: 0, skipped: batch.map((id) => ({id, name: names[ids.indexOf(id)] ?? String(id), reason}))}
            }
            total.done += changed.done
            total.skipped.push(...changed.skipped)
            const left = new Set(changed.skipped.map((item) => item.id))
            progress = {
                at: null,
                saved: [...progress.saved, ...batch.filter((id) => !left.has(id))],
                skipped: {...progress.skipped, ...Object.fromEntries(changed.skipped.map((item) => [item.id, item.reason]))},
            }
            setSaving(progress)
        }
        finished(total)
    }

    /** Changes that need a look first open the review; there, the form saves them. */
    const onSubmit = (event: FormEvent<HTMLFormElement>) => {
        if (reviewWanted && !reviewing) {
            event.preventDefault()
            return form.handleSubmit(() => {
                setReady(null)
                setSaving(null)
                setReviewing(true)
            })(event)
        }
        if (reviewing) {
            event.preventDefault()
            return void saveReviewed()
        }
        return save(event)
    }

    const shownNames = names.slice(0, 3)
    // A setting none of the chosen profiles have is left out.
    const summaryOf = (spec: BulkFieldSpec): FieldSummary | undefined => spec.summary ?? summary.data?.fields[spec.key]
    const shownFields = fields.filter((spec) => !summary.data || (summaryOf(spec)?.offered ?? 1) > 0)
    const errors = form.formState.errors

    return (
        <Modal
            onDismiss={saving ? () => undefined : onClose}
            // Escape cancels, so it only closes before a setting is ticked, or once the result is shown.
            dismissOnEscape={Boolean(result) || (ticked === 0 && !form.formState.isSubmitting)}
            className="modal modal-wide bulk-dialog"
            labelledBy={titleId}
            onSubmit={onSubmit}
        >
            <div className="modal-header">
                <div className="modal-icon" aria-hidden><FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')}/></div>
                <h2 id={titleId} className="modal-title">Change {countOf(ids.length, noun)}</h2>
            </div>

            <div className="modal-body">
                {result ? (
                    <SkippedList result={result} verb="Changed" noun={noun}/>
                ) : reviewing && review ? (
                    review.render({changes: changesOf(form.getValues()), onReady: setReady, onBack: () => setReviewing(false), saving})
                ) : (
                    <>
                        {shownNames.length > 0 && (
                            <div className="bulk-dialog-subjects">
                                {shownNames.map((name) => <span className="bulk-subject" key={name}>{name}</span>)}
                                {ids.length > shownNames.length && (
                                    <span className="bulk-subject is-more">+{(ids.length - shownNames.length).toLocaleString()} more</span>
                                )}
                            </div>
                        )}
                        <p className="bulk-dialog-hint">
                            Tick the settings you want to change. Everything you leave unticked keeps its own value on each {noun[0]}.
                        </p>
                        {summary.isError && <div className="form-error-card" role="alert">Could not load the current settings.</div>}
                        {summary.isPending ? (
                            <p className="bulk-dialog-hint" aria-live="polite">Loading the current settings…</p>
                        ) : (
                            <div className="bulk-fields">
                                {shownFields.map((spec) => {
                                    const fieldSummary = summaryOf(spec)
                                    const count = summary.data?.count ?? ids.length
                                    const offered = fieldSummary?.offered ?? count
                                    const active = !!values[spec.key]?.apply
                                    const controlId = `${titleId}-${spec.key}`
                                    const error = (errors[spec.key] as {value?: {message?: string}} | undefined)?.value?.message
                                    return (
                                        <div className={`bulk-field${active ? ' is-active' : ''}`} key={spec.key}>
                                            <label className="bulk-field__head">
                                                <input type="checkbox" className="bulk-check" {...form.register(`${spec.key}.apply`)}/>
                                                <span className="bulk-field__label">{spec.label}</span>
                                                {fieldSummary && <span className="bulk-field__current">{currentValues(spec, fieldSummary)}</span>}
                                            </label>
                                            {active && (
                                                <div className="bulk-field__control">
                                                    <Controller
                                                        control={form.control}
                                                        name={`${spec.key}.value`}
                                                        render={({field}) => spec.kind === 'switch' ? (
                                                            <SegmentedOptions<string>
                                                                name={controlId}
                                                                ariaLabel={spec.label}
                                                                value={field.value ? 'on' : 'off'}
                                                                onChange={(value) => field.onChange(value === 'on')}
                                                                options={[{value: 'on', label: 'On'}, {value: 'off', label: 'Off'}]}
                                                            />
                                                        ) : spec.kind === 'choice' ? (
                                                            <ChoiceBar
                                                                ariaLabel={spec.label} options={spec.options ?? []}
                                                                value={typeof field.value === 'string' ? field.value : null}
                                                                onChange={field.onChange}
                                                            />
                                                        ) : spec.kind === 'text' ? (
                                                            <input
                                                                id={controlId}
                                                                className="input"
                                                                type="text"
                                                                aria-label={spec.label}
                                                                placeholder={spec.placeholder}
                                                                maxLength={spec.maxLength}
                                                                value={String(field.value ?? '')}
                                                                onChange={(event) => field.onChange(event.target.value)}
                                                                aria-invalid={!!error}
                                                            />
                                                        ) : spec.kind === 'number' ? (
                                                            <NumberInput
                                                                id={controlId}
                                                                aria-label={spec.label}
                                                                inputMode="numeric"
                                                                min={spec.min}
                                                                step={1}
                                                                value={field.value === undefined || Number.isNaN(field.value) ? '' : String(field.value)}
                                                                onChange={(event) => field.onChange(event.target.value === '' ? NaN : Number(event.target.value))}
                                                                aria-invalid={!!error}
                                                            />
                                                        ) : (
                                                            <SimpleSelect
                                                                inputId={controlId}
                                                                aria-label={spec.label}
                                                                registry={spec.registry!}
                                                                value={String(field.value ?? '')}
                                                                onChange={field.onChange}
                                                            />
                                                        )}
                                                    />
                                                    {error && <div className="error" role="alert">{error}</div>}
                                                    {fieldSummary && offered < count && (
                                                        <div className="help">
                                                            Only changes {offered.toLocaleString()} of the {countOf(count, noun)}
                                                            {fieldSummary.sitesWithout.length
                                                                ? `; ${sitesWithout(fieldSummary.sitesWithout)} have this setting.`
                                                                : '; the others don’t have this setting.'}
                                                        </div>
                                                    )}
                                                    {spec.help && <div className="help">{spec.help}</div>}
                                                </div>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                        {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}
                    </>
                )}
            </div>

            <div className="modal-actions">
                {result ? (
                    <button type="button" className="btn btn-primary" onClick={onClose}>Close</button>
                ) : (
                    <>
                        <button type="button" className="btn" disabled={!!saving} onClick={reviewing ? () => setReviewing(false) : onClose}>
                            {reviewing ? 'Back' : 'Cancel'}
                        </button>
                        <button type="submit" className="btn btn-primary" disabled={!ticked || form.formState.isSubmitting || (reviewing && (!ready || !!saving))}>
                            {(form.formState.isSubmitting || !!saving) && <FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin aria-hidden="true"/>}
                            {reviewing && review
                                ? saving ? 'Saving…' : review.saveLabel
                                : !ticked
                                    ? 'Choose a setting to change'
                                    : reviewWanted
                                        ? 'Next'
                                        : `Change ${ticked} setting${ticked === 1 ? '' : 's'} on ${countOf(ids.length, noun)}`}
                        </button>
                    </>
                )}
            </div>
        </Modal>
    )
}
