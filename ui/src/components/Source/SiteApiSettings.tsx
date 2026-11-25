import {useState} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'

import {apiUrl} from '../../lib/api'
import {ApiKeyRejectedError, changeSiteApi} from '../../lib/queries'
import {SiteAuthenticationReadSchema, type SiteApiRead, type SiteAuthenticationRead} from '../../types/schemas/source'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'

type SiteApiValues = {values: Record<string, string>}

/** Every value of the Site's API is filled in, except a secret that is stored already, which stays as it is. */
function siteApiSchema(api: SiteApiRead, hints: Record<string, string>) {
    return z.object({
        values: z.object(Object.fromEntries(api.fields.map((field) => [
            field.key,
            field.secret && hints[field.key]
                ? z.string().trim()
                : z.string().trim().min(1, `Fill in the ${field.label.charAt(0).toLowerCase()}${field.label.slice(1)}`),
        ]))),
    })
}

/** A Site's own free API, such as Twitch's: fill in, test or remove its values, and how to get them. */
export default function SiteApiSettings({site, onSaved}: {site: SiteAuthenticationRead; onSaved: (site: SiteAuthenticationRead) => void}) {
    const api = site.siteApi!
    const status = site.siteApiStatus
    const hints = status?.hints ?? {}
    const setUp = Boolean(status?.setUp)
    const queryClient = useQueryClient()
    const [busy, setBusy] = useState<'test' | 'remove' | null>(null)
    const [actionError, setActionError] = useState<{message: string; fixUrl: string | null} | null>(null)
    const [tested, setTested] = useState(false)

    const empty = () => ({values: Object.fromEntries(api.fields.map((field) => [
        field.key, field.secret ? '' : hints[field.key] ?? '',
    ]))})
    const form = useForm<SiteApiValues>({resolver: zodResolver(siteApiSchema(api, hints)), defaultValues: empty()})
    const {register, formState: {errors, isSubmitting}} = form

    const saved = (listing: SiteAuthenticationRead) => {
        onSaved(listing)
        // Add Media only offers a search that goes through the API once it is set up.
        if (api.searches) void queryClient.invalidateQueries({queryKey: ['sources']})
    }

    const onSubmit = buildServerAwareSubmit<SiteApiValues, SiteApiValues, SiteAuthenticationRead>(
        form,
        async (data) => {
            setActionError(null)
            setTested(false)
            return fetch(`${apiUrl()}/sources/authentication/${encodeURIComponent(site.key)}/api`, {
                method: 'PUT',
                credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({values: data.values}),
            })
        },
        {
            parseSuccess: async (response) => SiteAuthenticationReadSchema.parse(await response.json()),
            onSuccess: async (listing, {resetForm}) => {
                saved(listing)
                setTested(true)
                resetForm({values: Object.fromEntries(api.fields.map((field) => [
                    field.key, field.secret ? '' : listing.siteApiStatus?.hints[field.key] ?? '',
                ]))})
            },
        },
    )

    const run = async (action: 'test' | 'remove') => {
        setBusy(action)
        setActionError(null)
        setTested(false)
        try {
            const listing = await changeSiteApi(site.key, action)
            saved(listing)
            if (action === 'test') setTested(true)
            if (action === 'remove') form.reset({values: Object.fromEntries(api.fields.map((field) => [field.key, '']))})
        } catch (exc) {
            setActionError({
                message: exc instanceof Error ? exc.message : String(exc),
                fixUrl: exc instanceof ApiKeyRejectedError ? exc.fixUrl : null,
            })
        } finally {
            setBusy(null)
        }
    }

    const problem = actionError ?? (status?.problem ? {message: status.problem, fixUrl: null} : null)
    const working = busy !== null || isSubmitting

    return (
        <div className="source-setting youtube-api">
            <div className="source-setting-copy">
                <h4>
                    {api.name}{' '}
                    {setUp && <span className={`youtube-api-state ${status?.problem ? 'is-problem' : 'is-ok'}`}>{status?.problem ? 'Not working' : 'Connected'}</span>}
                </h4>
                <p>{api.benefits}</p>
                <form className="site-api-form" onSubmit={onSubmit} noValidate>
                    {api.fields.map((field) => {
                        const error = errors.values?.[field.key]
                        return (
                            <label key={field.key} className="site-api-form__field">
                                <span>{field.label}</span>
                                <input
                                    className="input"
                                    type={field.secret ? 'password' : 'text'}
                                    autoComplete="off"
                                    aria-invalid={Boolean(error)}
                                    placeholder={field.secret && hints[field.key]
                                        ? `Ending in ${hints[field.key].replace('…', '')}. Fill in a new one to replace it`
                                        : undefined}
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
                        <button className="btn btn-primary" type="submit" disabled={working}>
                            {isSubmitting ? 'Testing…' : 'Save and test'}
                        </button>
                        {setUp && (
                            <button className="btn" type="button" onClick={() => void run('test')} disabled={working}>
                                {busy === 'test' ? 'Testing…' : 'Test'}
                            </button>
                        )}
                        {setUp && (
                            <button className="btn" type="button" onClick={() => void run('remove')} disabled={working}>
                                Remove
                            </button>
                        )}
                    </div>
                </form>
                {problem && (
                    <p className="source-setting-error" role="alert">
                        {problem.message}
                        {problem.fixUrl && <>{' '}<a href={problem.fixUrl} target="_blank" rel="noreferrer">Open it on {site.name}</a></>}
                    </p>
                )}
                {tested && !problem && !Object.keys(errors).length && <p className="youtube-api-ok" role="status">{site.name} accepts these.</p>}
                {!setUp && api.steps.length > 0 && (
                    <details className="youtube-api-guide">
                        <summary>Get them for free in a few minutes</summary>
                        <ol>
                            {api.steps.map((step) => (
                                <li key={step.text}>
                                    <span>{step.text}</span>
                                    {step.url && <a className="btn" href={step.url} target="_blank" rel="noreferrer">{step.button ?? 'Open'}</a>}
                                </li>
                            ))}
                            <li><span>Fill them in above and choose Save and test.</span></li>
                        </ol>
                    </details>
                )}
            </div>
        </div>
    )
}
