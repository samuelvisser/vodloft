import {useId, useMemo, useState} from 'react'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {zodResolver} from '@hookform/resolvers/zod'
import {useQuery} from '@tanstack/react-query'
import {Controller, useForm, useWatch} from 'react-hook-form'
import {z} from 'zod'
import {faIcon} from '../../icons/faIcon'
import type {BulkResult, BulkSummary} from '../../types/schemas/profile_bulk'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import type {SelectRegistry} from '../../utils/selectRegistry'
import {SegmentedOptions} from '../SegmentedOptions'
import NumberInput from '../common/NumberInput'
import SimpleSelect from '../common/SimpleSelect'
import {SkippedList} from './BulkEditControls'
import {type BulkEndpoint, countOf, fetchBulkSummary, postBulkChange} from './bulkApi'

type FieldValue = boolean | string | number

/** One setting the bulk edit can change, by its name in the API's changes. */
export type BulkFieldSpec = {
    key: string
    label: string
    kind: 'switch' | 'select' | 'number'
    defaultValue: FieldValue
    registry?: SelectRegistry
    min?: number
    /** How a value the profiles have now reads; the registry's label or On/Off when left out. */
    valueLabel?: (value: string | number | boolean | null) => string
    /** The value as the API takes it, such as a select's id as a number. */
    toApi?: (value: FieldValue) => unknown
    /** Shown under the control once the setting is ticked. */
    help?: string
    /** Why some of the chosen profiles don't have the setting, such as "only YouTube has SponsorBlock". */
    missingReason?: string
}

function valueSchema(spec: BulkFieldSpec) {
    if (spec.kind === 'switch') return z.boolean()
    if (spec.kind === 'number') return z.number({error: 'Enter a number'}).int().min(spec.min ?? 0)
    return z.string().min(1, 'Choose one')
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

/** "2 on, 1 off", or "All on" when they agree. */
function currentValues(spec: BulkFieldSpec, summary: BulkSummary['fields'][string]): string {
    if (summary.values.length === 1) return `All ${valueLabel(spec, summary.values[0].value)}`
    if (spec.kind === 'number') return summary.values.map((item) => `${valueLabel(spec, item.value)} (${item.count})`).join(', ')
    return summary.values.map((item) => `${item.count} ${valueLabel(spec, item.value)}`).join(', ')
}

type BulkChangeDialogProps = {
    endpoint: BulkEndpoint
    ids: readonly number[]
    noun: [string, string]
    /** Names of the chosen profiles that are on screen, to show which ones change. */
    names: string[]
    fields: BulkFieldSpec[]
    onClose: () => void
    onChanged: (result: BulkResult) => void
}

/** Change settings: tick the settings to give every chosen profile; the rest keep their own value. */
export default function BulkChangeDialog({endpoint, ids, noun, names, fields, onClose, onChanged}: BulkChangeDialogProps) {
    const titleId = useId()
    const [result, setResult] = useState<BulkResult | null>(null)
    const schema = useMemo(() => bulkFormSchema(fields), [fields])
    const form = useForm<BulkFormValues>({
        resolver: zodResolver(schema) as never,
        defaultValues: getZodDefaults(schema) as BulkFormValues,
    })
    const values = useWatch({control: form.control})
    const ticked = fields.filter((spec) => values[spec.key]?.apply).length

    const summary = useQuery({
        queryKey: ['profileBulkSummary', endpoint, ids] as const,
        queryFn: ({signal}) => fetchBulkSummary(endpoint, ids, signal),
        staleTime: 0,
    })

    const onSubmit = buildServerAwareSubmit<BulkFormValues, BulkFormValues, BulkResult>(
        form,
        async (data) => {
            const changes = Object.fromEntries(fields
                .filter((spec) => data[spec.key]?.apply)
                .map((spec) => {
                    const value = data[spec.key].value as FieldValue
                    return [spec.key, spec.toApi ? spec.toApi(value) : value]
                }))
            return postBulkChange(endpoint, ids, changes)
        },
        {
            rootServerValidationMessage: 'Nothing was changed.',
            onSuccess: (changed) => {
                onChanged(changed)
                if (changed.skipped.length) setResult(changed)
                else onClose()
            },
        },
    )

    const shownNames = names.slice(0, 3)
    const errors = form.formState.errors

    return (
        <div className="modal-overlay" role="presentation" onClick={onClose}>
            <form
                className="modal modal-wide bulk-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                onClick={(event) => event.stopPropagation()}
                onSubmit={onSubmit}
                noValidate
            >
                <div className="modal-header">
                    <div className="modal-icon" aria-hidden><FontAwesomeIcon icon={faIcon('fass', 'pen-to-square')}/></div>
                    <h2 id={titleId} className="modal-title">Change {countOf(ids.length, noun)}</h2>
                </div>

                {result ? (
                    <SkippedList result={result} verb="Changed" noun={noun}/>
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
                            Tick the settings you want to change. Everything you leave unticked keeps its own value on each profile.
                        </p>
                        {summary.isError && <div className="form-error-card" role="alert">Could not load the current settings.</div>}
                        <div className="bulk-fields">
                            {fields.map((spec) => {
                                const fieldSummary = summary.data?.fields[spec.key]
                                const count = summary.data?.count ?? ids.length
                                const offered = fieldSummary?.offered ?? count
                                const unavailable = !!fieldSummary && offered === 0
                                const active = !!values[spec.key]?.apply && !unavailable
                                const controlId = `${titleId}-${spec.key}`
                                const error = (errors[spec.key] as {value?: {message?: string}} | undefined)?.value?.message
                                return (
                                    <div className={`bulk-field${active ? ' is-active' : ''}${unavailable ? ' is-unavailable' : ''}`} key={spec.key}>
                                        <label className="bulk-field__head">
                                            <input
                                                type="checkbox"
                                                className="bulk-check"
                                                disabled={unavailable}
                                                {...form.register(`${spec.key}.apply`)}
                                            />
                                            <span className="bulk-field__label">{spec.label}</span>
                                            <span className="bulk-field__current">
                                                {!fieldSummary ? '…' : unavailable ? 'None of these have it' : currentValues(spec, fieldSummary)}
                                            </span>
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
                                                            menuPortalTarget={document.body}
                                                            styles={{menuPortal: (base) => ({...base, zIndex: 2000})}}
                                                        />
                                                    )}
                                                />
                                                {error && <div className="error" role="alert">{error}</div>}
                                                {fieldSummary && offered < count && (
                                                    <div className="help">
                                                        Only changes {offered.toLocaleString()} of the {countOf(count, noun)}
                                                        {spec.missingReason ? `: ${spec.missingReason}` : '; the others don’t have this setting'}.
                                                    </div>
                                                )}
                                                {spec.help && <div className="help">{spec.help}</div>}
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                        {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}
                    </>
                )}

                <div className="modal-actions">
                    {result ? (
                        <button type="button" className="btn btn-primary" onClick={onClose}>Close</button>
                    ) : (
                        <>
                            <button type="button" className="btn" onClick={onClose}>Cancel</button>
                            <button type="submit" className="btn btn-primary" disabled={!ticked || form.formState.isSubmitting}>
                                {form.formState.isSubmitting && <FontAwesomeIcon icon={faIcon('fass', 'circle-notch')} spin aria-hidden="true"/>}
                                {ticked
                                    ? `Change ${ticked} setting${ticked === 1 ? '' : 's'} on ${countOf(ids.length, noun)}`
                                    : 'Choose a setting to change'}
                            </button>
                        </>
                    )}
                </div>
            </form>
        </div>
    )
}
