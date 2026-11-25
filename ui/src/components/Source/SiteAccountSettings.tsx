import {useEffect, useRef, useState} from 'react'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'

import {apiUrl} from '../../lib/api'
import {CodeSignInEndedError, cancelCodeSignIn, finishCodeSignIn, signOutOfSite, startCodeSignIn} from '../../lib/queries'
import {
    SiteAuthenticationReadSchema, type AccountSignInRead, type CodeSignInRead, type SiteAuthenticationRead,
} from '../../types/schemas/source'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'

type AccountValues = {values: Record<string, string>}

const errorText = (exc: unknown) => exc instanceof Error ? exc.message : String(exc)

/** Every value the sign-in asks for is filled in. */
function accountSchema(signIn: AccountSignInRead) {
    return z.object({
        values: z.object(Object.fromEntries(signIn.fields.map((field) => [
            field.key,
            (field.secret ? z.string() : z.string().trim())
                .min(1, `Fill in your ${field.label.charAt(0).toLowerCase()}${field.label.slice(1)}`),
        ]))),
    })
}

/** How to get what the sign-in asks for, such as where SoundCloud keeps its token. */
function SignInSteps({signIn}: {signIn: AccountSignInRead}) {
    if (!signIn.steps.length) return null
    return (
        <details className="youtube-api-guide">
            <summary>Where to find it</summary>
            <ol>
                {signIn.steps.map((step) => (
                    <li key={step.text}>
                        <span>{step.text}</span>
                        {step.url && <a className="btn" href={step.url} target="_blank" rel="noreferrer">{step.button ?? 'Open'}</a>}
                    </li>
                ))}
                <li><span>Fill it in above and choose Sign in.</span></li>
            </ol>
        </details>
    )
}

/** Signing in with what the user fills in: an email address and password, or a token. */
function AccountForm({site, signIn, onSaved}: {
    site: SiteAuthenticationRead
    signIn: AccountSignInRead
    onSaved: (site: SiteAuthenticationRead) => void
}) {
    const empty = () => ({values: Object.fromEntries(signIn.fields.map((field) => [field.key, '']))})
    const form = useForm<AccountValues>({resolver: zodResolver(accountSchema(signIn)), defaultValues: empty()})
    const {register, formState: {errors, isSubmitting}} = form

    const onSubmit = buildServerAwareSubmit<AccountValues, AccountValues, SiteAuthenticationRead>(
        form,
        async (data) => fetch(`${apiUrl()}/sources/authentication/${encodeURIComponent(site.key)}/account`, {
            method: 'PUT',
            credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({values: data.values}),
        }),
        {
            parseSuccess: async (response) => SiteAuthenticationReadSchema.parse(await response.json()),
            onSuccess: async (listing, {resetForm}) => {
                onSaved(listing)
                resetForm(empty())
            },
        },
    )

    return (
        <>
            <form className="site-api-form" onSubmit={onSubmit} noValidate>
                {signIn.fields.map((field) => {
                    const error = errors.values?.[field.key]
                    return (
                        <label key={field.key} className="site-api-form__field">
                            <span>{field.label}</span>
                            <input
                                className="input"
                                type={field.secret ? 'password' : field.key === 'email' ? 'email' : 'text'}
                                autoComplete={field.secret ? 'current-password' : 'username'}
                                aria-invalid={Boolean(error)}
                                {...register(`values.${field.key}`)}
                            />
                            {error && <span className="error" role="alert">{String(error.message)}</span>}
                        </label>
                    )
                })}
                {errors.values?.root && <div className="error" role="alert">{String(errors.values.root.message)}</div>}
                {errors.values && 'message' in errors.values && typeof errors.values.message === 'string' && (
                    <div className="error" role="alert">{errors.values.message}</div>
                )}
                {errors.root && <div className="error" role="alert">{String(errors.root.message)}</div>}
                <div className="youtube-api-key">
                    <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
                        {isSubmitting ? 'Signing in…' : 'Sign in'}
                    </button>
                </div>
            </form>
            <SignInSteps signIn={signIn}/>
        </>
    )
}

