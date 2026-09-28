import {useEffect, useRef, useState} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {z} from 'zod'

const URLForm = z.object({url: z.url().startsWith('https://').or(z.url().startsWith('http://')),
    source_id: z.string(), connection_id: z.string()})
type URLFields = z.infer<typeof URLForm>
type Source = {source_id: string; display_name: string; capabilities: string[];
    configuration_schema: {name: string; label: string; kind: string; required: boolean}[]}
type Connection = {id: number; source_id: string; name: string; has_secret: boolean; enabled: boolean}
type Reference = {source_id: string; domain: string; namespace: string; upstream_id: string; url: string}
type Preview = {kind: string; title: string; description?: string; artwork_url?: string; reference: Reference; entries: {title: string; position: number}[]; enumeration_complete: boolean}
type Item = {id: number; title: string; description?: string; kind: string; domain: string; downloaded: boolean; playback_type?: string; artwork_url?: string; entries?: Item[]; extras?: Item[]}
type Home = {continue: (Item & {seconds: number})[]; recent: Item[];
    activity: {id: number; item_id: number; state: string}[]; issues: {kind: string; id: number}[]}
type Job = {id: number; state: string; error?: string; cancel_requested?: boolean;
    operation_id?: string; progress?: number}
type Profile = {id: number; name: string; domain: string; preferred_format: string; output_template: string; applicable_kinds: string[]; enabled: boolean}
type DownloadPolicy = {id: number; name: string; local_profile_ids: number[]; backfill: string; newest_count: number; enabled: boolean}
type StreamProfile = {id: number; name: string; format: string; enabled: boolean}
type Target = {id: number; name: string; kind: string; base_url: string; library_id: string; enabled: boolean}
type RuntimeState = {active: Record<string, string>; installed: Record<string, string[]>;
    policy: Record<string, {automatic: boolean; pinned_version: string | null; channel: string}>}
type Catalogue = {source_id: string; items: {hostname: string; display_name: string}[]; exhaustive: boolean}
const ProfileFormSchema = z.object({
    name: z.string().min(1),
    preferred_format: z.enum(['format_720p', 'format_1080p', 'format_4k', 'format_audio_only']),
    output_template: z.string().min(16),
})
type ProfileFields = z.infer<typeof ProfileFormSchema>

