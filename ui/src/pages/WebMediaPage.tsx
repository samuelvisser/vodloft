import {useEffect, useRef, useState} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {z} from 'zod'

const URLForm = z.object({url: z.url().startsWith('https://').or(z.url().startsWith('http://')),
    source_id: z.string(), connection_id: z.string()})
type URLFields = z.infer<typeof URLForm>
type Source = {source_id: string; display_name: string; capabilities: string[];
    configuration_schema: {name: string; label: string; kind: 'text' | 'number' | 'select' | 'secret' | 'credential_file';
        required: boolean; options: string[]}[]}
type Connection = {id: number; source_id: string; name: string; has_secret: boolean; enabled: boolean;
    settings: Record<string, string | number>; secret_fields: string[]}
type Reference = {source_id: string; domain: string; namespace: string; upstream_id: string; url: string}
type Preview = {kind: string; title: string; description?: string; artwork_url?: string; reference: Reference; entries: {title: string; position: number}[]; enumeration_complete: boolean}
type Item = {id: number; title: string; description?: string; kind: string; domain: string; downloaded: boolean;
    capabilities?: string[] | null; playback_type?: string; artwork_url?: string; entries?: Item[]; extras?: Item[];
    references?: {id: number; source_id: string; connection_id: number | null; namespace: string; upstream_id: string}[]}
type Home = {continue: (Item & {seconds: number})[]; recent: Item[];
    activity: {id: number; item_id: number; state: string}[]; issues: {kind: string; id: number}[]}
type Job = {id: number; state: string; error?: string; cancel_requested?: boolean;
    error_code?: string; failed_stage?: string; operation_id?: string; progress?: number;
    title?: string; attempts?: number; item_id?: number}
type Export = {id: number; target_id: number; state: string; remote_id?: string; error?: string; attempts: number}
type SourceHistory = {id: number; source_id: string; connection_id: number | null;
    runtime_version: string; created_at: string; metadata: {title?: string; description?: string}}
type Profile = {id: number; name: string; domain: string; preferred_format: string; output_template: string; applicable_kinds: string[]; enabled: boolean}
type DownloadPolicy = {id: number; name: string; local_profile_ids: number[]; backfill: string; newest_count: number;
    source_reference_id: number | null; enabled: boolean}
type StreamProfile = {id: number; name: string; format: string; enabled: boolean;
    published_after?: string | null; published_before?: string | null; title_contains?: string | null}
type Target = {id: number; name: string; kind: string; base_url: string; library_id: string; enabled: boolean}
type RuntimeState = {active: Record<string, string>; installed: Record<string, string[]>;
    policy: Record<string, {automatic: boolean; pinned_version: string | null; channel: string}>}
type Catalogue = {source_id: string; items: {hostname: string; display_name: string}[]; exhaustive: boolean}
type SearchPage = {items: {reference: Reference; kind: string; title: string; description?: string}[];
    next_cursor: string | null}
const SearchForm = z.object({query: z.string().min(1).max(200), source_id: z.string().min(1),
    connection_id: z.string()})