/** Signing in with a code the user enters on the Site's own page, the way a TV app signs in. */
function CodeSignIn({site, onSaved}: {site: SiteAuthenticationRead; onSaved: (site: SiteAuthenticationRead) => void}) {
    const [code, setCode] = useState<CodeSignInRead | null>(null)
    const [starting, setStarting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [copied, setCopied] = useState(false)
    const waiting = useRef<{controller: AbortController; flowId: string} | null>(null)

    /** Stop waiting here, and tell VODLoft to stop asking the Site. */
    const stopWaiting = () => {
        const current = waiting.current
        waiting.current = null
        if (!current) return
        current.controller.abort()
        void cancelCodeSignIn(site.key, current.flowId).catch(() => undefined)
    }

    useEffect(() => stopWaiting, [])

    const start = async () => {
        stopWaiting()
        setStarting(true)
        setError(null)
        setCopied(false)
        try {
            const started = await startCodeSignIn(site.key)
            setCode(started)
            const controller = new AbortController()
            waiting.current = {controller, flowId: started.id}
            try {
                onSaved(await finishCodeSignIn(site.key, started.id, controller.signal))
                waiting.current = null
                setCode(null)
            } catch (exc) {
                if (controller.signal.aborted) return
                waiting.current = null
                setCode(null)
                setError(exc instanceof CodeSignInEndedError ? exc.message : errorText(exc))
            }
        } catch (exc) {
            setError(errorText(exc))
        } finally {
            setStarting(false)
        }
    }

    const cancel = () => {
        stopWaiting()
        setCode(null)
    }

    const copy = async () => {
        if (!code) return
        try {
            await navigator.clipboard.writeText(code.userCode)
            setCopied(true)
        } catch {
            setCopied(false)
        }
    }

    if (!code) {
        return (
            <>
                <div className="youtube-api-key">
                    <button className="btn btn-primary" type="button" onClick={() => void start()} disabled={starting}>
                        {starting ? 'Getting a code…' : `Sign in to ${site.name}`}
                    </button>
                </div>
                {error && <p className="source-setting-error" role="alert">{error}</p>}
            </>
        )
    }
    return (
        <div className="code-sign-in" aria-live="polite">
            <ol className="code-sign-in__steps">
                <li>
                    <div className="code-sign-in__step">
                        <span>Open {site.name}&apos;s activation page, signed in with your account.</span>
                        <a className="btn" href={code.verificationUrl} target="_blank" rel="noreferrer">Open the page</a>
                    </div>
                </li>
                <li>
                    <div className="code-sign-in__step">
                        <span>Enter this code there:</span>
                        <span className="code-sign-in__code">
                            <code>{code.userCode}</code>
                            <button className="btn" type="button" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy'}</button>
                        </span>
                    </div>
                </li>
            </ol>
            <p className="settings-field__help">Waiting for you to enter the code. It works for {Math.round(code.expiresIn / 60)} minutes.</p>
            <div className="youtube-api-key">
                <button className="btn" type="button" onClick={cancel}>Cancel</button>
            </div>
        </div>
    )
}

/** Signing in with the user's own account on a Site, such as Nebula's email and password or Twitch's code. */
export default function SiteAccountSettings({site, onSaved}: {site: SiteAuthenticationRead; onSaved: (site: SiteAuthenticationRead) => void}) {
    const signIn = site.accountSignIn!
    const status = site.accountStatus
    const [signingOut, setSigningOut] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const signOut = async () => {
        setSigningOut(true)
        setError(null)
        try {
            onSaved(await signOutOfSite(site.key))
        } catch (exc) {
            setError(errorText(exc))
        } finally {
            setSigningOut(false)
        }
    }

    return (
        <div className="source-setting youtube-api">
            <div className="source-setting-copy">
                <h4>
                    {site.name} account{' '}
                    {status?.signedIn && (
                        <span className={`youtube-api-state ${status.problem ? 'is-problem' : 'is-ok'}`}>
                            {status.problem ? 'Not working' : 'Signed in'}
                        </span>
                    )}
                </h4>
                <p>{signIn.benefits}</p>
                {signIn.caution && <p className="settings-field__help">{signIn.caution}</p>}
                {status?.signedIn && (
                    <>
                        <p>{status.account ? `Signed in as ${status.account}.` : `Signed in on ${site.name}.`}</p>
                        {status.problem && <p className="source-setting-error" role="alert">{status.problem}</p>}
                        <div className="youtube-api-key">
                            <button className="btn" type="button" onClick={() => void signOut()} disabled={signingOut}>
                                {signingOut ? 'Signing out…' : 'Sign out'}
                            </button>
                        </div>
                    </>
                )}
                {/* A sign-in that stopped working can be done again in its place. */}
                {(!status?.signedIn || status.problem) && (signIn.kind === 'device_code'
                    ? <CodeSignIn site={site} onSaved={onSaved}/>
                    : <AccountForm site={site} signIn={signIn} onSaved={onSaved}/>)}
                {error && <p className="source-setting-error" role="alert">{error}</p>}
            </div>
        </div>
    )
}
