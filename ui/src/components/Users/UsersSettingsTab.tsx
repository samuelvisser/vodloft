import './Users.css'
import {useState} from 'react'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'
import Switch from 'react-switch'
import {useQueryClient} from '@tanstack/react-query'
import toast from 'react-hot-toast'

import ConfirmDialog from '../ConfirmDialog/ConfirmDialog'
import {SegmentedOptions} from '../SegmentedOptions'
import {SettingsLoading, SettingsSection} from '../Settings/SettingsControls'
import UserEditor from './UserEditor'
import {getAccess} from '../../lib/access'
import {AREA_LABELS} from '../../lib/accessLabels'
import {
    USERS_KEY,
    USER_ACCOUNTS_KEY,
    errorMessage,
    useAccessOptions,
    useUserAccountsSettings,
    useUsers,
    usersRequest,
} from '../../lib/users'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {hashPasswordForAdminAuth} from '../../utils/security/adminAuth'
import type {AccessOptionsRead, UserRead} from '../../types/schemas/user'

/** Settings › Users: turning accounts on, and everyone who may sign in. */
export default function UsersSettingsTab() {
    const settings = useUserAccountsSettings()
    const options = useAccessOptions()
    const users = useUsers(Boolean(settings.data?.enabled))
    const [editing, setEditing] = useState<UserRead | 'new' | null>(null)

    if (settings.isError) return <p role="alert">Could not load user accounts: {settings.error.message}</p>
    if (!settings.data || !options.data) return <SettingsLoading />

    if (editing !== null) {
        return (
            <UserEditor
                user={editing === 'new' ? null : editing}
                options={options.data}
                onDone={() => setEditing(null)}
            />
        )
    }

    return (
        <>
            <AccountsSwitch enabled={settings.data.enabled} administrators={settings.data.administrators} environmentPassword={settings.data.environmentPassword} />
            {settings.data.enabled && (
                <SettingsSection
                    title="Users"
                    description="Everyone who may sign in, and what they may see and change."
                    bodyClassName="users-section"
                >
                    <div className="users-toolbar">
                        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>Add user</button>
                    </div>
                    {users.isError && <p role="alert">Could not load users: {users.error.message}</p>}
                    <ul className="users-list">
                        {(users.data ?? []).map((user) => (
                            <UserRow key={user.id} user={user} options={options.data} onEdit={() => setEditing(user)} />
                        ))}
                    </ul>
                </SettingsSection>
            )}
        </>
    )
}

const FirstAdministratorSchema = z.object({
    username: z.string().trim().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$/, 'Use 2 to 64 letters, digits, dots, dashes or underscores, starting with a letter or digit'),
    password: z.string().min(7, 'Use at least 7 characters'),
    confirmPassword: z.string(),
}).refine((values) => values.password === values.confirmPassword, {path: ['confirmPassword'], message: 'The two passwords differ'})
type FirstAdministratorValues = z.infer<typeof FirstAdministratorSchema>