type SearchFields = z.infer<typeof SearchForm>
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
    const [view, setView] = useState<'home' | 'discover' | 'library' | 'management'>('home')
    const [libraryQuery, setLibraryQuery] = useState('')
    const {register, handleSubmit, formState: {errors}} = useForm<URLFields>({
        resolver: zodResolver(URLForm), defaultValues: {url: '', source_id: '', connection_id: ''},
    })
    const {register: registerSearch, handleSubmit: handleSearch, watch: watchSearch,
        formState: {errors: searchErrors}} = useForm<SearchFields>({
        resolver: zodResolver(SearchForm), defaultValues: {query: '', source_id: '', connection_id: ''},
    })
    const selectedSearchSource = watchSearch('source_id')
    const [sources, setSources] = useState<Source[]>([])
    const [connections, setConnections] = useState<Connection[]>([])
    const [importConnectionId, setImportConnectionId] = useState<number | null>(null)
    const [items, setItems] = useState<Item[]>([])
    const [home, setHome] = useState<Home | null>(null)
    const [preview, setPreview] = useState<Preview | null>(null)
    const [searchPage, setSearchPage] = useState<SearchPage | null>(null)
    const [searchRequest, setSearchRequest] = useState<SearchFields | null>(null)
    const [selected, setSelected] = useState<Item | null>(null)
    const [job, setJob] = useState<Job | null>(null)
    const [jobs, setJobs] = useState<Job[]>([])
    const [exports, setExports] = useState<Export[]>([])
    const [sourceHistory, setSourceHistory] = useState<SourceHistory[] | null>(null)
    const [profiles, setProfiles] = useState<Profile[]>([])
    const [downloadPolicies, setDownloadPolicies] = useState<DownloadPolicy[]>([])
    const [streamProfiles, setStreamProfiles] = useState<StreamProfile[]>([])
    const [targets, setTargets] = useState<Target[]>([])
    const [runtimes, setRuntimes] = useState<RuntimeState | null>(null)
    const [catalogues, setCatalogues] = useState<Catalogue[]>([])
    const [prepareDomain, setPrepareDomain] = useState('')
    const [runResult, setRunResult] = useState<string | null>(null)
    const [profileId, setProfileId] = useState<number | null>(null)
    const [referenceId, setReferenceId] = useState<number | null>(null)
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
    useEffect(() => {
        if (view !== 'management') return
        const update = () => void Promise.all([api<Job[]>('/jobs').then(setJobs),
            api<Export[]>('/integrations/exports').then(setExports)]).catch(e => setError(String(e)))
        update()
        const timer = window.setInterval(update, 10000)
        return () => window.clearInterval(timer)
    }, [view])

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
            await open(item.id)
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    const fetchSearch = async (fields: SearchFields, cursor?: string) => {
        setBusy(true); setError(null)
        try {
            const params = new URLSearchParams({query: fields.query, limit: '30'})
            if (cursor) params.set('cursor', cursor)
            if (fields.connection_id) params.set('connection_id', fields.connection_id)
            const result = await api<SearchPage>(`/sources/${encodeURIComponent(fields.source_id)}/search?${params}`)
            setSearchPage(previous => cursor && previous ? {
                items: [...previous.items, ...result.items], next_cursor: result.next_cursor} : result)
            setSearchRequest(fields)
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    const previewSearchResult = async (reference: Reference) => {
        setBusy(true); setError(null)
        try {
            setPreview(await api<Preview>('/resolve', {method: 'POST', body: JSON.stringify({
                url: reference.url, source_id: reference.source_id,
                connection_id: searchRequest?.connection_id ? Number(searchRequest.connection_id) : null})}))
            setImportConnectionId(searchRequest?.connection_id ? Number(searchRequest.connection_id) : null)
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    const open = async (id: number) => {
        setError(null); setJob(null); setFeedUrl(null); setOutputPreview(null); setSourceHistory(null)
        setView('library')
        try {
            const item = await api<Item>(`/library/${id}`)
            setSelected(item)
            setReferenceId(item.references?.length === 1 ? item.references[0].id : null)
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
        try { setJob(await api<Job>(`/library/${id}/download`, {method: 'POST',
            body: JSON.stringify({profile_id: profileId, reference_id: referenceId})})) }
        catch (e) { setError(String(e)) }
    }
    const refreshCollection = async (id: number, expandDepth = 0) => {
        setBusy(true); setError(null)
        try {
            const params = new URLSearchParams()
            if (referenceId) params.set('reference_id', String(referenceId))
            if (expandDepth) params.set('expand_depth', String(expandDepth))
            const result = await api<Item & {nested_expansion?: {refreshed_ids: number[]; skipped: {item_id: number; reason: string}[]}}>(
                `/library/${id}/refresh?${params}`, {method: 'POST'})
            if (result.nested_expansion) setRunResult(`${result.nested_expansion.refreshed_ids.length} nested collections refreshed; ${result.nested_expansion.skipped.length} skipped.`)
            setSelected(await api<Item>(`/library/${id}`))
            await refresh()
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    const refreshDetails = async (id: number) => {
        setBusy(true); setError(null)
        try {
            const params = referenceId ? `?reference_id=${referenceId}` : ''
            await api<Item>(`/library/${id}/refresh-details${params}`, {method: 'POST'})
            setSelected(await api<Item>(`/library/${id}`))
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
            <p className="view-description">Discover, collect, download and play media from the web.</p></div></div>
        <nav aria-label="Web media" style={{display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24}}>
            {(['home', 'discover', 'library', 'management'] as const).map(next =>
                <button key={next} type="button" className={`btn ${view === next ? 'btn-primary' : ''}`}
                    aria-current={view === next ? 'page' : undefined} onClick={() => setView(next)}>
                    {next[0].toUpperCase() + next.slice(1)}</button>)}
        </nav>
        {error && <div className="form-error-card" role="alert">{error}</div>}
        {view === 'discover' && <>
        <h2>Add media</h2>
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
        {sources.some(source => source.capabilities.includes('search')) && <section style={{marginBottom: 24}}>
            <h2>Search a Source</h2>
            <form onSubmit={handleSearch(fields => void fetchSearch(fields))}
                style={{display: 'flex', gap: 12, alignItems: 'end', flexWrap: 'wrap'}}>
                <label>Search phrase <input {...registerSearch('query')} />
                    {searchErrors.query && <span role="alert">Enter a search phrase.</span>}</label>
                <label>Source <select {...registerSearch('source_id')}><option value="">Choose Source</option>
                    {sources.filter(source => source.capabilities.includes('search')).map(source =>
                        <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}</select>
                    {searchErrors.source_id && <span role="alert">Choose a searchable Source.</span>}</label>
                <label>Connection <select {...registerSearch('connection_id')}><option value="">Anonymous</option>
                    {connections.filter(connection => connection.enabled && connection.source_id === selectedSearchSource).map(connection =>
                        <option key={connection.id} value={connection.id}>{connection.name}</option>)}</select></label>
                <button className="btn" type="submit" disabled={busy}>Search</button>
            </form>
            {searchPage && <div style={{display: 'grid', gap: 8, marginTop: 12}}>
                {searchPage.items.map(item => <button type="button" className="btn"
                    key={`${item.reference.source_id}:${item.reference.upstream_id}`}
                    onClick={() => void previewSearchResult(item.reference)} style={{textAlign: 'left'}}>
                    {item.title} · {item.kind} · {item.reference.domain}</button>)}
                {searchPage.items.length === 0 && <p>No results from this Source.</p>}
                {searchPage.next_cursor && searchRequest && <button className="btn" type="button" disabled={busy}
                    onClick={() => void fetchSearch(searchRequest, searchPage.next_cursor || undefined)}>More results</button>}
            </div>}
        </section>}
        {preview && <section style={{marginBottom: 32}}><h2>{preview.title}</h2>
            <p>{preview.kind} · {preview.reference.domain} · {preview.reference.source_id}</p>
            {preview.description && <p>{preview.description.slice(0, 350)}</p>}
            {preview.kind === 'collection' && <p>{preview.entries.length} preview entries
                {!preview.enumeration_complete && ' (more entries are available)'}</p>}
            <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void importPreview()}>Add to library</button>
        </section>}
        </>}
        {view === 'home' && home && <section style={{marginBottom: 24}} aria-label="Home">
            <h2>Continue</h2>
            {home.continue.filter(item => item.downloaded).length === 0 && <p>Your local playback will appear here.</p>}
            <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>{home.continue.filter(item => item.downloaded).map(item =>
                <button className="btn" type="button" key={item.id} onClick={() => void open(item.id)}>
                    {item.title} · {Math.floor(item.seconds / 60)} min</button>)}</div>
            <h2>Recent arrivals</h2>
            <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>{home.recent.map(item =>
                <button className="btn" type="button" key={item.id} onClick={() => void open(item.id)}>
                    {item.title}{item.downloaded ? ' · Local' : ''}</button>)}</div>
            <h2>Activity</h2>
            <p>{home.activity.length} active downloads · {home.issues.length} issues</p>
            {home.issues.length > 0 && <button className="btn" type="button"
                onClick={() => setView('management')}>Review issues</button>}
        </section>}
        {view === 'management' && <section style={{marginBottom: 24}}><h2>Sources, Domains and media servers</h2>
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
            <label>Prepare a Domain profile <input list="vodloft-domain-suggestions"
                value={prepareDomain} onChange={event => setPrepareDomain(event.target.value)}
                placeholder="example.com" /></label>
            <datalist id="vodloft-domain-suggestions">{catalogues.flatMap(c => c.items.map(domain =>
                <option key={`${c.source_id}:${domain.hostname}`} value={domain.hostname}>{domain.display_name}</option>))}</datalist>
            {prepareDomain.trim() && <DomainProfileForm key={prepareDomain.trim()} domain={prepareDomain.trim()}
                targets={targets} onCreated={profile => setProfiles(current => [...current, profile])} />}
            <h3>Source connections</h3>
            {connections.map(connection => <p key={connection.id}>{connection.name} · {connection.source_id}
                {connection.has_secret ? ' · credential stored' : ' · anonymous'}
                {!connection.enabled && ' · disabled'}{' '}
                <button className="btn" type="button" onClick={() => void api<Connection>(
                    `/sources/connections/${connection.id}`, {method: 'PUT', body: JSON.stringify({
                        source_id: connection.source_id, name: connection.name,
                        settings: connection.settings, enabled: !connection.enabled})})
                    .then(updated => setConnections(current => current.map(item =>
                        item.id === updated.id ? updated : item))).catch(e => setError(String(e)))}>
                    {connection.enabled ? 'Disable' : 'Enable'}</button>
            </p>)}
            <ConnectionForm sources={sources} onCreated={connection => setConnections(current => [...current, connection])}/>
            <h3>Media servers</h3>
            {targets.map(target => <p key={target.id}>{target.name} · {target.kind} · library {target.library_id}{' '}
                <button type="button" className="btn" onClick={() => void api<unknown>(`/integrations/${target.id}/test`, {method: 'POST'})
                    .then(result => setRunResult(JSON.stringify(result))).catch(e => setError(String(e)))}>Test connection</button></p>)}
            <TargetForm onCreated={target => setTargets(current => [...current, target])}/>
            <h3>Recent downloads</h3>
            {jobs.length === 0 && <p>No download jobs yet.</p>}
            {jobs.map(record => <p key={record.id}>
                <button type="button" className="btn" onClick={() => void open(record.item_id!)}>{record.title}</button>
                {' '}· {record.state} · {record.progress ?? 0}% · attempt {record.attempts}
                {record.error_code && ` · ${record.error_code.replace(/_/g, ' ')}`}
                {record.failed_stage && ` during ${record.failed_stage}`}
                {['failed', 'canceled'].includes(record.state) && <button className="btn" type="button"
                    onClick={() => void api<Job>(`/jobs/${record.id}/retry`, {method: 'POST'})
                        .then(() => api<Job[]>('/jobs').then(setJobs)).catch(e => setError(String(e)))}>Retry</button>}
                {['queued', 'resolving', 'downloading', 'processing', 'verifying'].includes(record.state) &&
                    <button className="btn" type="button" onClick={() => void api<Job>(`/jobs/${record.id}/cancel`, {method: 'POST'})
                        .then(() => api<Job[]>('/jobs').then(setJobs)).catch(e => setError(String(e)))}>Cancel</button>}
            </p>)}
            <h3>Media-server delivery</h3>
            {exports.length === 0 && <p>No exports yet.</p>}
            {exports.map(record => <p key={record.id}>Export {record.id} · {targets.find(t => t.id === record.target_id)?.name}
                {' '}· {record.state}{record.remote_id && ` · remote item ${record.remote_id}`}
                {record.error && ` · ${record.error}`}
                {record.state !== 'available' && <button className="btn" type="button"
                    onClick={() => void api<unknown>(`/integrations/exports/${record.id}/retry`, {method: 'POST'})
                        .then(() => api<Export[]>('/integrations/exports').then(setExports)).catch(e => setError(String(e)))}>Retry</button>}
            </p>)}
            {runResult && <p role="status">{runResult}</p>}
        </section>}
        {view === 'library' && <>
        <h2>Library</h2>
        <label>Search your library <input type="search" value={libraryQuery}
            onChange={event => setLibraryQuery(event.target.value)} /></label>
        {items.length === 0 && <p>No web media has been added yet.</p>}
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 12}}>
            {items.filter(item => `${item.title} ${item.domain} ${item.kind}`.toLocaleLowerCase()
                .includes(libraryQuery.toLocaleLowerCase())).map(item =>
                <button type="button" key={item.id} onClick={() => void open(item.id)}
                        className="btn" style={{textAlign: 'left', minWidth: 200}}>
                    <strong>{item.title}</strong><br/>{item.kind} · {item.domain}{item.downloaded ? ' · Local' : ''}
                </button>)}
        </div>
        {selected && <section style={{marginTop: 32}}><h2>{selected.title}</h2>
            <p>{selected.kind} · {selected.domain}</p>
            {(selected.references?.length ?? 0) > 1 && <label>Source account{' '}
                <select value={referenceId ?? ''} onChange={event => setReferenceId(Number(event.target.value) || null)}>
                    <option value="">Choose a Source account</option>
                    {selected.references?.map(reference => <option key={reference.id} value={reference.id}>
                        {reference.source_id} · {connections.find(c => c.id === reference.connection_id)?.name ?? 'Anonymous'}
                    </option>)}
                </select>
            </label>}
            <MetadataForm key={selected.id} item={selected} onSaved={updated => {
                setSelected(previous => previous?.id === updated.id ? {...previous, ...updated} : previous)
                void refresh()
            }}/>
            <div style={{margin: '12px 0'}}>
                <button className="btn" type="button" onClick={() => void api<SourceHistory[]>(
                    `/library/${selected.id}/source-history`).then(setSourceHistory).catch(e => setError(String(e)))}>
                    Source history</button>
                {sourceHistory && <div>{sourceHistory.length === 0 && <p>No Source snapshots yet.</p>}
                    {sourceHistory.map(snapshot => <p key={snapshot.id}>
                        {new Date(snapshot.created_at).toLocaleString()} · {snapshot.source_id} {snapshot.runtime_version}
                        {' '}· {connections.find(c => c.id === snapshot.connection_id)?.name ?? 'Anonymous'}
                        {' '}· {snapshot.metadata.title ?? 'Untitled'}{' '}
                        <button className="btn" type="button" onClick={() => {
                            if (!window.confirm('Restore this upstream metadata? Your library edits remain in place.')) return
                            void api<Item>(`/library/${selected.id}/source-history/${snapshot.id}/restore`, {method: 'POST'})
                                .then(() => api<Item>(`/library/${selected.id}`).then(setSelected))
                                .then(() => refresh()).catch(e => setError(String(e)))
                        }}>Restore</button>
                    </p>)}
                </div>}
            </div>
            {selected.kind === 'collection' && <div style={{display: 'flex', gap: 10, marginBottom: 16}}>
                <button className="btn" type="button" disabled={busy || !referenceId}
                    onClick={() => void refreshCollection(selected.id)}>Refresh collection</button>
                <button className="btn" type="button" disabled={busy || !referenceId}
                    onClick={() => void refreshCollection(selected.id, 2)}>Expand nested collections (2 levels, 20 max)</button>
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
                    sourceReferenceId={referenceId} references={selected.references ?? []}
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
                <button className="btn" type="button" disabled={busy || !referenceId}
                    onClick={() => void refreshDetails(selected.id)}>Refresh details</button>
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
                <button className="btn btn-primary" type="button" disabled={!profileId || !referenceId ||
                    selected.capabilities !== null && selected.capabilities !== undefined && !selected.capabilities.includes('download') ||
                    !!job && !['failed', 'available'].includes(job.state)}
                        onClick={() => void download(selected.id)}>{selected.downloaded ? 'Download again' : 'Download'}</button>
                {selected.capabilities && !selected.capabilities.includes('download') &&
                    <p>This Source does not advertise a download for this item.</p>}
                {job && <p role="status">Download: {job.state}{job.progress !== undefined ? ` · ${job.progress}%` : ''}
                    {job.error_code ? ` · ${job.error_code.replace(/_/g, ' ')}` : ''}
                    {job.failed_stage ? ` during ${job.failed_stage}` : ''}
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
        </>}
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

function DownloadPolicyForm({collectionId, profiles, sourceReferenceId, references, onCreated}: {
    collectionId: number; profiles: Profile[]; sourceReferenceId: number | null;
    references: NonNullable<Item['references']>; onCreated: (profile: DownloadPolicy) => void}) {
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
        if (!sourceReferenceId && references.length > 1) { setError('Select a Source account above.'); return }
        setError(null)
        try {
            const created = await api<DownloadPolicy>(`/library/${collectionId}/download-profiles`, {
                method: 'POST', body: JSON.stringify({...values,
                    published_after: values.published_after || null,
                    published_before: values.published_before || null,
                    title_contains: values.title_contains || null,
                    local_profile_ids: selectedIds, source_reference_id: sourceReferenceId,
                    enabled: true})})
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

const StreamProfileSchema = z.object({name: z.string().min(1), format: z.enum(['audio', 'video']).default('audio'),
    published_after: z.string().default(''), published_before: z.string().default(''),
    title_contains: z.string().max(200).default('')}).refine(
        values => !values.published_after || !values.published_before || values.published_after <= values.published_before,
        {path: ['published_before'], message: 'End date must follow start date'})
type StreamFields = z.input<typeof StreamProfileSchema>

function StreamProfileForm({collectionId, onCreated}: {collectionId: number; onCreated: (profile: StreamProfile) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const {register, handleSubmit, formState: {errors, isSubmitting}} = useForm<StreamFields, unknown, z.output<typeof StreamProfileSchema>>({
        resolver: zodResolver(StreamProfileSchema), defaultValues: {name: 'Podcast feed', format: 'audio',
            published_after: '', published_before: '', title_contains: ''},
    })
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>Create Stream Profile</button>
    return <form onSubmit={handleSubmit(async values => {
        setError(null)
        try {
            onCreated(await api<StreamProfile>(`/library/${collectionId}/stream-profiles`, {method: 'POST',
                body: JSON.stringify({...values, published_after: values.published_after || null,
                    published_before: values.published_before || null,
                    title_contains: values.title_contains || null, local_only: true, enabled: true})}))
            setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 500, margin: '12px 0'}}>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Rendition <select {...register('format')}><option value="audio">Podcast audio</option>
            <option value="video">Video feed</option></select></label>
        <label>Published on or after <input type="date" {...register('published_after')} /></label>
        <label>Published on or before <input type="date" {...register('published_before')} />
            {errors.published_before && <span role="alert">{errors.published_before.message}</span>}</label>
        <label>Title contains <input {...register('title_contains')} /></label>
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

const ConnectionSchema = z.object({source_id: z.string().min(1), name: z.string().min(1),
    configuration: z.record(z.string(), z.string()).default({})})
type ConnectionFields = z.input<typeof ConnectionSchema>

function ConnectionForm({sources, onCreated}: {sources: Source[]; onCreated: (connection: Connection) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [fileSecrets, setFileSecrets] = useState<Record<string, string>>({})
    const [readingFile, setReadingFile] = useState(false)
    const {register, handleSubmit, watch, formState: {errors, isSubmitting}, reset} = useForm<ConnectionFields, unknown, z.output<typeof ConnectionSchema>>({
        resolver: zodResolver(ConnectionSchema),
        shouldUnregister: true,
        defaultValues: {source_id: '', name: '', configuration: {}},
    })
    const selected = sources.find(source => source.source_id === watch('source_id'))
    useEffect(() => setFileSecrets({}), [selected?.source_id])
    if (!expanded) return <button type="button" className="btn" onClick={() => setExpanded(true)}>Add Source connection</button>
    return <form onSubmit={handleSubmit(async values => {
        setError(null)
        try {
            const schema = sources.find(source => source.source_id === values.source_id)?.configuration_schema ?? []
            const settings: Record<string, string | number> = {}
            const secrets: Record<string, string> = {}
            for (const field of schema) {
                const value = field.kind === 'credential_file' ? fileSecrets[field.name] ?? '' :
                    values.configuration[field.name]?.trim() ?? ''
                if (field.required && !value) {setError(`${field.label} is required.`); return}
                if (!value) continue
                if (field.kind === 'secret' || field.kind === 'credential_file') secrets[field.name] = value
                else if (field.kind === 'number') {
                    const number = Number(value)
                    if (!Number.isFinite(number)) {setError(`${field.label} must be a number.`); return}
                    settings[field.name] = number
                } else settings[field.name] = value
            }
            onCreated(await api<Connection>('/sources/connections', {method: 'POST',
                body: JSON.stringify({source_id: values.source_id, name: values.name,
                    settings, secrets, enabled: true})}))
            reset(); setFileSecrets({}); setExpanded(false)
        } catch (e) { setError(String(e)) }
    })} style={{display: 'grid', gap: 10, maxWidth: 500}}>
        <label>Source <select {...register('source_id')}><option value="">Select Source</option>
            {sources.map(source => <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}</select>
            {errors.source_id && <span role="alert">{errors.source_id.message}</span>}</label>
        <label>Connection name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        {selected?.configuration_schema.map(field => <label key={field.name}>{field.label}
            {field.kind === 'credential_file' ? <input type="file" accept=".txt,text/plain" required={field.required}
                onChange={event => { const file = event.target.files?.[0];
                    if (!file) {setFileSecrets(current => ({...current, [field.name]: ''})); return}
                    if (file.size > 1024 * 1024) {
                        setFileSecrets(current => ({...current, [field.name]: ''}))
                        setError('Credential files must be at most 1 MiB.'); return
                    }
                    setReadingFile(true)
                    void file.text().then(content => setFileSecrets(current => ({...current, [field.name]: content})))
                        .catch(() => setError('Could not read the credential file.'))
                        .finally(() => setReadingFile(false))
                }} /> : field.kind === 'select' ? <select {...register(`configuration.${field.name}`)}>
                <option value="">Choose an option</option>
                {field.options.map(option => <option key={option} value={option}>{option}</option>)}
            </select> : <input type={field.kind === 'secret' ? 'password' : field.kind === 'number' ? 'number' : 'text'}
                autoComplete={field.kind === 'secret' ? 'off' : undefined}
                required={field.required} {...register(`configuration.${field.name}`)} />}
        </label>)}
        {error && <p role="alert">{error}</p>}
        <div><button className="btn btn-primary" disabled={isSubmitting || readingFile}>Save connection</button>{' '}
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
