import {useMemo, useState} from 'react'
import {zodResolver} from '@hookform/resolvers/zod'
import {FontAwesomeIcon} from '@fortawesome/react-fontawesome'
import {useQueryClient} from '@tanstack/react-query'
import {Controller, useForm} from 'react-hook-form'
import Select from 'react-select'
import Switch from 'react-switch'
import toast from 'react-hot-toast'

import {faIcon} from '../../icons/faIcon'
import {useCollections} from '../../lib/queries'
import {deleteRule, notificationKeys, notificationsRequest, rulePayload, rulesPath, saveRuleEnabled} from '../../lib/notifications'
import {
    RuleFormSchema,
    type DestinationRead,
    type NotificationEventRead,
    type RuleFormValues,
    type RuleRead,
} from '../../types/schemas/notifications'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {getZodDefaults} from '../../utils/defaultZod'
import {createSelectRegistry} from '../../utils/selectRegistry'
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import SimpleSelect from '../common/SimpleSelect'
import {DeliveryReg, PersonalScopeReg, SharedScopeReg, eventRegistry} from './registries'

type CollectionName = {id: number; title: string}

type RulesProps = {
    rules: RuleRead[]
    events: NotificationEventRead[]
    /** Destinations a rule on Settings can use; a person's own rules only push. */
    destinations: DestinationRead[]
    personal: boolean
}