function AccountsSwitch({enabled, administrators, environmentPassword}: {enabled: boolean, administrators: number, environmentPassword: boolean}) {
    const queryClient = useQueryClient()
    const [askFirst, setAskFirst] = useState(false)
    const [confirmOff, setConfirmOff] = useState(false)
    const [busy, setBusy] = useState(false)
    const form = useForm<FirstAdministratorValues>({
        resolver: zodResolver(FirstAdministratorSchema),
        defaultValues: {username: getAccess()?.user?.username ?? 'admin', password: '', confirmPassword: ''},
    })

    const turn = async (on: boolean) => {
        setBusy(true)
        try {
            const response = await usersRequest('/settings', 'PUT', {enabled: on})
            if (!response.ok) throw new Error(await errorMessage(response))
            // Turning accounts on or off changes who this browser is signed in as.
            window.location.reload()
        } catch (error) {
            toast.error((error as Error).message)
            setBusy(false)
        }
    }

    const createFirst = buildServerAwareSubmit<FirstAdministratorValues>(
        form,
        async (values) => usersRequest('/settings', 'PUT', {
            enabled: true,
            firstAdministrator: {username: values.username.trim(), passwordHash: await hashPasswordForAdminAuth(values.password)},
        }),
        {
            successStatuses: [200],
            fieldAlias: {'firstAdministrator.username': 'username', 'firstAdministrator.passwordHash': 'password', firstAdministrator: 'username'},
            rootServerValidationMessage: 'User accounts were not turned on.',
            onSuccess: async () => {
                await queryClient.invalidateQueries({queryKey: USER_ACCOUNTS_KEY})
                window.location.reload()
            },
        },
    )

    const {register, formState: {errors, isSubmitting}} = form

    return (
        <SettingsSection
            title="User accounts"
            description="Give each person their own sign-in, with only the parts of VODLoft they need."
        >
            <div className="settings-field settings-toggle-field settings-field--wide">
                <div className="settings-toggle-field__control">
                    <div>
                        <label htmlFor="user-accounts-enabled">Sign in with user accounts</label>
                        <div className="settings-field__help">
                            {enabled
                                ? `On. ${administrators} administrator${administrators === 1 ? '' : 's'} can sign in.${environmentPassword ? ' The environment password only works for recovery while no administrator can sign in.' : ''}`
                                : environmentPassword
                                    ? 'Off: everyone signs in with the one admin password from the environment.'
                                    : 'Off: VODLoft asks for no password at all. Turn this on before you open VODLoft to others.'}
                        </div>
                    </div>
                    <Switch
                        id="user-accounts-enabled"
                        checked={enabled || askFirst}
                        disabled={busy}
                        onChange={(on) => {
                            if (on && administrators === 0) setAskFirst(true)
                            else if (on) void turn(true)
                            else if (askFirst) setAskFirst(false)
                            else setConfirmOff(true)
                        }}
                    />
                </div>
            </div>

            {askFirst && !enabled && (
                <form className="form users-first-admin settings-field--wide" onSubmit={createFirst} noValidate>
                    <p>Create the first administrator. You will be signed in as them right away.</p>
                    {errors.root && <div className="form-error-card" role="alert">{String(errors.root.message)}</div>}
                    <div className="form-row">
                        <label htmlFor="first-admin-username">Username</label>
                        <input id="first-admin-username" className="input" autoComplete="username" autoCapitalize="none" {...register('username')} />
                        {errors.username && <div className="error" role="alert">{String(errors.username.message)}</div>}
                    </div>
                    <div className="form-row">
                        <label htmlFor="first-admin-password">Password</label>
                        <input id="first-admin-password" className="input" type="password" autoComplete="new-password" {...register('password')} />
                        {errors.password && <div className="error" role="alert">{String(errors.password.message)}</div>}
                    </div>
                    <div className="form-row">
                        <label htmlFor="first-admin-confirm">Password again</label>
                        <input id="first-admin-confirm" className="input" type="password" autoComplete="new-password" {...register('confirmPassword')} />
                        {errors.confirmPassword && <div className="error" role="alert">{String(errors.confirmPassword.message)}</div>}
                    </div>
                    <div className="actions">
                        <button type="button" className="btn" onClick={() => setAskFirst(false)}>Cancel</button>
                        <button type="submit" className="btn btn-primary" disabled={isSubmitting}>Turn on user accounts</button>
                    </div>
                </form>
            )}

            <ConfirmDialog
                open={confirmOff}
                title="Turn off user accounts?"
                onDismiss={() => setConfirmOff(false)}
                iconTone="danger"
                confirmButton={{label: 'Turn off', className: 'btn btn-danger', disabled: busy, onClick: () => turn(false)}}
            >
                <p>
                    Everyone is signed out, and VODLoft goes back to {environmentPassword ? 'the one admin password from the environment' : 'asking for no password at all'}.
                    The users stay, so turning accounts on again brings them back.
                </p>
            </ConfirmDialog>
        </SettingsSection>
    )
}

function describeLevels(user: UserRead, options: AccessOptionsRead): string {
    if (user.administrator) return 'Administrator'
    const template = options.templates.find((entry) => entry.key === user.templateKey)
    const visible = Object.entries(user.levels).filter(([, level]) => level !== 'none').length
    return template ? template.name : `Customised · ${visible} area${visible === 1 ? '' : 's'}`
}

