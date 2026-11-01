import {useMemo, useState} from 'react'
import {Controller, useFieldArray, useForm, useWatch} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'
import Switch from 'react-switch'
import {useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'

import {SegmentedOptions} from '../SegmentedOptions'
import SimpleSelect from '../common/SimpleSelect'
import {AREAS, LEVELS, type Area, type Level} from '../../lib/access'
import {AREA_LABELS, DOMAIN_SUGGESTIONS, cleanDomain, describeAccess, levelLabel, sourceTakesAnyDomain} from '../../lib/accessLabels'
import {USERS_KEY, usersRequest} from '../../lib/users'
import {useSources} from '../../lib/queries'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {createSelectRegistry} from '../../utils/selectRegistry'
import {hashPasswordForAdminAuth} from '../../utils/security/adminAuth'
import type {AccessOptionsRead, UserAccessInput, UserRead} from '../../types/schemas/user'
import type {SourceRead} from '../../types/schemas/source'

const SourceRowSchema = z.object({
    sourceKey: z.string(),
    allowed: z.boolean(),
    allDomains: z.boolean(),
    domains: z.array(z.string()),
})

const UserEditorSchema = z.object({
    username: z.string().trim().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$/, 'Use 2 to 64 letters, digits, dots, dashes or underscores, starting with a letter or digit'),
    password: z.string(),
    templateKey: z.string().nullable(),
    levels: z.record(z.string(), z.enum(LEVELS)),
    allSources: z.boolean(),
    sources: z.array(SourceRowSchema),
    membersOnly: z.boolean(),
    deleteFiles: z.boolean(),
}).superRefine((values, ctx) => {
    if (!values.allSources) {
        values.sources.forEach((row, index) => {
            if (row.allowed && !row.allDomains && row.domains.length === 0) {
                ctx.addIssue({code: 'custom', path: ['sources', index, 'domains'], message: 'Add at least one domain, or allow all of them'})
            }
        })
    }
})
type UserEditorValues = z.infer<typeof UserEditorSchema>

type Props = {
    user: UserRead | null
    options: AccessOptionsRead
    onDone: () => void
}

function sourceRows(sources: SourceRead[], user: UserRead | null): UserEditorValues['sources'] {
    return sources.map((source) => {
        const limit = user?.sources?.find((entry) => entry.sourceKey === source.id)
        return {
            sourceKey: source.id,
            allowed: Boolean(limit),
            // A Source that takes any site starts limited to listed domains.
            allDomains: limit ? limit.domains === null : !sourceTakesAnyDomain(source),
            domains: limit?.domains ?? [],
        }
    })
}

export function toAccessInput(values: UserEditorValues): UserAccessInput {
    return {
        templateKey: values.templateKey,
        levels: values.levels,
        sources: values.allSources ? null : values.sources
            .filter((row) => row.allowed)
            .map((row) => ({sourceKey: row.sourceKey, domains: row.allDomains ? null : row.domains})),
        membersOnly: values.membersOnly,
        deleteFiles: values.deleteFiles,
    }
}