const base = () => `${(window as any).appConfig?.API_URL || '/api'}/vodloft`
async function api<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${base()}${path}`, {credentials: 'include', ...options,
        headers: {'Content-Type': 'application/json', ...options?.headers}})
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `HTTP ${response.status}`)
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

export default function WebMediaPage() {
    const {register, handleSubmit, formState: {errors}} = useForm<URLFields>({
        resolver: zodResolver(URLForm), defaultValues: {url: '', source_id: '', connection_id: ''},
    })
    const [sources, setSources] = useState<Source[]>([])
    const [connections, setConnections] = useState<Connection[]>([])
    const [importConnectionId, setImportConnectionId] = useState<number | null>(null)
    const [items, setItems] = useState<Item[]>([])
    const [home, setHome] = useState<Home | null>(null)
    const [preview, setPreview] = useState<Preview | null>(null)
    const [selected, setSelected] = useState<Item | null>(null)
    const [job, setJob] = useState<Job | null>(null)
    const [profiles, setProfiles] = useState<Profile[]>([])
    const [downloadPolicies, setDownloadPolicies] = useState<DownloadPolicy[]>([])
    const [streamProfiles, setStreamProfiles] = useState<StreamProfile[]>([])
    const [targets, setTargets] = useState<Target[]>([])
    const [runtimes, setRuntimes] = useState<RuntimeState | null>(null)
    const [catalogues, setCatalogues] = useState<Catalogue[]>([])
    const [runResult, setRunResult] = useState<string | null>(null)
    const [profileId, setProfileId] = useState<number | null>(null)
    const [outputPreview, setOutputPreview] = useState<string | null>(null)
    const [feedUrl, setFeedUrl] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const refresh = () => Promise.all([api<Item[]>('/library').then(setItems),
        api<Home>('/home').then(setHome)]).catch(e => setError(String(e)))
    useEffect(() => {
        void api<Source[]>('/sources').then(setSources).catch(e => setError(String(e)))
        void api<Connection[]>('/sources/connections').then(setConnections).catch(e => setError(String(e)))
        void api<Target[]>('/integrations').then(setTargets).catch(e => setError(String(e)))
        void api<RuntimeState>('/sources/runtimes').then(setRuntimes).catch(e => setError(String(e)))
        void api<Catalogue[]>('/sources/domains').then(setCatalogues).catch(e => setError(String(e)))
        void refresh()
    }, [])
    useEffect(() => {
        if (!job || !['queued', 'resolving', 'downloading', 'processing', 'verifying', 'finalizing'].includes(job.state)) return
        const timer = window.setInterval(() => {
            void api<Job>(`/jobs/${job.id}`).then(next => {
                setJob(next)
                if (next.state === 'available') {
                    void refresh()
                    if (selected) void api<Item>(`/library/${selected.id}`).then(setSelected)
                }
            }).catch(e => setError(String(e)))
        }, 2500)
        return () => window.clearInterval(timer)
    }, [job?.id, job?.state, selected?.id])

    const resolve = handleSubmit(async fields => {
        setBusy(true); setError(null); setPreview(null)
        try {
            setPreview(await api<Preview>('/resolve', {method: 'POST',
                body: JSON.stringify({url: fields.url, source_id: fields.source_id || null,
                    connection_id: fields.connection_id ? Number(fields.connection_id) : null})}))
            setImportConnectionId(fields.connection_id ? Number(fields.connection_id) : null)
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    })
    const importPreview = async () => {
        if (!preview) return
        setBusy(true); setError(null)
        try {
            const item = await api<Item>('/import', {method: 'POST',
                body: JSON.stringify({snapshot: preview, connection_id: importConnectionId})})
            setPreview(null); await refresh()
            setSelected(await api<Item>(`/library/${item.id}`))
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    const open = async (id: number) => {
        setError(null); setJob(null); setFeedUrl(null); setOutputPreview(null)
        try {
            const item = await api<Item>(`/library/${id}`)
            setSelected(item)
            const available = await api<Profile[]>(`/profiles${item.kind === 'collection' ? '' : `?domain=${encodeURIComponent(item.domain)}`}`)
            setProfiles(available)
            setProfileId(available.find(profile => profile.enabled && profile.applicable_kinds.includes(item.kind))?.id ?? null)
            if (item.kind === 'collection') {
                setDownloadPolicies(await api<DownloadPolicy[]>(`/library/${id}/download-profiles`))
                setStreamProfiles(await api<StreamProfile[]>(`/library/${id}/stream-profiles`))
            }
        } catch (e) { setError(String(e)) }
    }
    const download = async (id: number) => {
        setError(null)
        try { setJob(await api<Job>(`/library/${id}/download`, {method: 'POST', body: JSON.stringify({profile_id: profileId})})) }
        catch (e) { setError(String(e)) }
    }
    const refreshCollection = async (id: number) => {
        setBusy(true); setError(null)
        try {
            setSelected(await api<Item>(`/library/${id}/refresh`, {method: 'POST'}).then(() => api<Item>(`/library/${id}`)))
            await refresh()
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    const runDownloadPolicy = async (policyId: number) => {
        setError(null)
        try {
            const result = await api<{queued_job_ids: number[]; skipped: {item_id: number; reason: string}[]}>(
                `/download-profiles/${policyId}/run`, {method: 'POST'})
            setRunResult(`${result.queued_job_ids.length} downloads queued; ${result.skipped.length} members skipped.`)
        } catch (e) { setError(String(e)) }
    }
    const createStreamFeed = async (streamId: number) => {
        setError(null)
        try { setFeedUrl((await api<{url: string}>(`/stream-profiles/${streamId}/feed`, {method: 'POST'})).url) }
        catch (e) { setError(String(e)) }
    }
    const showOutputPreview = async (id: number, itemId: number, createdProfile?: Profile) => {
        setError(null)
        try {
            const profile = createdProfile ?? profiles.find(p => p.id === id)
            const extension = profile?.preferred_format === 'format_audio_only' ? 'mp3' : 'mp4'
            const result = await api<{path: string}>(`/profiles/${id}/preview?item_id=${itemId}&extension=${extension}`, {method: 'POST'})
            setOutputPreview(result.path)
        } catch (e) { setError(String(e)) }
    }

    return <section className="view" aria-labelledby="web-media-title">
        <div className="view-header"><div><h1 id="web-media-title">Web media</h1>
            <p className="view-description">Add a URL, review its media, and keep a local copy for playback.</p></div></div>
        <form onSubmit={resolve} style={{display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'end', marginBottom: 24}}>
            <label style={{flex: '1 1 340px'}}>Media URL
                <input type="url" {...register('url')} placeholder="https://…" style={{width: '100%'}} />
                {errors.url && <span role="alert">Enter a public HTTP or HTTPS URL.</span>}
            </label>
            <label>Source
                <select {...register('source_id')}><option value="">Automatic</option>
                    {sources.map(source => <option value={source.source_id} key={source.source_id}>{source.display_name}</option>)}</select>
            </label>
            <label>Connection <select {...register('connection_id')}><option value="">Anonymous</option>
                {connections.filter(connection => connection.enabled).map(connection => <option key={connection.id} value={connection.id}>
                    {connection.name} ({connection.source_id})</option>)}</select></label>
            <button className="btn btn-primary" type="submit" disabled={busy}>Resolve URL</button>
        </form>
        {error && <div className="form-error-card" role="alert">{error}</div>}
        {preview && <section style={{marginBottom: 32}}><h2>{preview.title}</h2>
            <p>{preview.kind} · {preview.reference.domain} · {preview.reference.source_id}</p>
            {preview.description && <p>{preview.description.slice(0, 350)}</p>}
            {preview.kind === 'collection' && <p>{preview.entries.length} preview entries
                {!preview.enumeration_complete && ' (more entries are available)'}</p>}
            <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void importPreview()}>Add to library</button>
        </section>}
        {home && <section style={{marginBottom: 24}} aria-label="Home">
            <h2>Continue</h2>
            {home.continue.filter(item => item.downloaded).length === 0 && <p>Your local playback will appear here.</p>}
            <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>{home.continue.filter(item => item.downloaded).map(item =>
                <button className="btn" type="button" key={item.id} onClick={() => void open(item.id)}>
                    {item.title} · {Math.floor(item.seconds / 60)} min</button>)}</div>
            <p>Recent arrivals: {home.recent.length}{home.activity.length > 0 &&
                ` · ${home.activity.length} active download${home.activity.length === 1 ? '' : 's'}`}{home.issues.length > 0 &&
                ` · ${home.issues.length} issue${home.issues.length === 1 ? '' : 's'}`}</p>
        </section>}
        <details style={{marginBottom: 24}}><summary>Sources, Domains and media servers</summary>
            <h3>Installed Sources</h3>
            {sources.map(source => <p key={source.source_id}>{source.display_name} · {source.capabilities.join(', ')}
                {runtimes?.active[source.source_id] && ` · runtime ${runtimes.active[source.source_id]}`}{' '}
                <button className="btn" type="button" onClick={() => void api<unknown>(
                    `/sources/${encodeURIComponent(source.source_id)}/rollback`, {method: 'POST'})
                    .then(() => api<RuntimeState>('/sources/runtimes').then(setRuntimes)).catch(e => setError(String(e)))}>Rollback</button>{' '}
                <label>Automatic updates <input type="checkbox"
                    checked={runtimes?.policy[source.source_id]?.automatic ?? true}
                    onChange={event => void api<unknown>(`/sources/${encodeURIComponent(source.source_id)}/policy`, {
                        method: 'PUT', body: JSON.stringify({automatic: event.target.checked,
                            pinned_version: runtimes?.policy[source.source_id]?.pinned_version ?? null,
                            channel: runtimes?.policy[source.source_id]?.channel ?? 'stable'})})
                        .then(() => api<RuntimeState>('/sources/runtimes').then(setRuntimes)).catch(e => setError(String(e)))} /></label>
                {' '}<label>Channel <select value={runtimes?.policy[source.source_id]?.channel ?? 'stable'}
                    onChange={event => void api<unknown>(`/sources/${encodeURIComponent(source.source_id)}/policy`, {
                        method: 'PUT', body: JSON.stringify({automatic: runtimes?.policy[source.source_id]?.automatic ?? true,
                            pinned_version: runtimes?.policy[source.source_id]?.pinned_version ?? null,
                            channel: event.target.value})})
                        .then(() => api<RuntimeState>('/sources/runtimes').then(setRuntimes)).catch(e => setError(String(e)))}>
                    <option value="stable">Stable</option><option value="beta">Beta</option></select></label>
            </p>)}
            <button className="btn" type="button" onClick={() => void api<unknown>('/sources/runtimes/check', {method: 'POST'})
                .then(() => api<RuntimeState>('/sources/runtimes').then(setRuntimes)).catch(e => setError(String(e)))}>Check Source bundles</button>
            {Object.entries(runtimes?.installed ?? {}).map(([source, versions]) => versions.map(version =>
                <button className="btn" key={`${source}:${version}`} type="button"
                    onClick={() => void api<unknown>(`/sources/${encodeURIComponent(source)}/runtimes/${encodeURIComponent(version)}/activate`, {method: 'POST'})
                        .then(() => api<RuntimeState>('/sources/runtimes').then(setRuntimes)).catch(e => setError(String(e)))}>
                    Activate {source} {version}</button>))}
            <p>Discoverable Domains: {catalogues.flatMap(c => c.items.map(d => `${d.display_name} (${c.source_id})`)).join(', ') || 'None'}. URL resolution also checks sites outside non-exhaustive catalogues.</p>
            <h3>Source connections</h3>
            {connections.map(connection => <p key={connection.id}>{connection.name} · {connection.source_id}
                {connection.has_secret ? ' · credential stored' : ' · anonymous'}
                {!connection.enabled && ' · disabled'}</p>)}
            <ConnectionForm sources={sources} onCreated={connection => setConnections(current => [...current, connection])}/>
            <h3>Media servers</h3>
            {targets.map(target => <p key={target.id}>{target.name} · {target.kind} · library {target.library_id}{' '}
                <button type="button" className="btn" onClick={() => void api<unknown>(`/integrations/${target.id}/test`, {method: 'POST'})
                    .then(result => setRunResult(JSON.stringify(result))).catch(e => setError(String(e)))}>Test connection</button></p>)}
            <TargetForm onCreated={target => setTargets(current => [...current, target])}/>
        </details>
        <h2>Library</h2>
        {items.length === 0 && <p>No web media has been added yet.</p>}
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 12}}>
            {items.map(item =>
                <button type="button" key={item.id} onClick={() => void open(item.id)}
                        className="btn" style={{textAlign: 'left', minWidth: 200}}>
                    <strong>{item.title}</strong><br/>{item.kind} · {item.domain}{item.downloaded ? ' · Local' : ''}
                </button>)}
        </div>
        {selected && <section style={{marginTop: 32}}><h2>{selected.title}</h2>
            <p>{selected.kind} · {selected.domain}</p>
            <MetadataForm key={selected.id} item={selected} onSaved={updated => {
                setSelected(previous => previous?.id === updated.id ? {...previous, ...updated} : previous)
                void refresh()
            }}/>
            {selected.kind === 'collection' && <div style={{display: 'flex', gap: 10, marginBottom: 16}}>
                <button className="btn" type="button" disabled={busy} onClick={() => void refreshCollection(selected.id)}>Refresh collection</button>
                <button className="btn" type="button" disabled={busy} onClick={() => {
                    if (!window.confirm('Remove this collection and its feeds? Shared local media will remain available.')) return
                    void api<unknown>(`/library/${selected.id}`, {method: 'DELETE'})
                        .then(() => {setSelected(null); void refresh()}).catch(e => setError(String(e)))
                }}>Remove collection</button>
            </div>}
            {selected.kind === 'collection' && <section>
                <h3>Collection downloads</h3>
                {downloadPolicies.map(policy => <p key={policy.id}>{policy.name} · {policy.backfill}{' '}
                    <button type="button" className="btn" onClick={() => void runDownloadPolicy(policy.id)}>Run now</button></p>)}
                <DownloadPolicyForm collectionId={selected.id} profiles={profiles}
                    onCreated={policy => setDownloadPolicies(previous => [...previous, policy])}/>
                <h3>Collection feeds</h3>
                {streamProfiles.map(profile => <p key={profile.id}>{profile.name} · {profile.format}{' '}
                    <button type="button" className="btn" onClick={() => void createStreamFeed(profile.id)}>Get feed</button></p>)}
                <StreamProfileForm collectionId={selected.id}
                    onCreated={profile => setStreamProfiles(previous => [...previous, profile])}/>
                {runResult && <p role="status">{runResult}</p>}
            </section>}
            {feedUrl && <p><a href={feedUrl} target="_blank" rel="noreferrer">{feedUrl}</a></p>}
            {selected.kind !== 'collection' && <>
                <div style={{marginBottom: 16}}>
                    <label>Local Media Profile{' '}
                        <select value={profileId ?? ''} onChange={event => {
                            const id = Number(event.target.value)
                            setProfileId(id || null); setOutputPreview(null)
                            if (id) void showOutputPreview(id, selected.id)
                        }}>
                            <option value="">Choose a profile</option>
                            {profiles.filter(p => p.enabled && p.applicable_kinds.includes(selected.kind)).map(p =>
                                <option key={p.id} value={p.id}>{p.name} · {p.preferred_format}</option>)}
                        </select>
                    </label>
                    {outputPreview && <p>Output: <code>{outputPreview}</code></p>}
                </div>
                <DomainProfileForm domain={selected.domain} targets={targets} onCreated={profile => {
                    setProfiles(previous => [...previous, profile]); setProfileId(profile.id)
                    void showOutputPreview(profile.id, selected.id, profile)
                }}/>
                <button className="btn btn-primary" type="button" disabled={!profileId || !!job && !['failed', 'available'].includes(job.state)}
                        onClick={() => void download(selected.id)}>{selected.downloaded ? 'Download again' : 'Download'}</button>
                {job && <p role="status">Download: {job.state}{job.progress !== undefined ? ` · ${job.progress}%` : ''}
                    {job.error ? ` · ${job.error}` : ''}</p>}
                {job && ['queued', 'resolving', 'downloading', 'verifying'].includes(job.state) &&
                    <button className="btn" type="button" disabled={job.cancel_requested}
                        onClick={() => void api<Job>(`/jobs/${job.id}/cancel`, {method: 'POST'})
                            .then(() => setJob(previous => previous ? {...previous, cancel_requested: true} : null))
                            .catch(e => setError(String(e)))}>Cancel download</button>}
                {job && ['failed', 'canceled'].includes(job.state) &&
                    <button className="btn" type="button" onClick={() => void api<Job>(`/jobs/${job.id}/retry`, {method: 'POST'})
                        .then(next => setJob({...job, ...next})).catch(e => setError(String(e)))}>Retry download</button>}
                {selected.downloaded && <LocalPlayer key={selected.id} item={selected} />}
            </>}
            {selected.entries && <div style={{display: 'grid', gap: 8}}>{selected.entries.map(entry =>
                <button type="button" className="btn" key={entry.id} onClick={() => void open(entry.id)}
                        style={{textAlign: 'left'}}>{entry.title}{entry.downloaded ? ' · Local' : ''}</button>)}</div>}
            {selected.extras && selected.extras.length > 0 && <section><h3>Movie extras</h3>
                <div style={{display: 'grid', gap: 8}}>{selected.extras.map(extra =>
                    <button type="button" className="btn" key={extra.id} onClick={() => void open(extra.id)}
                        style={{textAlign: 'left'}}>{extra.title}{extra.downloaded ? ' · Local' : ''}</button>)}</div>
            </section>}
        </section>}
    </section>
}

function LocalPlayer({item}: {item: Item}) {
    const player = useRef<HTMLVideoElement & HTMLAudioElement>(null)
    const lastSaved = useRef(0)
    const [position, setPosition] = useState(0)
    useEffect(() => {
        void api<{seconds: number}>(`/library/${item.id}/progress`).then(data => setPosition(data.seconds))
    }, [item.id])
    const save = (completed = false) => {
        const current = player.current?.currentTime ?? 0
        if (!Number.isFinite(current)) return
        lastSaved.current = current
        void api(`/library/${item.id}/progress`, {method: 'PUT',
            body: JSON.stringify({seconds: current, completed})}).catch(() => {})
    }
    const common = {controls: true, preload: 'metadata' as const,
        src: `${base()}/library/${item.id}/play`,
        onLoadedMetadata: () => {
            if (player.current && position > 0 && position < player.current.duration - 1)
                player.current.currentTime = position
        },
        onTimeUpdate: () => {
            if (player.current && Math.abs(player.current.currentTime - lastSaved.current) >= 10) save()
        }, onPause: () => save(), onEnded: () => save(true),
        style: {display: 'block', width: 'min(100%, 800px)', marginTop: 16}}
    return item.playback_type === 'audio' ? <audio ref={player} {...common} /> : <video ref={player} {...common} />
}

function DomainProfileForm({domain, targets, onCreated}: {domain: string; targets: Target[]; onCreated: (profile: Profile) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [deliveryIds, setDeliveryIds] = useState<number[]>([])
    const {register, handleSubmit, formState: {errors, isSubmitting}, reset} = useForm<ProfileFields>({
        resolver: zodResolver(ProfileFormSchema),
        defaultValues: {name: `${domain} video`, preferred_format: 'format_1080p',
            output_template: '/downloads/{{ domain }}/{{ title }} - {{ id }}.ext'},
    })
    const submit = handleSubmit(async values => {
        setError(null)
        try {
            const profile = await api<Profile>('/profiles', {method: 'POST',
                body: JSON.stringify({...values, domain, applicable_kinds: ['video', 'movie', 'movie_extra'],
                    delivery_target_ids: deliveryIds})})
            onCreated(profile); setExpanded(false); reset()
        } catch (e) { setError(String(e)) }
    })
    if (!expanded) return <button type="button" className="btn" style={{marginRight: 12}}
                                  onClick={() => setExpanded(true)}>Create Local Media Profile</button>
    return <form onSubmit={submit} style={{display: 'grid', maxWidth: 640, gap: 10, marginBottom: 16}}>
        <h3>New profile for {domain}</h3>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Preferred format <select {...register('preferred_format')}>
            <option value="format_720p">Video up to 720p</option>
            <option value="format_1080p">Video up to 1080p</option>
            <option value="format_4k">Video up to 4K</option>
            <option value="format_audio_only">Audio only (MP3)</option>
        </select></label>
        <label>Output path template <input {...register('output_template')} style={{width: '100%'}} />
            {errors.output_template && <span role="alert">{errors.output_template.message}</span>}
        </label>
        {targets.length > 0 && <fieldset><legend>Media-server delivery</legend>{targets.map(target =>
            <label key={target.id} style={{display: 'block'}}><input type="checkbox" checked={deliveryIds.includes(target.id)}
                onChange={event => setDeliveryIds(current => event.target.checked ? [...current, target.id] :
                    current.filter(id => id !== target.id))} /> {target.name} ({target.kind})</label>)}</fieldset>}
        {error && <p role="alert">{error}</p>}
        <div><button type="submit" className="btn btn-primary" disabled={isSubmitting}>Save profile</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const DownloadPolicySchema = z.object({
    name: z.string().min(1),
    backfill: z.enum(['newest', 'all', 'date_range', 'metadata_only']).default('newest'),
    newest_count: z.coerce.number().int().min(1).max(1000).default(10),
    refresh_minutes: z.coerce.number().int().min(15).max(10080).default(60),
    published_after: z.string().default(''), published_before: z.string().default(''),
    title_contains: z.string().max(200).default(''),
})
type PolicyFields = z.input<typeof DownloadPolicySchema>

function DownloadPolicyForm({collectionId, profiles, onCreated}: {collectionId: number; profiles: Profile[]; onCreated: (profile: DownloadPolicy) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [selectedIds, setSelectedIds] = useState<number[]>([])
    const [error, setError] = useState<string | null>(null)
    const {register, handleSubmit, formState: {errors, isSubmitting}} = useForm<PolicyFields, unknown, z.output<typeof DownloadPolicySchema>>({
        resolver: zodResolver(DownloadPolicySchema),
        defaultValues: {name: 'New episodes', backfill: 'newest', newest_count: 10, refresh_minutes: 60,
            published_after: '', published_before: '', title_contains: ''},
    })
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>Create Download Profile</button>
    return <form onSubmit={handleSubmit(async values => {
        if (!selectedIds.length) { setError('Select at least one Local Media Profile.'); return }
        setError(null)
        try {
            const created = await api<DownloadPolicy>(`/library/${collectionId}/download-profiles`, {
                method: 'POST', body: JSON.stringify({...values,
                    published_after: values.published_after || null,
                    published_before: values.published_before || null,
                    title_contains: values.title_contains || null,
                    local_profile_ids: selectedIds, enabled: true})})
            onCreated(created); setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 620, margin: '12px 0'}}>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Backfill <select {...register('backfill')}><option value="newest">Newest N</option>
            <option value="all">All imported members</option><option value="date_range">Date range</option>
            <option value="metadata_only">Metadata only</option></select></label>
        <label>Newest count <input type="number" {...register('newest_count')} /></label>
        <label>Published on or after <input type="date" {...register('published_after')} /></label>
        <label>Published on or before <input type="date" {...register('published_before')} /></label>
        <label>Title contains <input {...register('title_contains')} /></label>
        <label>Refresh every (minutes) <input type="number" {...register('refresh_minutes')} /></label>
        <fieldset><legend>Local Media Profiles by member Domain</legend>{profiles.map(profile =>
            <label key={profile.id} style={{display: 'block'}}><input type="checkbox" checked={selectedIds.includes(profile.id)}
                onChange={event => setSelectedIds(current => event.target.checked ? [...current, profile.id] :
                    current.filter(id => id !== profile.id))} /> {profile.name} · {profile.domain} · {profile.preferred_format}</label>)}</fieldset>
        {profiles.length === 0 && <p>Create a Local Media Profile on a playable member first.</p>}
        {error && <p role="alert">{error}</p>}
        <div><button type="submit" className="btn btn-primary" disabled={isSubmitting}>Save Download Profile</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const StreamProfileSchema = z.object({name: z.string().min(1), format: z.enum(['audio', 'video']).default('audio')})
type StreamFields = z.input<typeof StreamProfileSchema>

function StreamProfileForm({collectionId, onCreated}: {collectionId: number; onCreated: (profile: StreamProfile) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const {register, handleSubmit, formState: {errors, isSubmitting}} = useForm<StreamFields, unknown, z.output<typeof StreamProfileSchema>>({
        resolver: zodResolver(StreamProfileSchema), defaultValues: {name: 'Podcast feed', format: 'audio'},
    })
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>Create Stream Profile</button>
    return <form onSubmit={handleSubmit(async values => {
        setError(null)
        try {
            onCreated(await api<StreamProfile>(`/library/${collectionId}/stream-profiles`, {method: 'POST',
                body: JSON.stringify({...values, local_only: true, enabled: true})}))
            setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 500, margin: '12px 0'}}>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Rendition <select {...register('format')}><option value="audio">Podcast audio</option>
            <option value="video">Video feed</option></select></label>
        {error && <p role="alert">{error}</p>}
        <div><button type="submit" className="btn btn-primary" disabled={isSubmitting}>Save Stream Profile</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const TargetSchema = z.object({
    kind: z.enum(['jellyfin', 'plex', 'audiobookshelf']).default('jellyfin'),
    name: z.string().min(1), base_url: z.url(), library_id: z.string().min(1),
    local_prefix: z.string().startsWith('/'), server_prefix: z.string().startsWith('/'), api_key: z.string().min(1),
})
type TargetFields = z.input<typeof TargetSchema>

function TargetForm({onCreated}: {onCreated: (target: Target) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const {register, handleSubmit, formState: {errors, isSubmitting}, reset} = useForm<TargetFields, unknown, z.output<typeof TargetSchema>>({
        resolver: zodResolver(TargetSchema), defaultValues: {kind: 'jellyfin', name: '', base_url: '',
            library_id: '', local_prefix: '/downloads', server_prefix: '/media', api_key: ''},
    })
    if (!expanded) return <button type="button" className="btn" onClick={() => setExpanded(true)}>Connect media server</button>
    return <form onSubmit={handleSubmit(async values => {
        setError(null)
        try {
            onCreated(await api<Target>('/integrations', {method: 'POST',
                body: JSON.stringify({...values, enabled: true})}))
            reset(); setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 600}}>
        <label>Server <select {...register('kind')}><option value="jellyfin">Jellyfin</option>
            <option value="plex">Plex</option><option value="audiobookshelf">Audiobookshelf podcast library</option></select></label>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Server URL <input {...register('base_url')} placeholder="http://media-server:8096" />
            {errors.base_url && <span role="alert">{errors.base_url.message}</span>}</label>
        <label>Library ID <input {...register('library_id')} /></label>
        <label>VodLoft folder <input {...register('local_prefix')} /></label>
        <label>Server's view of that folder <input {...register('server_prefix')} /></label>
        <label>API token <input type="password" autoComplete="off" {...register('api_key')} /></label>
        {error && <p role="alert">{error}</p>}
        <div><button className="btn btn-primary" disabled={isSubmitting}>Save connection</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const ConnectionSchema = z.object({source_id: z.string().min(1), name: z.string().min(1), access_token: z.string().optional()})
type ConnectionFields = z.infer<typeof ConnectionSchema>

function ConnectionForm({sources, onCreated}: {sources: Source[]; onCreated: (connection: Connection) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const {register, handleSubmit, watch, formState: {errors, isSubmitting}, reset} = useForm<ConnectionFields>({
        resolver: zodResolver(ConnectionSchema),
        defaultValues: {source_id: sources[0]?.source_id || '', name: '', access_token: ''},
    })
    const selected = sources.find(source => source.source_id === watch('source_id'))
    if (!expanded) return <button type="button" className="btn" onClick={() => setExpanded(true)}>Add Source connection</button>
    return <form onSubmit={handleSubmit(async values => {
        setError(null)
        try {
            onCreated(await api<Connection>('/sources/connections', {method: 'POST',
                body: JSON.stringify({...values, access_token: values.access_token || null, enabled: true})}))
            reset(); setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 500}}>
        <label>Source <select {...register('source_id')}><option value="">Select Source</option>
            {sources.map(source => <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}</select>
            {errors.source_id && <span role="alert">{errors.source_id.message}</span>}</label>
        <label>Connection name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        {selected?.configuration_schema.filter(field => field.name === 'access_token').map(field =>
            <label key={field.name}>{field.label} <input type="password" autoComplete="off" {...register('access_token')} /></label>)}
        {error && <p role="alert">{error}</p>}
        <div><button className="btn btn-primary" disabled={isSubmitting}>Save connection</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const MetadataSchema = z.object({title: z.string().max(500), description: z.string().max(10000)})
type MetadataFields = z.infer<typeof MetadataSchema>

function MetadataForm({item, onSaved}: {item: Item; onSaved: (updated: Item) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const {register, handleSubmit, formState: {errors, isSubmitting}} = useForm<MetadataFields>({
        resolver: zodResolver(MetadataSchema),
        defaultValues: {title: item.title, description: item.description ?? ''},
    })
    if (!expanded) return <button type="button" className="btn" onClick={() => setExpanded(true)}>Edit library metadata</button>
    return <form onSubmit={handleSubmit(async values => {
        setError(null)
        try {
            onSaved(await api<Item>(`/library/${item.id}/metadata`, {method: 'PUT',
                body: JSON.stringify(values)}))
            setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 640, marginBottom: 16}}>
        <label>Display title <input {...register('title')} />{errors.title && <span role="alert">{errors.title.message}</span>}</label>
        <label>Description <textarea {...register('description')} rows={4} />
            {errors.description && <span role="alert">{errors.description.message}</span>}</label>
        {error && <p role="alert">{error}</p>}
        <div><button className="btn btn-primary" disabled={isSubmitting}>Save metadata</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}
