import {useEffect, useState} from 'react'
import {useForm} from 'react-hook-form'
import {z} from 'zod'
import {zodResolver} from '@hookform/resolvers/zod'
import {buildServerAwareSubmit} from '../utils/buildServerAwareSubmit'

const Schema = z.object({
    timezone: z.string().min(1),
    download_root: z.string().startsWith('/'),
    temporary_download_root: z.string().startsWith('/'),
    max_concurrent_downloads: z.number().int().min(1).max(32),
    max_download_attempts: z.number().int().min(1).max(20),
})
type Fields = z.infer<typeof Schema>
type Settings = {values: Record<string, any>; environmentOverrides: Record<string, string>}
const apiBase = () => (window as any).appConfig?.API_URL || '/api'

export default function VodLoftSettingsPage() {
    const [actor, setActor] = useState<{username: string; role: string} | null>(null)
    const [settings, setSettings] = useState<Settings | null>(null)
    const [notice, setNotice] = useState<string | null>(null)
    const form = useForm<Fields>({resolver: zodResolver(Schema)})
    useEffect(() => {
        void fetch(`${apiBase()}/vodloft/me`, {credentials: 'include'}).then(r => r.json()).then(me => {
            setActor(me)
            if (me.role !== 'admin') return
            void fetch(`${apiBase()}/settings`, {credentials: 'include'}).then(r => {
                if (!r.ok) throw new Error('Could not read settings')
                return r.json()
            }).then(data => {
                setSettings(data)
                form.reset({timezone: data.values.timezone, download_root: data.values.downloadSettings.downloadRoot,
                    temporary_download_root: data.values.downloadSettings.temporaryDownloadRoot,
                    max_concurrent_downloads: data.values.downloadSettings.maxConcurrentDownloads,
                    max_download_attempts: data.values.downloadSettings.maxDownloadAttempts})
            }).catch(error => setNotice(String(error)))
        }).catch(error => setNotice(String(error)))
    }, [])
    const paths: Record<keyof Fields, string> = {timezone: 'timezone', download_root: 'downloadSettings.downloadRoot',
        temporary_download_root: 'downloadSettings.temporaryDownloadRoot', max_concurrent_downloads: 'downloadSettings.maxConcurrentDownloads',
        max_download_attempts: 'downloadSettings.maxDownloadAttempts'}
    const submit = buildServerAwareSubmit(form, async values => {
        if (!settings) return
        const changed = Object.keys(form.formState.dirtyFields) as (keyof Fields)[]
        if (!changed.length) {setNotice('Settings are already saved.'); return}
        const downloadSettings = {...settings.values.downloadSettings, downloadRoot: values.download_root,
            temporaryDownloadRoot: values.temporary_download_root, maxConcurrentDownloads: values.max_concurrent_downloads,
            maxDownloadAttempts: values.max_download_attempts}
        return fetch(`${apiBase()}/settings`, {method: 'PUT', credentials: 'include', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({values: {...settings.values, timezone: values.timezone, downloadSettings},
                changedFields: changed.map(key => paths[key])})})
    }, {fieldAlias: Object.fromEntries(Object.entries(paths).map(([key, value]) => [`values.${value}`, key])),
        onSuccess: (_, {form}) => {form.reset(form.getValues()); setNotice('Settings saved.')}})
    return <section className="page"><h1>Settings</h1>
        <p>Signed in as {actor?.username ?? '…'} · {actor?.role}</p>
        {settings && <form onSubmit={submit} style={{display: 'grid', gap: 16, maxWidth: 650}}>
            {Object.entries(paths).map(([name, path]) => {
                const field = name as keyof Fields
                const numeric = field.startsWith('max_')
                const managed = settings.environmentOverrides?.[path]
                return <label key={name}>{({timezone: 'Timezone', download_root: 'Library folder',
                    temporary_download_root: 'Temporary download folder', max_concurrent_downloads: 'Concurrent downloads',
                    max_download_attempts: 'Download attempts'})[field]}
                    <input type={numeric ? 'number' : 'text'} {...form.register(field, {valueAsNumber: numeric})} readOnly={!!managed}/>
                    {managed && <small>Managed by {managed}</small>}
                    {form.formState.errors[field] && <span role="alert">{form.formState.errors[field]?.message}</span>}
                </label>
            })}
            {form.formState.errors.root && <p role="alert">{form.formState.errors.root.message}</p>}
            <div><button className="btn btn-primary" disabled={form.formState.isSubmitting}>Save settings</button></div>
        </form>}
        {notice && <p role="status">{notice}</p>}
        {actor?.role === 'admin' && <p>Set the administrator password with <code>WL_ADMIN_AUTH__PASSWORD</code> in your deployment.
            Source accounts, updates, and media-server connections are managed in Management.</p>}
        <button type="button" className="btn" onClick={() => void fetch(`${apiBase()}/auth/logout`,
            {method: 'POST', credentials: 'include'}).then(() => window.location.reload())}>Sign out</button>
    </section>
}