/** Create or change a user: template, a level per area, Source and domain limits, and the summary in words. */
export default function UserEditor({user, options, onDone}: Props) {
    const queryClient = useQueryClient()
    const {data: sources = []} = useSources()
    const creating = user === null
    const downloader = options.templates.find((template) => template.key === 'downloader') ?? options.templates[0]

    const form = useForm<UserEditorValues>({
        resolver: zodResolver(UserEditorSchema),
        values: {
            username: user?.username ?? '',
            password: '',
            templateKey: user ? user.templateKey : downloader.key,
            levels: user ? {...user.levels} : {...downloader.levels},
            allSources: user ? user.sources === null : true,
            sources: sourceRows(sources, user),
            membersOnly: user?.membersOnly ?? false,
            deleteFiles: user ? user.deleteFiles : downloader.deleteFiles,
        },
        resetOptions: {keepDirtyValues: true},
        shouldFocusError: true,
    })
    const {control, register, setValue, getValues, formState: {errors, isSubmitting}} = form
    const sourceFields = useFieldArray({control, name: 'sources'})
    const watched = useWatch({control}) as UserEditorValues
    const administrator = watched.levels?.users === 'manage'

    const templateRegistry = useMemo(() => createSelectRegistry(
        'AccessTemplate',
        Object.fromEntries(options.templates.map((template) => [template.key, {label: template.name}])),
        options.templates.map((template) => template.key),
    ), [options.templates])
    const currentTemplate = options.templates.find((template) => template.key === watched.templateKey)

    const pickTemplate = (key: string) => {
        const template = options.templates.find((entry) => entry.key === key)
        if (!template) return
        setValue('templateKey', key, {shouldDirty: true})
        setValue('levels', {...template.levels}, {shouldDirty: true})
        setValue('deleteFiles', template.deleteFiles, {shouldDirty: true})
    }

    const setLevel = (area: Area, level: Level) => {
        const levels = {...getValues('levels'), [area]: level}
        setValue('levels', levels, {shouldDirty: true})
        // The template name only stays while the list still matches it.
        const key = getValues('templateKey')
        const template = options.templates.find((entry) => entry.key === key)
        if (template && AREAS.some((name) => (template.levels[name] ?? 'none') !== (levels[name] ?? 'none'))) {
            setValue('templateKey', null, {shouldDirty: true})
        }
    }

    const onSubmit = buildServerAwareSubmit<UserEditorValues>(
        form,
        async (values) => {
            const access = toAccessInput(values)
            if (creating) {
                return usersRequest('', 'POST', {
                    username: values.username.trim(),
                    passwordHash: await hashPasswordForAdminAuth(values.password),
                    access,
                })
            }
            return usersRequest(`/${user.id}`, 'PATCH', {username: values.username.trim(), access})
        },
        {
            successStatuses: [200, 201],
            fieldAlias: {passwordHash: 'password'},
            rootServerValidationMessage: creating ? 'The user was not created.' : 'Your changes were not saved.',
            onSuccess: async () => {
                await queryClient.invalidateQueries({queryKey: USERS_KEY})
                toast.success(creating ? 'User created. Give them their one-time password.' : 'User saved')
                onDone()
            },
        },
    )

    if (creating) {
        // The first password is one-time: the server makes them choose their own at sign-in.
        register('password', {validate: (value) => value.length >= 7 || 'Use at least 7 characters'})
    }

    const summary = describeAccess(toAccessInput(watched), sources, watched.username?.trim() || 'This user')
    const groups = [...new Set(AREAS.map((area) => AREA_LABELS[area].group))]

    return (
        <form className="form user-editor" onSubmit={onSubmit} noValidate>
            <div className="user-editor__heading">
                <h2>{creating ? 'Add user' : `Edit ${user.username}`}</h2>
                {currentTemplate ? null : <span className="user-editor__customised">Customised</span>}
            </div>
            {errors.root && <div className="form-error-card" role="alert" aria-live="polite">{String(errors.root.message)}</div>}

            <div className="user-editor__columns">
                <div className="user-editor__main">
                    <div className="form-row">
                        <label htmlFor="user-username">Username</label>
                        <input id="user-username" className="input" autoComplete="off" autoCapitalize="none" {...register('username')} />
                        {errors.username && <div className="error" role="alert">{String(errors.username.message)}</div>}
                    </div>
                    {creating && (
                        <div className="form-row">
                            <label htmlFor="user-password">One-time password</label>
                            <input id="user-password" className="input" type="text" autoComplete="off" {...register('password')} />
                            <small className="user-editor__help">They choose their own password the first time they sign in.</small>
                            {errors.password && <div className="error" role="alert">{String(errors.password.message)}</div>}
                        </div>
                    )}
                    <div className="form-row">
                        <label htmlFor="user-template">Template</label>
                        <SimpleSelect
                            inputId="user-template"
                            registry={templateRegistry}
                            value={watched.templateKey}
                            placeholder={currentTemplate ? undefined : 'Customised'}
                            onChange={pickTemplate}
                        />
                        <small className="user-editor__help">Picking a template fills in the list below; you can change any line after.</small>
                    </div>

                    <table className="user-editor__levels">
                        <tbody>
                            {groups.map((group) => (
                                <FragmentRows key={group} group={group}>
                                    {AREAS.filter((area) => AREA_LABELS[area].group === group).map((area) => {
                                        const offered = options.areas.find((entry) => entry.area === area)?.levels ?? LEVELS
                                        const forced = administrator && area !== 'users'
                                        return (
                                            <tr key={area}>
                                                <th scope="row">
                                                    <span>{AREA_LABELS[area].label}</span>
                                                    <small>{AREA_LABELS[area].help}</small>
                                                </th>
                                                <td>
                                                    <SegmentedOptions<string>
                                                        name={`level-${area}`}
                                                        ariaLabel={AREA_LABELS[area].label}
                                                        value={forced ? offered[offered.length - 1] : (watched.levels?.[area] ?? 'none')}
                                                        disabled={forced}
                                                        onChange={(value) => setLevel(area, value as Level)}
                                                        options={offered.map((level) => ({value: level, label: levelLabel(area, level as Level)}))}
                                                    />
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </FragmentRows>
                            ))}
                        </tbody>
                    </table>
                    <label className="user-editor__switch">
                        <Controller
                            control={control}
                            name="deleteFiles"
                            render={({field}) => (
                                <Switch checked={administrator || field.value} disabled={administrator} onChange={field.onChange} height={20} width={40} />
                            )}
                        />
                        <span>May delete downloaded files from disk</span>
                    </label>
                </div>

                <aside className="user-editor__side">
                    <h3>Sources {watched.username?.trim() || 'this user'} may use</h3>
                    {administrator ? (
                        <p className="user-editor__help">Administrators may use every Source.</p>
                    ) : (
                        <>
                            <Controller
                                control={control}
                                name="allSources"
                                render={({field}) => (
                                    <SegmentedOptions<string>
                                        name="all-sources"
                                        ariaLabel="Sources"
                                        value={field.value ? 'all' : 'some'}
                                        onChange={(value) => field.onChange(value === 'all')}
                                        options={[{value: 'all', label: 'Every Source'}, {value: 'some', label: 'Only these'}]}
                                    />
                                )}
                            />
                            {!watched.allSources && sourceFields.fields.map((row, index) => {
                                const source = sources.find((entry) => entry.id === row.sourceKey)
                                if (!source) return null
                                const current = watched.sources?.[index]
                                return (
                                    <div className="user-editor__source" key={row.id}>
                                        <label className="user-editor__switch">
                                            <Controller
                                                control={control}
                                                name={`sources.${index}.allowed`}
                                                render={({field}) => <Switch checked={field.value} onChange={field.onChange} height={20} width={40} />}
                                            />
                                            <b>{source.name}</b>
                                        </label>
                                        {current?.allowed && (
                                            <SourceDomains
                                                source={source}
                                                allDomains={current.allDomains}
                                                domains={current.domains}
                                                error={errors.sources?.[index]?.domains?.message}
                                                onAllDomains={(all) => setValue(`sources.${index}.allDomains`, all, {shouldDirty: true})}
                                                onDomains={(domains) => setValue(`sources.${index}.domains`, domains, {shouldDirty: true, shouldValidate: form.formState.isSubmitted})}
                                            />
                                        )}
                                    </div>
                                )
                            })}
                            {errors.sources?.message && <div className="error" role="alert">{String(errors.sources.message)}</div>}
                            <label className="user-editor__switch user-editor__members">
                                <Controller
                                    control={control}
                                    name="membersOnly"
                                    render={({field}) => <Switch checked={field.value} onChange={field.onChange} height={20} width={40} />}
                                />
                                <span>
                                    Members-only media
                                    <small>Uses the memberships signed in under Settings › Sources, such as the Daily Wire’s.</small>
                                </span>
                            </label>
                        </>
                    )}
                    <div className="user-editor__summary" aria-live="polite">
                        <h3>In words</h3>
                        {summary.map((line) => <p key={line}>{line}</p>)}
                    </div>
                </aside>
            </div>

            <div className="actions">
                <button type="button" className="btn" onClick={onDone}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={isSubmitting}>{creating ? 'Create user' : 'Save'}</button>
            </div>
        </form>
    )
}

function FragmentRows({group, children}: {group: string, children: React.ReactNode}) {
    return (
        <>
            <tr className="user-editor__group"><th colSpan={2}>{group}</th></tr>
            {children}
        </>
    )
}

function SourceDomains({source, allDomains, domains, error, onAllDomains, onDomains}: {
    source: SourceRead
    allDomains: boolean
    domains: string[]
    error?: string
    onAllDomains: (all: boolean) => void
    onDomains: (domains: string[]) => void
}) {
    const [typed, setTyped] = useState('')
    const anyDomain = sourceTakesAnyDomain(source)
    const suggestions = anyDomain
        ? DOMAIN_SUGGESTIONS.filter((entry) => entry.domains.some((domain) => !domains.includes(domain)))
        : source.domains.filter((domain) => !domains.includes(domain)).map((domain) => ({label: domain, domains: [domain]}))
    const add = (more: string[]) => onDomains([...new Set([...domains, ...more.map(cleanDomain).filter(Boolean)])])

    return (
        <div className="user-editor__domains">
            <SegmentedOptions<string>
                name={`domains-${source.id}`}
                ariaLabel={`Domains of ${source.name}`}
                value={allDomains ? 'all' : 'some'}
                onChange={(value) => onAllDomains(value === 'all')}
                options={[
                    {value: 'all', label: anyDomain ? 'Every site' : 'All its domains'},
                    {value: 'some', label: 'Only these domains'},
                ]}
            />
            {!allDomains && (
                <>
                    <div className="user-editor__chips">
                        {domains.map((domain) => (
                            <button type="button" key={domain} className="user-editor__chip" title="Remove" onClick={() => onDomains(domains.filter((entry) => entry !== domain))}>
                                {domain} ×
                            </button>
                        ))}
                        <input
                            className="input user-editor__domain-input"
                            placeholder="+ domain"
                            value={typed}
                            aria-label={`Add a domain for ${source.name}`}
                            onChange={(event) => setTyped(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter' || event.key === ',') {
                                    event.preventDefault()
                                    if (typed.trim()) add([typed])
                                    setTyped('')
                                }
                            }}
                            onBlur={() => {
                                if (typed.trim()) add([typed])
                                setTyped('')
                            }}
                        />
                    </div>
                    {suggestions.length > 0 && (
                        <div className="user-editor__suggestions">
                            {suggestions.map((entry) => (
                                <button type="button" key={entry.label} className="btn" onClick={() => add(entry.domains)}>
                                    + {entry.label}
                                </button>
                            ))}
                        </div>
                    )}
                    <small className="user-editor__help">Subdomains count too, so youtube.com also allows m.youtube.com.</small>
                    {error && <div className="error" role="alert">{error}</div>}
                </>
            )}
        </div>
    )
}