function joinNames(names: string[]): string {
    if (names.length <= 1) return names[0] ?? ''
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** One rule as the sentence it stands for. */
export function RuleSentence({rule, events, destinations, collections, personal}: {
    rule: RuleRead
    events: NotificationEventRead[]
    destinations: DestinationRead[]
    collections: CollectionName[]
    personal: boolean
}) {
    const event = events.find((item) => item.event === rule.event)
    const chosen = collections.filter(({id}) => rule.collectionIds.includes(id)).map(({title}) => title)
    const targets = [
        ...(rule.push ? [personal ? 'push it to my devices' : 'push it to administrators'] : []),
        ...destinations.filter(({id}) => rule.destinationIds.includes(id)).map((destination) => (
            destination.purpose === 'action'
                ? (destination.kind === 'webhook' ? `call ${destination.name}` : destination.kind === 'script' ? `run ${destination.name}` : `refresh ${destination.name}`)
                : `send it to ${destination.name}`
        )),
    ]
    const where = !event?.collections ? null
        : rule.collectionScope === 'added' ? 'in Collections I added'
            : rule.collectionScope === 'chosen' ? `in ${joinNames(chosen) || 'the chosen Collections'}`
                : personal ? 'in any Collection I can see' : 'in any Collection'
    const delivery = rule.delivery === 'daily' ? `in a daily summary at ${rule.summaryTime}`
        : rule.delivery === 'grouped' ? 'grouped per Collection, hourly' : null
    return (
        <p className="notif-sentence">
            When <b>{event?.when ?? rule.event}</b>{where ? <> {where}</> : null},{' '}
            {targets.length ? <b>{joinNames(targets)}</b> : <span className="notif-sentence__muted">do nothing yet</span>}
            {delivery ? <> {delivery}</> : null}.
        </p>
    )
}

export default function Rules({rules, events, destinations, personal}: RulesProps) {
    const queryClient = useQueryClient()
    const collectionsQuery = useCollections()
    const collections: CollectionName[] = (collectionsQuery.data ?? []).map(({id, title}) => ({id, title}))
    const [editing, setEditing] = useState<RuleRead | 'new' | null>(null)
    const [deleting, setDeleting] = useState<RuleRead | null>(null)
    const key = personal ? notificationKeys.personal : notificationKeys.rules

    const toggle = async (rule: RuleRead, enabled: boolean) => {
        try {
            await saveRuleEnabled(personal, {...rule, enabled})
            await queryClient.invalidateQueries({queryKey: key})
        } catch (error) {
            toast.error((error as Error).message)
        }
    }

    const remove = async (rule: RuleRead) => {
        try {
            await deleteRule(personal, rule.id)
            await queryClient.invalidateQueries({queryKey: key})
            toast.success('Rule deleted')
        } catch (error) {
            toast.error((error as Error).message)
        } finally {
            setDeleting(null)
        }
    }

    return (
        <>
            {rules.length === 0 ? <p className="notif-empty">No rules yet.</p> : (
                <ul className="notif-list">
                    {rules.map((rule) => (
                        <li key={rule.id} className={`notif-row notif-row--compact notif-row--rule${rule.enabled ? '' : ' is-off'}`}>
                            <Switch
                                id={`notif-rule-${rule.id}`}
                                aria-label={rule.enabled ? 'Turn this rule off' : 'Turn this rule on'}
                                checked={rule.enabled}
                                onChange={(checked) => void toggle(rule, checked)}
                                checkedIcon={false}
                                uncheckedIcon={false}
                                height={20}
                                width={36}
                            />
                            <div className="notif-row__main">
                                <RuleSentence rule={rule} events={events} destinations={destinations} collections={collections} personal={personal}/>
                            </div>
                            <div className="notif-row__actions">
                                <button type="button" className="btn btn-secondary" aria-label="Edit rule" onClick={() => setEditing(rule)}>
                                    <FontAwesomeIcon icon={faIcon('fass', 'pen')} aria-hidden="true"/>
                                </button>
                                <button type="button" className="btn btn-secondary" aria-label="Delete rule" onClick={() => setDeleting(rule)}>
                                    <FontAwesomeIcon icon={faIcon('fass', 'trash')} aria-hidden="true"/>
                                </button>
                            </div>
                        </li>
                    ))}
                </ul>
            )}
            <div className="notif-toolbar">
                <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
                    <FontAwesomeIcon icon={faIcon('fass', 'plus')} aria-hidden="true"/> Add rule
                </button>
            </div>
            {editing !== null ? (
                <RuleDialog
                    rule={editing === 'new' ? null : editing}
                    events={events}
                    destinations={destinations}
                    collections={collections}
                    personal={personal}
                    onDismiss={() => setEditing(null)}
                />
            ) : null}
            {deleting ? (
                <ConfirmDialog
                    open
                    title="Delete this rule?"
                    icon={faIcon('fass', 'trash')}
                    iconTone="danger"
                    onDismiss={() => setDeleting(null)}
                    confirmButton={{label: 'Delete', className: 'btn-danger', onClick: () => remove(deleting)}}
                >
                    <RuleSentence rule={deleting} events={events} destinations={destinations} collections={collections} personal={personal}/>
                    {deleting.defaultKey && !personal ? <p className="help">Restore default rules brings it back.</p> : null}
                </ConfirmDialog>
            ) : null}
        </>
    )
}

function RuleDialog({rule, events, destinations, collections, personal, onDismiss}: {
    rule: RuleRead | null
    events: NotificationEventRead[]
    destinations: DestinationRead[]
    collections: CollectionName[]
    personal: boolean
    onDismiss: () => void
}) {
    const queryClient = useQueryClient()
    const form = useForm<RuleFormValues>({
        resolver: zodResolver(RuleFormSchema),
        defaultValues: rule ? {
            enabled: rule.enabled, event: rule.event, collectionScope: rule.collectionScope, collectionIds: rule.collectionIds,
            push: rule.push, destinationIds: rule.destinationIds, delivery: rule.delivery, summaryTime: rule.summaryTime,
        } : {...getZodDefaults(RuleFormSchema), event: events[0]?.event ?? 'episode_downloaded'},
    })
    const {control, register, watch, setValue, formState: {errors, isSubmitting}} = form
    const eventKey = watch('event')
    const scope = watch('collectionScope')
    const delivery = watch('delivery')
    const event = events.find((item) => item.event === eventKey)

    const eventReg = useMemo(() => eventRegistry(events), [events])
    const usable = destinations.filter((destination) => destination.purpose === 'message' || (event?.actions && delivery !== 'daily'))
    const destinationReg = useMemo(() => createSelectRegistry(
        'NotificationDestinations',
        Object.fromEntries(usable.map((destination) => [String(destination.id), {label: destination.name}])),
        usable.map((destination) => String(destination.id)),
    ), [usable])
    const collectionReg = useMemo(() => createSelectRegistry(
        'NotificationCollections',
        Object.fromEntries(collections.map((collection) => [String(collection.id), {label: collection.title}])),
        collections.map((collection) => String(collection.id)),
    ), [collections])

    const submit = buildServerAwareSubmit<RuleFormValues>(
        form,
        async (values) => {
            const payload = rulePayload(values)
            return rule
                ? notificationsRequest(`${rulesPath(personal)}/${rule.id}`, 'PUT', payload)
                : notificationsRequest(rulesPath(personal), 'POST', payload)
        },
        {
            successStatuses: [200, 201],
            fallbackField: 'event',
            genericMessage: 'Could not save the rule',
            onSuccess: async () => {
                await queryClient.invalidateQueries({queryKey: personal ? notificationKeys.personal : notificationKeys.rules})
                toast.success(rule ? 'Rule saved' : 'Rule added')
                onDismiss()
            },
        },
    )

    return (
        <ConfirmDialog
            open
            className="notif-dialog"
            title={rule ? 'Edit rule' : 'Add rule'}
            icon={faIcon('fass', 'bolt')}
            onDismiss={onDismiss}
            dismissOnOverlayClick={false}
            confirmButton={{
                label: rule ? 'Save rule' : 'Add rule',
                icon: faIcon('fass', isSubmitting ? 'spinner' : 'check'),
                iconSpin: isSubmitting,
                disabled: isSubmitting,
                onClick: () => submit(),
            }}
        >
            <form className="notif-form notif-rule-form" onSubmit={submit} noValidate>
                {errors.root?.message ? <div className="form-error-card" role="alert">{errors.root.message}</div> : null}
                <div className="form-row">
                    <label htmlFor="notif-rule-event">When</label>
                    <Controller control={control} name="event" render={({field}) => (
                        <SimpleSelect inputId="notif-rule-event" registry={eventReg} value={field.value} onChange={(value) => {
                            field.onChange(value)
                            if (value === 'everything') setValue('delivery', 'daily')
                        }}/>
                    )}/>
                    {errors.event ? <span className="error">{errors.event.message}</span> : null}
                </div>
                {event?.collections ? (
                    <div className="form-row">
                        <label htmlFor="notif-rule-scope">In</label>
                        <Controller control={control} name="collectionScope" render={({field}) => (
                            <SimpleSelect inputId="notif-rule-scope" registry={personal ? PersonalScopeReg : SharedScopeReg}
                                          value={field.value} onChange={field.onChange}/>
                        )}/>
                        {errors.collectionScope ? <span className="error">{errors.collectionScope.message}</span> : null}
                        {scope === 'chosen' ? (
                            <Controller control={control} name="collectionIds" render={({field}) => (
                                <Select
                                    inputId="notif-rule-collections"
                                    aria-label="Collections"
                                    isMulti
                                    closeMenuOnSelect={false}
                                    classNamePrefix="select"
                                    placeholder="Choose Collections"
                                    options={collectionReg.options}
                                    value={collectionReg.options.filter((option) => (field.value ?? []).includes(Number(option.value)))}
                                    onChange={(options) => field.onChange(options.map((option) => Number(option.value)))}
                                />
                            )}/>
                        ) : null}
                        {errors.collectionIds ? <span className="error">{errors.collectionIds.message}</span> : null}
                    </div>
                ) : null}
                <div className="form-row">
                    <span>Then</span>
                    {personal ? <p className="notif-sentence">Push it to my devices.</p> : (
                        <label className="notif-check">
                            <input type="checkbox" {...register('push')}/>
                            <span>Push it to administrators’ devices</span>
                        </label>
                    )}
                    {errors.push ? <span className="error">{errors.push.message}</span> : null}
                    {!personal ? (
                        <>
                            <Controller control={control} name="destinationIds" render={({field}) => (
                                <Select
                                    inputId="notif-rule-destinations"
                                    aria-label="Destinations and services"
                                    isMulti
                                    closeMenuOnSelect={false}
                                    classNamePrefix="select"
                                    placeholder={usable.length ? 'And send it to, or refresh, call or run…' : 'Add a destination first to send it elsewhere'}
                                    options={destinationReg.options}
                                    value={destinationReg.options.filter((option) => (field.value ?? []).includes(Number(option.value)))}
                                    onChange={(options) => field.onChange(options.map((option) => Number(option.value)))}
                                />
                            )}/>
                            {!event?.actions ? <span className="help">Actions such as a media server refresh only run on downloads.</span> : null}
                        </>
                    ) : null}
                    {errors.destinationIds ? <span className="error">{errors.destinationIds.message}</span> : null}
                </div>
                <div className="notif-inline">
                    <div className="form-row notif-grow">
                        <label htmlFor="notif-rule-delivery">Send it</label>
                        <Controller control={control} name="delivery" render={({field}) => (
                            <SimpleSelect inputId="notif-rule-delivery" registry={DeliveryReg} value={field.value} onChange={field.onChange}/>
                        )}/>
                        {errors.delivery ? <span className="error">{errors.delivery.message}</span> : null}
                    </div>
                    {delivery === 'daily' ? (
                        <div className="form-row">
                            <label htmlFor="notif-rule-time">At</label>
                            <input id="notif-rule-time" className="input" type="time" {...register('summaryTime')}/>
                            {errors.summaryTime ? <span className="error">{errors.summaryTime.message}</span> : null}
                        </div>
                    ) : null}
                </div>
                <button type="submit" hidden/>
            </form>
        </ConfirmDialog>
    )
}