function UserRow({user, options, onEdit}: {user: UserRead, options: AccessOptionsRead, onEdit: () => void}) {
    const queryClient = useQueryClient()
    const [dialog, setDialog] = useState<'password' | 'delete' | null>(null)
    const [oneTime, setOneTime] = useState('')
    const [profiles, setProfiles] = useState<'transfer' | 'delete'>('transfer')
    const [busy, setBusy] = useState(false)
    const me = getAccess()?.user?.id === user.id

    const run = async (request: () => Promise<Response>, done: string) => {
        setBusy(true)
        try {
            const response = await request()
            if (!response.ok) throw new Error(await errorMessage(response))
            await queryClient.invalidateQueries({queryKey: USERS_KEY})
            toast.success(done)
            setDialog(null)
            setOneTime('')
        } catch (error) {
            toast.error((error as Error).message)
        } finally {
            setBusy(false)
        }
    }

    const limits = user.sources === null || user.administrator
        ? null
        : user.sources.map((limit) => limit.domains ? limit.domains.join(', ') : limit.sourceKey).join('; ') || 'no Sources'

    return (
        <li className={`users-row${user.enabled ? '' : ' is-disabled'}`}>
            <div className="users-row__who">
                <b>{user.username}</b>
                {me && <span className="users-badge">You</span>}
                {!user.enabled && <span className="users-badge is-off">Disabled</span>}
                {user.mustChangePassword && <span className="users-badge">One-time password</span>}
                <small>
                    {describeLevels(user, options)}
                    {limits ? ` · Only ${limits}` : ''}
                    {' · '}
                    {user.lastLoginAt ? `Last signed in ${user.lastLoginAt.toLocaleString()}` : 'Never signed in'}
                </small>
            </div>
            <div className="users-row__actions">
                <button type="button" className="btn" onClick={onEdit}>Edit</button>
                <button type="button" className="btn" onClick={() => setDialog('password')}>Reset password</button>
                {!me && (
                    <button type="button" className="btn" disabled={busy} onClick={() => void run(
                        () => usersRequest(`/${user.id}`, 'PATCH', {enabled: !user.enabled}),
                        user.enabled ? `${user.username} is disabled and signed out` : `${user.username} may sign in again`,
                    )}>
                        {user.enabled ? 'Disable' : 'Enable'}
                    </button>
                )}
                <button type="button" className="btn" disabled={busy} title="Sign this user out on every device" onClick={() => void run(
                    () => usersRequest(`/${user.id}/sign-out`, 'POST'),
                    `${user.username} is signed out everywhere`,
                )}>
                    Sign out everywhere
                </button>
                {!me && <button type="button" className="btn btn-danger" onClick={() => setDialog('delete')}>Delete</button>}
            </div>

            <ConfirmDialog
                open={dialog === 'password'}
                title={`Reset the password of ${user.username}`}
                onDismiss={() => setDialog(null)}
                confirmButton={{
                    label: 'Set one-time password',
                    className: 'btn btn-primary',
                    disabled: busy || oneTime.length < 7,
                    onClick: async () => run(
                        async () => usersRequest(`/${user.id}/password`, 'POST', {passwordHash: await hashPasswordForAdminAuth(oneTime)}),
                        `${user.username} must choose a new password at their next sign-in`,
                    ),
                }}
            >
                <p>{user.username} is signed out everywhere and must choose their own password after signing in with this one.</p>
                <input className="input" type="text" autoComplete="off" value={oneTime} placeholder="At least 7 characters" aria-label="One-time password" onChange={(event) => setOneTime(event.target.value)} />
            </ConfirmDialog>

            <ConfirmDialog
                open={dialog === 'delete'}
                title={`Delete ${user.username}?`}
                onDismiss={() => setDialog(null)}
                iconTone="danger"
                confirmButton={{
                    label: 'Delete user',
                    className: 'btn btn-danger',
                    disabled: busy,
                    onClick: () => run(() => usersRequest(`/${user.id}?streamProfiles=${profiles}`, 'DELETE'), `${user.username} is deleted`),
                }}
            >
                <p>They can no longer sign in. Disabling them instead keeps their account for later.</p>
                <p>Their Stream Profiles, and the feeds apps follow through them:</p>
                <SegmentedOptions<string>
                    name={`delete-profiles-${user.id}`}
                    ariaLabel="Their Stream Profiles"
                    value={profiles}
                    onChange={(value) => setProfiles(value as 'transfer' | 'delete')}
                    options={[
                        {value: 'transfer', label: 'Give them to me', description: 'The feeds keep working.'},
                        {value: 'delete', label: 'Delete them', description: 'The feeds stop working.'},
                    ]}
                />
            </ConfirmDialog>
        </li>
    )
}

export const USERS_AREA_HELP = AREA_LABELS.users.help
