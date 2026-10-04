import type Hls from 'hls.js'
import {useEffect, useRef, useState} from 'react'
import {useForm, type UseFormReturn} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {z} from 'zod'
import {buildServerAwareSubmit} from '../utils/buildServerAwareSubmit'
import {hashPasswordForAdminAuth} from '../utils/security/adminAuth'
import DomainTemplateEditor from '../components/LocalMediaProfile/DomainTemplateEditor'

const URLForm = z.object({url: z.url().startsWith('https://').or(z.url().startsWith('http://')),
    source_id: z.string().default(''), connection_id: z.string().default('')})
type URLFields = z.infer<typeof URLForm>
type Source = {source_id: string; display_name: string; capabilities: string[];
    configuration_schema: {name: string; label: string; kind: 'text' | 'number' | 'select' | 'secret' | 'credential_file';
        required: boolean; options: string[]}[]}
type Me = {key: string; username: string; role: string; manages_library: boolean; can_subscribe: boolean; auto_approve: boolean; request_quota: number}
type MediaRequest = {id: number; item_id: number; user_key: string; profile_id: number; state: string; job_id: number | null; reason: string | null}
type Connection = {id: number; source_id: string; name: string; has_secret: boolean; enabled: boolean;
    authentication_status?: string | null;
    settings: Record<string, string | number>; secret_fields: string[]}
type Reference = {source_id: string; domain: string; namespace: string; upstream_id: string; url: string}
type Preview = {kind: string; title: string; description?: string; artwork_url?: string; reference: Reference; entries: {title: string; position: number}[]; enumeration_complete: boolean}
type Item = {parent_id?: number | null; parent_ids?: number[]; extra_type?: string | null; chapters?: {title: string; start: number; end?: number}[]; id: number; title: string; description?: string; kind: string; domain: string; downloaded: boolean;
    member_groups?: string[]; member_roles?: string[];
    capabilities?: string[] | null; playback_type?: string; artwork_url?: string; artwork_available?: boolean; entries?: Item[]; extras?: Item[];
    is_live?: boolean | null; formats?: {code: string; description?: string; audio_only: boolean; height?: number}[];
    references?: {id: number; source_id: string; connection_id: number | null; namespace: string; upstream_id: string}[]}
type Home = {continue: (Item & {seconds: number})[]; recent: Item[];
    activity: {id: number; item_id: number; state: string}[]; issues: {kind: string; id: number}[]}
type Job = {id: number; state: string; error?: string; cancel_requested?: boolean;
    error_code?: string; failed_stage?: string; operation_id?: string; progress?: number;
    title?: string; attempts?: number; item_id?: number}
type Export = {id: number; target_id: number; state: string; remote_id?: string; error?: string; attempts: number}
type RemoteItem = {id: number; kind: string; name: string; state: string; url: string | null;
    remote_episode_id: string | null; progress_path: string}
type SourceHistory = {id: number; source_id: string; connection_id: number | null;
    runtime_version: string; created_at: string; metadata: {title?: string; description?: string}}
type Representation = {languages: string[]; subtitles: string[]; container: ProfileFields['container']; video_codec: ProfileFields['video_codec']; audio_codec: ProfileFields['audio_codec']; chapters: boolean; artwork: boolean; embed_metadata: boolean; language_fallback: boolean}
type Profile = {representation: Representation; delivery_target_ids: number[]; impairment: string | null; id: number; name: string; domain: string; preferred_format: string; output_template: string; applicable_kinds: string[]; enabled: boolean}
type MembershipPolicy = {selected_groups: string[] | null; include_future_groups: boolean; member_roles: string[] | null}
type DownloadPolicy = MembershipPolicy & {id: number; name: string; local_profile_ids: number[]; backfill: string; newest_count: number;
    retain_newest: number | null; retain_days: number | null;
    source_reference_id: number | null; enabled: boolean; refresh_minutes: number; published_after: string | null; published_before: string | null; title_contains: string | null}
type StreamProfile = MembershipPolicy & {id: number; name: string; format: string; enabled: boolean; max_items: number; feed_title: string | null;
    source_reference_id: number | null; local_profile_ids: number[]; refresh_minutes: number; allow_other_renditions: boolean;
    include_live: boolean; local_only: boolean;
    published_after?: string | null; published_before?: string | null; title_contains?: string | null}
type Target = {local_prefix: string; server_prefix: string; id: number; name: string; kind: string; base_url: string; library_id: string; enabled: boolean}
type RuntimeState = {history: {source_id: string; action: string; at: string; state?: string; message?: string; version?: string}[]; active: Record<string, string>; installed: Record<string, string[]>;
    policy: Record<string, {automatic: boolean; pinned_version: string | null; channel: string}>}
type Catalogue = {source_id: string; items: {hostname: string; display_name: string}[]; exhaustive: boolean}
type SearchPage = {items: {reference: Reference; kind: string; title: string; description?: string}[];
    next_cursor: string | null}
const SearchForm = z.object({query: z.string().min(1).max(200), source_id: z.string().min(1),
    connection_id: z.string().default('')})
type SearchFields = z.infer<typeof SearchForm>
const ProfileFormSchema = z.object({
    name: z.string().min(1).default(''),
    preferred_format: z.enum(['format_720p', 'format_1080p', 'format_4k', 'format_audio_only']),
    output_template: z.string().min(16),
    languages: z.string().default('').refine(value => value.split(',').map(code => code.trim()).filter(Boolean)
        .every(code => /^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$/.test(code)), 'Use language codes such as en, nl or en-US'),
    subtitles: z.string().default('').refine(value => value.split(',').map(code => code.trim()).filter(Boolean)
        .every(code => /^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$/.test(code)), 'Use language codes such as en or nl'),
    container: z.enum(['source', 'mp4', 'mkv', 'mp3', 'm4a', 'opus']).default('source'),
    video_codec: z.enum(['source', 'h264', 'h265', 'vp9', 'av1']).default('source'),
    audio_codec: z.enum(['source', 'aac', 'mp3', 'opus']).default('source'),
    chapters: z.boolean().default(true), artwork: z.boolean().default(false),
    embed_metadata: z.boolean().default(true), language_fallback: z.boolean().default(true),
    applicable_kinds: z.array(z.enum(['video', 'movie', 'movie_extra'])).min(1).default(['video', 'movie', 'movie_extra']), enabled: z.boolean().default(true),
})
type ProfileFields = z.input<typeof ProfileFormSchema>

const base = () => `${(window as any).appConfig?.API_URL || '/api'}/vodloft`
function formRequest(path: string, method: string, values: unknown) {
    return fetch(`${base()}${path}`, {method, credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)})
}
async function api<T>(path: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${base()}${path}`, {credentials: 'include', ...options,
        headers: {'Content-Type': 'application/json', ...options?.headers}})
    if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `HTTP ${response.status}`)
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

export default function WebMediaPage({initialView = 'home'}: {initialView?: 'home' | 'discover' | 'library' | 'management'}) {
    const [view, setView] = useState<'home' | 'discover' | 'library' | 'management'>(initialView)
    const [me, setMe] = useState<Me | null>(null)
    const [libraryQuery, setLibraryQuery] = useState('')
    const urlForm = useForm<z.input<typeof URLForm>, unknown, URLFields>({
        resolver: zodResolver(URLForm), defaultValues: URLForm.partial({url: true}).parse({}),
    })
    const {register, formState: {errors}} = urlForm
    const searchForm = useForm<z.input<typeof SearchForm>, unknown, SearchFields>({
        resolver: zodResolver(SearchForm), defaultValues: SearchForm.partial({query: true, source_id: true}).parse({}),
    })
    const {register: registerSearch, watch: watchSearch, formState: {errors: searchErrors}} = searchForm
    const selectedSearchSource = watchSearch('source_id')
    const [sources, setSources] = useState<Source[]>([])
    const [connections, setConnections] = useState<Connection[]>([])
    const [importConnectionId, setImportConnectionId] = useState<number | null>(null)
    const [items, setItems] = useState<Item[]>([])
    const [home, setHome] = useState<Home | null>(null)
    const [preview, setPreview] = useState<Preview | null>(null)
    const [searchPage, setSearchPage] = useState<SearchPage | null>(null)
    const [searchRequest, setSearchRequest] = useState<SearchFields | null>(null)
    const [queue, setQueue] = useState<{id: number; title: string}[]>([])
    const [selected, setSelected] = useState<Item | null>(null)
    const [job, setJob] = useState<Job | null>(null)
    const [jobs, setJobs] = useState<Job[]>([])
    const [exports, setExports] = useState<Export[]>([])
    const [remoteItems, setRemoteItems] = useState<RemoteItem[]>([])
    const [sourceHistory, setSourceHistory] = useState<SourceHistory[] | null>(null)
    const [managedProfiles, setManagedProfiles] = useState<Profile[]>([])
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
        void api<Profile[]>('/profiles').then(setManagedProfiles).catch(e => setError(String(e)))
        void api<Target[]>('/integrations').then(setTargets).catch(e => setError(String(e)))
        void api<Me>('/me').then(actor => {
            setMe(actor)
            if (actor.role === 'admin') void api<RuntimeState>('/sources/runtimes').then(setRuntimes).catch(e => setError(String(e)))
        }).catch(e => setError(String(e)))
        void api<Catalogue[]>('/sources/domains').then(setCatalogues).catch(e => setError(String(e)))
        void refresh()
        const itemId = Number(new URLSearchParams(window.location.search).get('media'))
        if (itemId > 0) void open(itemId)
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
        if (view !== 'management' || me?.role !== 'admin') return
        const update = () => void Promise.all([api<Job[]>('/jobs').then(setJobs),
            api<Export[]>('/integrations/exports').then(setExports)]).catch(e => setError(String(e)))
        update()
        const timer = window.setInterval(update, 10000)
        return () => window.clearInterval(timer)
    }, [view, me?.role])

    const resolve = buildServerAwareSubmit(urlForm, async (fields: URLFields) => {
        setBusy(true); setError(null); setPreview(null)
        try {
            setImportConnectionId(fields.connection_id ? Number(fields.connection_id) : null)
            return await formRequest('/resolve', 'POST', {url: fields.url, source_id: fields.source_id || null,
                connection_id: fields.connection_id ? Number(fields.connection_id) : null})
        } finally { setBusy(false) }
    }, {onSuccess: result => setPreview(result as Preview), rootOnFieldErrors: true})
    const search = buildServerAwareSubmit(searchForm, async (fields: SearchFields) => {
        setBusy(true); setError(null)
        try {
            setSearchRequest(fields)
            const params = new URLSearchParams({query: fields.query, limit: '30'})
            if (fields.connection_id) params.set('connection_id', fields.connection_id)
            return await fetch(`${base()}/sources/${encodeURIComponent(fields.source_id)}/search?${params}`, {credentials: 'include'})
        } finally { setBusy(false) }
    }, {onSuccess: result => setSearchPage(result as SearchPage), rootOnFieldErrors: true})
    const importPreview = async (item: Item) => {
        setPreview(null)
        await refresh()
        await open(item.id)
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
    const open = async (id: number, keepQueue = false) => {
        if (!keepQueue) setQueue([])
        setError(null); setJob(null); setFeedUrl(null); setOutputPreview(null); setSourceHistory(null)
        setView('library')
        try {
            const item = await api<Item>(`/library/${id}`)
            setSelected(item)
            const location = new URL(window.location.href); location.searchParams.set('media', String(id)); window.history.replaceState(null, '', location)
            setRemoteItems(await api<RemoteItem[]>(`/library/${id}/integrations`))
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
        try {
            if (me?.role === 'admin' && selected?.downloaded) {
                setJob(await api<Job>(`/library/${id}/download`, {method: 'POST',
                    body: JSON.stringify({profile_id: profileId, reference_id: referenceId})}))
            } else {
                const demand = await api<MediaRequest>(`/library/${id}/requests`, {method: 'POST',
                    body: JSON.stringify({profile_id: profileId, reference_id: referenceId})})
                if (demand.job_id) setJob(await api<Job>(`/jobs/${demand.job_id}`))
                setRunResult(demand.state === 'pending' ? 'Download requested; waiting for approval.' : `Request ${demand.state}.`)
            }
        }
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
            {errors.root && <p role="alert">{errors.root.message}</p>}
        </form>
        {sources.some(source => source.capabilities.includes('search')) && <section style={{marginBottom: 24}}>
            <h2>Search a Source</h2>
            <form onSubmit={search}
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
                {searchErrors.root && <p role="alert">{searchErrors.root.message}</p>}
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
            <ImportPreviewForm key={`${preview.reference.source_id}:${preview.reference.domain}:${preview.reference.namespace}:${preview.reference.upstream_id}:${importConnectionId}`}
                preview={preview} connectionId={importConnectionId} items={items}
                canLink={!!me?.manages_library} busy={busy} onImported={importPreview}/>
        </section>}
        </>}
        {view === 'home' && home && <section style={{marginBottom: 24}} aria-label="Home">
            <h2>Continue</h2>
            {home.continue.length === 0 && <p>Play an item to continue it here.</p>}
            <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>{home.continue.map(item =>
                <button className="btn" type="button" key={item.id} onClick={() => void open(item.id)}>
                    <MediaArtwork item={item} shape="square"/>{item.title} · {Math.floor(item.seconds / 60)} min</button>)}</div>
            <h2>Recent arrivals</h2>
            <div style={{display: 'flex', gap: 8, flexWrap: 'wrap'}}>{home.recent.map(item =>
                <button className="btn" type="button" key={item.id} onClick={() => void open(item.id)}>
                    <MediaArtwork item={item} shape={item.kind === 'movie' ? 'portrait' : 'landscape'}/>{item.title}{item.downloaded ? ' · Local' : ''}</button>)}</div>
            <h2>Activity</h2>
            <p>{home.activity.length} active downloads · {home.issues.length} issues</p>
            {home.issues.length > 0 && <button className="btn" type="button"
                onClick={() => setView('management')}>Review issues</button>}
        </section>}
        {view === 'management' && <section style={{marginBottom: 24}}><h2>Management</h2>
            {me && <RequestsView me={me} items={items} onOpen={open}/>}
            {me && <ListeningAccounts me={me} targets={targets}/>}
            {me?.role === 'admin' && <>
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
                    <option value="stable">Stable</option><option value="beta">Beta</option></select></label>{' '}
                <label>Pin version <select value={runtimes?.policy[source.source_id]?.pinned_version ?? ''} onChange={event => void api(`/sources/${encodeURIComponent(source.source_id)}/policy`, {method: 'PUT', body: JSON.stringify({automatic: runtimes?.policy[source.source_id]?.automatic ?? true, channel: runtimes?.policy[source.source_id]?.channel ?? 'stable', pinned_version: event.target.value || null})}).then(() => api<RuntimeState>('/sources/runtimes').then(setRuntimes)).catch(e => setError(String(e)))}><option value="">Follow channel</option>{Array.from(new Set([runtimes?.active[source.source_id], ...(runtimes?.installed[source.source_id] ?? [])])).filter(Boolean).map(version => <option key={version} value={version}>{version}</option>)}</select></label>
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
                targets={targets} onCreated={profile => {setProfiles(current => [...current, profile]); setManagedProfiles(current => [...current, profile])}} />}
            <h3>Local Media Profiles</h3>
            {managedProfiles.map(profile => <div key={profile.id} style={{marginBottom: 16}}>
                <p>{profile.name} · {profile.domain} · {profile.enabled ? 'Enabled' : 'Disabled'}
                    {profile.impairment && <span role="alert"> · {profile.impairment}</span>}</p>
                <DomainProfileForm initial={profile} domain={profile.domain} targets={targets}
                    onCreated={() => void api<Profile[]>('/profiles').then(setManagedProfiles)}/>{' '}
                <button className="btn" type="button" onClick={() => {
                    if (!window.confirm('Delete this profile? Shared files and download history are retained.')) return
                    void api(`/profiles/${profile.id}`, {method: 'DELETE'}).then(() => api<Profile[]>('/profiles').then(setManagedProfiles)).catch(e => setError(String(e)))
                }}>Delete profile</button>
            </div>)}
            <details><summary>Source update history</summary>{runtimes?.history?.slice().reverse().map((entry, index) =>
                <p key={index}>{new Date(entry.at).toLocaleString()} · {entry.source_id} · {entry.action} {entry.version} {entry.state} {entry.message}</p>)}</details>
            <h3>Source connections</h3>
            {connections.map(connection => <div key={connection.id} style={{marginBottom: 12}}>{connection.name} · {connection.source_id}
                {connection.has_secret ? ' · credential stored' : ' · anonymous'}
                {!connection.enabled && ' · disabled'}{' '}
                <button className="btn" type="button" onClick={() => void api<Connection>(
                    `/sources/connections/${connection.id}`, {method: 'PUT', body: JSON.stringify({
                        source_id: connection.source_id, name: connection.name,
                        settings: connection.settings, enabled: !connection.enabled})})
                    .then(updated => setConnections(current => current.map(item =>
                        item.id === updated.id ? updated : item))).catch(e => setError(String(e)))}>
                    {connection.enabled ? 'Disable' : 'Enable'}</button>
                <ConnectionForm initial={connection} sources={sources} onCreated={updated => setConnections(current => current.map(item => item.id === updated.id ? updated : item))}/>{' '}
                {connection.enabled && sources.find(source => source.source_id === connection.source_id)?.capabilities.includes('authentication') &&
                    <ConnectionAuthentication connection={connection} onUpdated={() => {
                        void api<Connection[]>('/sources/connections').then(setConnections)
                    }}/>} 
            </div>)}
            <ConnectionForm sources={sources} onCreated={connection => setConnections(current => [...current, connection])}/>
            <h3>Media servers</h3>
            {targets.map(target => <div key={target.id}>{target.name} · {target.kind} · library {target.library_id}{' '}
                <button type="button" className="btn" onClick={() => void api<unknown>(`/integrations/${target.id}/test`, {method: 'POST'})
                    .then(result => setRunResult(JSON.stringify(result))).catch(e => setError(String(e)))}>Test connection</button>{' '}
                <TargetForm initial={target} onCreated={updated => setTargets(current => current.map(value => value.id === updated.id ? updated : value))}/>
                {!target.enabled && ' · disabled'}
            </div>)}
            <TargetForm onCreated={target => setTargets(current => [...current, target])}/>
            <RSSDeliveries targets={targets}/>
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
            <UsersManagement connections={connections} targets={targets}/>
            {runResult && <p role="status">{runResult}</p>}
            </>}
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
            {selected.is_live && <p role="status">Live now</p>}
            {(selected.references?.length ?? 0) > 1 && <label>Source account{' '}
                <select value={referenceId ?? ''} onChange={event => setReferenceId(Number(event.target.value) || null)}>
                    <option value="">Choose a Source account</option>
                    {selected.references?.map(reference => <option key={reference.id} value={reference.id}>
                        {reference.source_id} · {connections.find(c => c.id === reference.connection_id)?.name ?? 'Anonymous'}
                    </option>)}
                </select>
            </label>}
            {me?.manages_library && <MetadataForm key={selected.id} item={selected} items={items} onSaved={updated => {
                setSelected(previous => previous?.id === updated.id ? {...previous, ...updated} : previous)
                void refresh()
            }}/>}
            {me?.role === 'admin' && <div style={{margin: '12px 0'}}>
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
            </div>}
            {selected.kind === 'collection' && me?.manages_library && <div style={{display: 'flex', gap: 10, marginBottom: 16}}>
                <button className="btn" type="button" disabled={me?.role !== 'admin' || busy || !referenceId}
                    onClick={() => void refreshCollection(selected.id)}>Refresh collection</button>
                <button className="btn" type="button" disabled={me?.role !== 'admin' || busy || !referenceId}
                    onClick={() => void refreshCollection(selected.id, 2)}>Expand nested collections (2 levels, 20 max)</button>
                <button className="btn" type="button" disabled={busy} onClick={() => {
                    if (!window.confirm('Remove this collection and its feeds? Shared local media will remain available.')) return
                    void api<unknown>(`/library/${selected.id}`, {method: 'DELETE'})
                        .then(() => {setSelected(null); void refresh()}).catch(e => setError(String(e)))
                }}>Remove collection</button>
            </div>}
            {selected.kind === 'collection' && <section>
                <h3>Collection downloads</h3>
                {downloadPolicies.map(policy => <div key={policy.id}>{policy.name} · {policy.backfill}
                    {policy.retain_newest && ` · keep newest ${policy.retain_newest}`}
                    {policy.retain_days && ` · ${policy.retain_days} days`}{' '}
                    {me?.role === 'admin' && <><button type="button" className="btn" onClick={() => void runDownloadPolicy(policy.id)}>Run now</button>{' '}
                    <DownloadPolicyForm initial={policy} collection={selected} collectionId={selected.id} profiles={profiles} sourceReferenceId={referenceId} references={selected.references ?? []} onCreated={updated => setDownloadPolicies(current => current.map(value => value.id === updated.id ? updated : value))}/>{' '}
                    <button type="button" className="btn" onClick={() => void api(`/download-profiles/${policy.id}`, {method: 'DELETE'}).then(() => setDownloadPolicies(current => current.filter(value => value.id !== policy.id))).catch(e => setError(String(e)))}>Delete</button></>}</div>)}
                {me?.role === 'admin' && <DownloadPolicyForm collection={selected} collectionId={selected.id} profiles={profiles}
                    sourceReferenceId={referenceId} references={selected.references ?? []}
                    onCreated={policy => setDownloadPolicies(previous => [...previous, policy])}/>}
                <h3>Collection feeds</h3>
                {streamProfiles.map(profile => <div key={profile.id}>{profile.name} · {profile.format}
                    {profile.include_live && ' · live admission'}{' '}
                    {me?.can_subscribe && <><button type="button" className="btn" onClick={() => void createStreamFeed(profile.id)}>Get feed</button>{' '}
                    <button type="button" className="btn" onClick={() => void api<{url: string}>(`/stream-profiles/${profile.id}/feed/rotate`, {method: 'POST'}).then(result => {setFeedUrl(result.url); setRunResult('Old feed URL revoked.')}).catch(e => setError(String(e)))}>Rotate URL</button>{' '}
                    <button type="button" className="btn" onClick={() => void api(`/stream-profiles/${profile.id}/feed`, {method: 'DELETE'}).then(() => {setFeedUrl(null); setRunResult('Feed revoked.')}).catch(e => setError(String(e)))}>Revoke my feed</button></>}{' '}
                    {me?.role === 'admin' && <>{!profile.local_only && <button type="button" className="btn" onClick={() => void api<{queued_job_ids: number[]; skipped: {reason: string}[]}>(`/stream-profiles/${profile.id}/prepare`, {method: 'POST'}).then(result => setRunResult(`Queued ${result.queued_job_ids.length} feed renditions. ${result.skipped.map(value => value.reason).join(' ')}`)).catch(e => setError(String(e)))}>Prepare now</button>}{' '}
                    <StreamProfileForm initial={profile} profiles={profiles} sourceReferenceId={referenceId} collection={selected} collectionId={selected.id} onCreated={updated => setStreamProfiles(current => current.map(value => value.id === updated.id ? updated : value))}/>{' '}
                    <button type="button" className="btn" onClick={() => void api(`/stream-profiles/${profile.id}`, {method: 'DELETE'}).then(() => setStreamProfiles(current => current.filter(value => value.id !== profile.id))).catch(e => setError(String(e)))}>Delete profile</button></>}</div>)}
                {me?.role === 'admin' && <StreamProfileForm profiles={profiles} sourceReferenceId={referenceId} collection={selected} collectionId={selected.id}
                    onCreated={profile => setStreamProfiles(previous => [...previous, profile])}/>}
                {me?.role === 'admin' && <RSSDeliveryForm targets={targets} profiles={streamProfiles}/>}
                {runResult && <p role="status">{runResult}</p>}
            </section>}
            {feedUrl && <p><a href={feedUrl} target="_blank" rel="noreferrer">{feedUrl}</a></p>}
            {selected.kind !== 'collection' && <>
                {remoteItems.length > 0 && <div style={{margin: '12px 0'}}><h3>Media servers</h3>
                    {remoteItems.map(remote => <p key={remote.progress_path}>{remote.name} · {remote.state}{' '}
                        {remote.url && <a href={remote.url} target="_blank" rel="noreferrer">Open in {remote.name}</a>}
                        {remote.kind === 'audiobookshelf' && remote.state === 'available' &&
                            remote.remote_episode_id && <button className="btn" type="button"
                                onClick={() => void api(remote.progress_path,
                                    {method: 'POST'}).then(() => setRunResult('Audiobookshelf progress imported.'))
                                    .catch(e => setError(String(e)))}>Import progress</button>}</p>)}
                </div>}
                <button className="btn" type="button" disabled={me?.role !== 'admin' || busy || !referenceId}
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
                {me?.role === 'admin' && <DomainProfileForm domain={selected.domain} formats={selected.formats} targets={targets} onCreated={profile => {
                    setProfiles(previous => [...previous, profile]); setProfileId(profile.id)
                    void showOutputPreview(profile.id, selected.id, profile)
                }}/> }
                <button className="btn btn-primary" type="button" disabled={!profileId || !referenceId ||
                    selected.capabilities !== null && selected.capabilities !== undefined && !selected.capabilities.includes('download') ||
                    !!job && !['failed', 'available'].includes(job.state)}
                        onClick={() => void download(selected.id)}>{me?.role !== 'admin' ? 'Request download' : selected.downloaded ? 'Download again' : 'Download'}</button>
                {runResult && <p role="status">{runResult}</p>}
                {selected.capabilities && !selected.capabilities.includes('download') &&
                    <p>This Source does not advertise a download for this item.</p>}
                {job && <p role="status">Download: {job.state}{job.progress !== undefined ? ` · ${job.progress}%` : ''}
                    {job.error_code ? ` · ${job.error_code.replace(/_/g, ' ')}` : ''}
                    {job.failed_stage ? ` during ${job.failed_stage}` : ''}
                    {job.error ? ` · ${job.error}` : ''}</p>}
                {me?.role === 'admin' && job && ['queued', 'resolving', 'downloading', 'processing', 'verifying'].includes(job.state) &&
                    <button className="btn" type="button" disabled={job.cancel_requested}
                        onClick={() => void api<Job>(`/jobs/${job.id}/cancel`, {method: 'POST'})
                            .then(() => setJob(previous => previous ? {...previous, cancel_requested: true} : null))
                            .catch(e => setError(String(e)))}>Cancel download</button>}
                {me?.role === 'admin' && job && ['failed', 'canceled'].includes(job.state) &&
                    <button className="btn" type="button" onClick={() => void api<Job>(`/jobs/${job.id}/retry`, {method: 'POST'})
                        .then(next => setJob({...job, ...next})).catch(e => setError(String(e)))}>Retry download</button>}
                {me?.role === 'admin' && selected.downloaded && profileId && <button className="btn" type="button" onClick={() => {
                    if (!window.confirm('Remove this local representation and pause automatic downloads for it?')) return
                    void api(`/library/${selected.id}/local/${profileId}`, {method: 'DELETE'})
                        .then(() => api<Item>(`/library/${selected.id}`).then(setSelected))
                        .then(() => refresh()).catch(e => setError(String(e)))
                }}>Remove local copy</button>}
                {me?.role === 'admin' && profileId && <button className="btn" type="button" onClick={() => {
                    void api(`/library/${selected.id}/local/${profileId}/resume`, {method: 'POST'})
                        .then(() => setRunResult('Automatic acquisition is allowed again for this profile.')).catch(e => setError(String(e)))
                }}>Allow automatic acquisition</button>}
                {(selected.downloaded || selected.capabilities?.includes('stream_lease') ||
                    selected.references?.some(ref => sources.find(source => source.source_id === ref.source_id)?.capabilities.includes('stream_lease'))) &&
                    <LocalPlayer key={`${selected.id}:${referenceId ?? ''}`} item={selected} referenceId={referenceId} onEnded={() => {const next = queue[0]; if (next) {setQueue(current => current.slice(1)); void open(next.id, true)}}} />}
            </>}
            {queue.length > 0 && <div><h3>Up next</h3><ol>{queue.map((entry, index) => <li key={`${entry.id}:${index}`}>{entry.title}</li>)}</ol>
                <button className="btn" type="button" onClick={() => setQueue([])}>Clear queue</button></div>}
            {selected.kind === 'collection' && selected.entries?.some(entry => entry.kind !== 'collection') && <button className="btn" type="button" onClick={() => {
                const playable = selected.entries!.filter(entry => entry.kind !== 'collection')
                setQueue(playable.slice(1)); void open(playable[0].id, true)
            }}>Play collection in order</button>}
            {selected.entries && <div style={{display: 'grid', gap: 8}}>{selected.entries.map(entry =>
                <button type="button" className="btn" key={entry.id} onClick={() => void open(entry.id)}
                        style={{textAlign: 'left'}}><MediaArtwork item={entry} shape="square"/>{entry.title}{entry.downloaded ? ' · Local' : ''}</button>)}</div>}
            {selected.extras && selected.extras.length > 0 && <section><h3>Movie extras</h3>
                <div style={{display: 'grid', gap: 8}}>{selected.extras.map(extra =>
                    <button type="button" className="btn" key={extra.id} onClick={() => void open(extra.id)}
                        style={{textAlign: 'left'}}>{extra.title}{extra.downloaded ? ' · Local' : ''}</button>)}</div>
            </section>}
        </section>}
        </>}
    </section>
}

const ImportPreviewSchema = z.object({
    existing_item_id: z.string().regex(/^(?:[1-9]\d*)?$/).default(''),
    confirm_same_edition: z.boolean().default(false),
}).refine(values => !values.existing_item_id || values.confirm_same_edition, {
    message: 'Confirm that both references describe the same edit, language, and edition.',
    path: ['confirm_same_edition'],
})

function ImportPreviewForm({preview, connectionId, items, canLink, busy, onImported}: {
    preview: Preview; connectionId: number | null; items: Item[]; canLink: boolean; busy: boolean;
    onImported: (item: Item) => Promise<void>;
}) {
    const form = useForm<z.input<typeof ImportPreviewSchema>, unknown, z.output<typeof ImportPreviewSchema>>({
        resolver: zodResolver(ImportPreviewSchema), defaultValues: ImportPreviewSchema.parse({}),
    })
    const {register, watch, formState: {errors, isSubmitting}} = form
    const existingId = watch('existing_item_id')
    const candidates = items.filter(item => item.domain === preview.reference.domain.replace(/\.$/, '').toLowerCase() &&
        (item.kind === preview.kind || (preview.kind === 'video' && ['movie', 'movie_extra'].includes(item.kind))))
    const submit = buildServerAwareSubmit(form, values => formRequest('/import', 'POST', {
        snapshot: preview, connection_id: connectionId,
        existing_item_id: canLink && values.existing_item_id ? Number(values.existing_item_id) : null,
        confirm_same_edition: canLink && values.confirm_same_edition,
    }), {onSuccess: result => onImported(result as Item)})
    return <form onSubmit={submit}>
        <fieldset disabled={busy || isSubmitting} style={{border: 0, padding: 0}}>
            {canLink && candidates.length > 0 && <>
                <label>Library identity <select {...register('existing_item_id', {
                    onChange: () => form.setValue('confirm_same_edition', false),
                })}>
                    <option value="">Import using this Source's identity</option>
                    {candidates.map(item => <option key={item.id} value={item.id}>{item.title} · {item.kind} · #{item.id}</option>)}
                </select></label>
                {existingId && <div style={{margin: '12px 0'}}>
                    <label><input type="checkbox" {...register('confirm_same_edition')}/>{' '}
                        I confirm this is the same edit, language, and edition as the selected item.</label>
                    <p>Link this Source to the existing item. Its metadata, memberships, Movie relationships, and local files are preserved.
                        Different editions and alternate uploads should have separate library identities.</p>
                    {errors.confirm_same_edition && <p role="alert">{errors.confirm_same_edition.message}</p>}
                </div>}
                {errors.existing_item_id && <p role="alert">{errors.existing_item_id.message}</p>}
            </>}
            <button className="btn btn-primary" type="submit">{isSubmitting ? 'Saving…' : existingId ? 'Link Source to item' : 'Add to library'}</button>
        </fieldset>
        {errors.root && <p role="alert">{errors.root.message}</p>}
    </form>
}

function MediaArtwork({item, shape}: {item: Item; shape: 'square' | 'portrait' | 'landscape'}) {
    const [failed, setFailed] = useState(false)
    useEffect(() => setFailed(false), [item.id, item.artwork_url, item.artwork_available, shape])
    if ((!item.artwork_url && !item.artwork_available) || failed) return null
    return <img src={`${base()}/library/${item.id}/artwork?shape=${shape}`} alt="" loading="lazy" referrerPolicy="no-referrer"
        onError={() => setFailed(true)} style={{width: shape === 'square' ? 64 : shape === 'portrait' ? 100 : 160,
            aspectRatio: shape === 'portrait' ? '2/3' : shape === 'square' ? '1' : '16/9', objectFit: 'cover', borderRadius: 8, marginRight: 12}}/>
}

function LocalPlayer({item, referenceId, onEnded}: {item: Item; referenceId: number | null; onEnded?: () => void}) {
    const player = useRef<HTMLVideoElement & HTMLAudioElement>(null)
    const hlsPlayer = useRef<Hls | null>(null)
    const resumed = useRef(false)
    const saving = useRef<Promise<unknown>>(Promise.resolve())
    const lastSaved = useRef(0)
    const [position, setPosition] = useState(0)
    const [speed, setSpeed] = useState(1)
    const [subtitles, setSubtitles] = useState<{index: number; label: string}[]>([])
    const [retry, setRetry] = useState(0)
    const [delivery, setDelivery] = useState<{transport: string; url: string} | null>(null)
    const [failure, setFailure] = useState<string | null>(null)
    useEffect(() => {
        let disposed = false
        void api<{seconds: number}>(`/library/${item.id}/progress`).then(data => {if (!disposed) setPosition(data.seconds)})
            .catch(() => {})
        return () => {disposed = true}
    }, [item.id])
    useEffect(() => {
        let disposed = false
        setDelivery(null); setFailure(null); resumed.current = false
        void api<{transport: string; url: string}>(`/library/${item.id}/watch${referenceId ? `?reference_id=${referenceId}` : ''}`, {method: 'POST'})
            .then(result => {if (!disposed) setDelivery(result)}).catch(error => {if (!disposed) setFailure(String(error))})
        return () => {disposed = true}
    }, [item.id, referenceId, retry])
    const resume = () => {
        const element = player.current
        if (element) element.playbackRate = speed
        if (element && !resumed.current && position > 0 && element.readyState >= 1 && position < element.duration - 1) {
            element.currentTime = position; resumed.current = true
        }
    }
    useEffect(resume, [position, delivery])
    useEffect(() => {
        const element = player.current
        if (!element || !delivery || delivery.transport !== 'hls' || element.canPlayType('application/vnd.apple.mpegurl')) return
        let disposed = false
        void import('hls.js').then(({default: Hls}) => {
            if (disposed) return
            if (!Hls.isSupported()) {setFailure('This browser cannot play this stream. Download a local copy.'); return}
            const hls = new Hls({enableWorker: true}); hlsPlayer.current = hls
            hls.on(Hls.Events.MANIFEST_PARSED, () => setSubtitles(hls.subtitleTracks.map((track, index) => ({index, label: track.name || track.lang || `Track ${index + 1}`}))))
            hls.on(Hls.Events.ERROR, (_event, data) => {if (data.fatal) setFailure('Playback was interrupted. Restart playback to obtain a new session.')})
            hls.loadSource(delivery.url); hls.attachMedia(element)
        }).catch(() => setFailure('This browser cannot play this stream. Download a local copy.'))
        return () => {disposed = true; hlsPlayer.current?.destroy(); hlsPlayer.current = null}
    }, [delivery])
    const save = (completed = false) => {
        const current = player.current?.currentTime ?? 0
        if (!Number.isFinite(current)) return Promise.resolve()
        lastSaved.current = current
        saving.current = saving.current.then(() => api(`/library/${item.id}/progress`, {method: 'PUT',
            body: JSON.stringify({seconds: current, completed})})).catch(() => {})
        return saving.current
    }
    const common = {controls: true, preload: 'metadata' as const,
        src: delivery?.transport === 'hls' && !player.current?.canPlayType('application/vnd.apple.mpegurl') ? undefined : delivery?.url,
        onLoadedMetadata: () => {
            resume()
            if (player.current && !hlsPlayer.current) setSubtitles(Array.from(player.current.textTracks).map((track, index) => ({index, label: track.label || track.language || `Track ${index + 1}`})))
        },
        onTimeUpdate: () => {if (player.current && Math.abs(player.current.currentTime - lastSaved.current) >= 10) void save()},
        onPause: () => {if (!player.current?.ended) void save()},
        onEnded: () => {void save(true).then(() => onEnded?.())},
        onError: () => setFailure('Playback is unavailable. Restart playback or prepare a compatible local copy.'),
        style: {display: 'block', width: 'min(100%, 800px)', marginTop: 16}}
    return <div>{failure && <p role="alert">{failure} <button className="btn" type="button" onClick={() => setRetry(value => value + 1)}>Restart playback</button></p>}
        {!delivery && !failure && <p>Preparing playback…</p>}
        {delivery && <>{item.playback_type === 'audio' ? <audio ref={player} {...common}/> : <video ref={player} {...common}/>}
            <label>Speed <select value={speed} onChange={event => {const value = Number(event.target.value); setSpeed(value); if (player.current) player.current.playbackRate = value}}>
                {[0.75, 1, 1.25, 1.5, 1.75, 2].map(value => <option key={value} value={value}>{value}×</option>)}</select></label>{' '}
            {subtitles.length > 0 && <label>Subtitles <select defaultValue="-1" onChange={event => {
                const selected = Number(event.target.value)
                if (hlsPlayer.current) hlsPlayer.current.subtitleTrack = selected
                else if (player.current) Array.from(player.current.textTracks).forEach((track, index) => {track.mode = index === selected ? 'showing' : 'disabled'})
            }}><option value="-1">Off</option>{subtitles.map(track => <option key={track.index} value={track.index}>{track.label}</option>)}</select></label>}
            {!!item.chapters?.length && <details><summary>Chapters</summary>{item.chapters.map((chapter, index) =>
                <button className="btn" type="button" key={index} onClick={() => {if (player.current) player.current.currentTime = chapter.start}}>{chapter.title} · {Math.floor(chapter.start / 60)}:{String(Math.floor(chapter.start % 60)).padStart(2, '0')}</button>)}</details>}
        </>}
    </div>
}

function DomainProfileForm({domain, formats, targets, initial, onCreated}: {domain: string; formats?: Item['formats'];
    targets: Target[]; initial?: Profile; onCreated: (profile: Profile) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [deliveryIds, setDeliveryIds] = useState<number[]>(initial?.delivery_target_ids ?? [])
    const form = useForm<ProfileFields, unknown, z.output<typeof ProfileFormSchema>>({
        resolver: zodResolver(ProfileFormSchema),
        defaultValues: {...ProfileFormSchema.partial({name: true, output_template: true, preferred_format: true}).parse({}),
            name: `${domain} video`, preferred_format: 'format_1080p',
            output_template: '/downloads/{{ domain }}/{{ title }} - {{ id }}.ext',
            ...(initial ? {...initial, preferred_format: initial.preferred_format as ProfileFields['preferred_format'], applicable_kinds: initial.applicable_kinds as z.output<typeof ProfileFormSchema>['applicable_kinds'], ...initial.representation,
                languages: initial.representation.languages.join(', '), subtitles: initial.representation.subtitles.join(', ')} : {})},
    })
    const {register, formState: {errors, isSubmitting}, setValue, watch} = form
    const audioOnly = watch('preferred_format') === 'format_audio_only'
    useEffect(() => {
        const container = watch('container')
        if (audioOnly && ['mp4', 'mkv'].includes(container ?? '') ||
            !audioOnly && ['mp3', 'm4a', 'opus'].includes(container ?? '')) setValue('container', 'source')
    }, [audioOnly])
    useEffect(() => {
        if (formats?.length && !formats.some(format => format.code === 'format_1080p'))
            setValue('preferred_format', formats[0].code as ProfileFields['preferred_format'])
    }, [formats, setValue])
    const submit = buildServerAwareSubmit(form, (values: z.output<typeof ProfileFormSchema>) => formRequest(
        initial ? `/profiles/${initial.id}` : '/profiles', initial ? 'PUT' : 'POST', {
            name: values.name, domain, preferred_format: values.preferred_format, output_template: values.output_template,
            applicable_kinds: values.applicable_kinds, enabled: values.enabled, delivery_target_ids: deliveryIds,
            representation: {languages: values.languages.split(',').map(code => code.trim()).filter(Boolean),
                subtitles: audioOnly ? [] : values.subtitles.split(',').map(code => code.trim()).filter(Boolean),
                container: values.container, video_codec: audioOnly ? 'source' : values.video_codec, audio_codec: values.audio_codec,
                chapters: values.chapters, artwork: values.artwork, embed_metadata: values.embed_metadata, language_fallback: values.language_fallback},
        }), {successStatuses: [200, 201], onSuccess: result => {onCreated(result as Profile); setExpanded(false)}})
    if (!expanded) return <button type="button" className="btn" style={{marginRight: 12}}
                                  onClick={() => setExpanded(true)}>{initial ? 'Edit profile' : 'Create Local Media Profile'}</button>
    return <form onSubmit={submit} style={{display: 'grid', maxWidth: 640, gap: 10, marginBottom: 16}}>
        <h3>{initial ? 'Edit profile' : 'New profile'} for {domain}</h3>
        <label><input type="checkbox" {...register('enabled')}/> Enabled</label>
        <fieldset><legend>Media types</legend>{['video', 'movie', 'movie_extra'].map(kind => <label key={kind} style={{marginRight: 12}}><input type="checkbox" value={kind} {...register('applicable_kinds')}/> {kind.replace('_', ' ')}</label>)}</fieldset>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Preferred format <select {...register('preferred_format')}>
            {(formats?.length ? formats : [
                {code: 'format_720p', description: 'Video up to 720p', audio_only: false},
                {code: 'format_1080p', description: 'Video up to 1080p', audio_only: false},
                {code: 'format_4k', description: 'Video up to 4K', audio_only: false},
                {code: 'format_audio_only', description: 'Audio only (MP3)', audio_only: true},
            ]).map(format => <option key={format.code} value={format.code}>
                {format.description ?? format.code.replace(/_/g, ' ')}</option>)}
        </select></label>
        <fieldset><legend>Representation</legend>
            <label>Audio languages <input {...register('languages')} placeholder="en, nl" />
                {errors.languages && <span role="alert">{errors.languages.message}</span>}</label>
            <label style={{display: 'block'}}><input type="checkbox" {...register('language_fallback')} /> Allow another language when the preferred tracks are unavailable</label>
            {!audioOnly && <label>Subtitle languages <input {...register('subtitles')} placeholder="en, nl" />
                {errors.subtitles && <span role="alert">{errors.subtitles.message}</span>}</label>}
            <label>Container <select {...register('container')}><option value="source">Automatic</option>
                {(audioOnly ? ['mp3', 'm4a', 'opus'] : ['mp4', 'mkv']).map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}
            </select></label>
            {!audioOnly && <label>Video codec <select {...register('video_codec')}><option value="source">Automatic</option>
                {['h264', 'h265', 'vp9', 'av1'].map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label>}
            <label>Audio codec <select {...register('audio_codec')}><option value="source">Automatic</option>
                {['aac', 'mp3', 'opus'].map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label>
            <label style={{display: 'block'}}><input type="checkbox" {...register('chapters')} /> Include chapters when supplied</label>
            <label style={{display: 'block'}}><input type="checkbox" {...register('artwork')} /> Embed artwork when supplied</label>
            <label style={{display: 'block'}}><input type="checkbox" {...register('embed_metadata')} /> Embed the library title and description</label>
        </fieldset>
        <DomainTemplateEditor form={form} domain={domain}/>
        {targets.length > 0 && <fieldset><legend>Media-server delivery</legend>{targets.map(target =>
            <label key={target.id} style={{display: 'block'}}><input type="checkbox" checked={deliveryIds.includes(target.id)}
                onChange={event => setDeliveryIds(current => event.target.checked ? [...current, target.id] :
                    current.filter(id => id !== target.id))} /> {target.name} ({target.kind})</label>)}</fieldset>}
        {errors.root && <p role="alert">{errors.root.message}</p>}
        <div><button type="submit" className="btn btn-primary" disabled={isSubmitting}>Save profile</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const DownloadPolicySchema = z.object({
    selected_groups: z.array(z.string()).nullable().default(null), include_future_groups: z.boolean().default(true), member_roles: z.array(z.string()).nullable().default(null),
    enabled: z.boolean().default(true),
    name: z.string().min(1).default('New episodes'),
    backfill: z.enum(['newest', 'all', 'date_range', 'metadata_only']).default('newest'),
    newest_count: z.coerce.number().int().min(1).max(1000).default(10),
    refresh_minutes: z.coerce.number().int().min(15).max(10080).default(60),
    retain_newest: z.string().default(''), retain_days: z.string().default(''),
    published_after: z.string().default(''), published_before: z.string().default(''),
    title_contains: z.string().max(200).default(''),
})
type PolicyFields = z.input<typeof DownloadPolicySchema>

function DownloadPolicyForm({collection, collectionId, profiles, sourceReferenceId, references, initial, onCreated}: {
    collection: Item;
    collectionId: number; profiles: Profile[]; sourceReferenceId: number | null;
    references: NonNullable<Item['references']>; initial?: DownloadPolicy; onCreated: (profile: DownloadPolicy) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [selectedIds, setSelectedIds] = useState<number[]>(initial?.local_profile_ids ?? [])
    const form = useForm<PolicyFields, unknown, z.output<typeof DownloadPolicySchema>>({
        resolver: zodResolver(DownloadPolicySchema),
        defaultValues: {...DownloadPolicySchema.partial({name: true}).parse({}), name: 'New episodes',
            ...(initial ? {...initial, backfill: initial.backfill as z.output<typeof DownloadPolicySchema>['backfill'], published_after: initial.published_after ?? '', published_before: initial.published_before ?? '', title_contains: initial.title_contains ?? '', retain_newest: initial.retain_newest?.toString() ?? '', retain_days: initial.retain_days?.toString() ?? ''} : {})},
    })
    const {register, formState: {errors, isSubmitting}} = form
    const submit = buildServerAwareSubmit(form, (values: z.output<typeof DownloadPolicySchema>) => {
        if (!selectedIds.length) throw new Error('Select at least one Local Media Profile.')
        const reference = initial?.source_reference_id ?? sourceReferenceId
        if (!reference && references.length > 1) throw new Error('Select a Source account above.')
        return formRequest(initial ? `/download-profiles/${initial.id}` : `/library/${collectionId}/download-profiles`, initial ? 'PUT' : 'POST', {
            ...values, published_after: values.published_after || null, published_before: values.published_before || null,
            title_contains: values.title_contains || null, retain_newest: values.retain_newest ? Number(values.retain_newest) : null,
            retain_days: values.retain_days ? Number(values.retain_days) : null, local_profile_ids: selectedIds,
            source_reference_id: reference, enabled: values.enabled,
        })
    }, {successStatuses: [200, 201], onSuccess: result => {onCreated(result as DownloadPolicy); setExpanded(false)}})
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>{initial ? 'Edit Download Profile' : 'Create Download Profile'}</button>
    return <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 620, margin: '12px 0'}}>
        <label><input type="checkbox" {...register('enabled')}/> Enabled</label>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Backfill <select {...register('backfill')}><option value="newest">Newest N</option>
            <option value="all">All imported members</option><option value="date_range">Date range</option>
            <option value="metadata_only">Metadata only</option></select></label>
        <label>Newest count <input type="number" {...register('newest_count')} /></label>
        <label>Published on or after <input type="date" {...register('published_after')} /></label>
        <label>Published on or before <input type="date" {...register('published_before')} /></label>
        <label>Title contains <input {...register('title_contains')} /></label>
        <MembershipFilter form={form} collection={collection}/>
        <label>Refresh every (minutes) <input type="number" {...register('refresh_minutes')} /></label>
        <label>Keep newest items (optional) <input type="number" min="1" {...register('retain_newest')} /></label>
        <label>Keep items for days (optional) <input type="number" min="1" {...register('retain_days')} /></label>
        <fieldset><legend>Local Media Profiles by member Domain</legend>{profiles.map(profile =>
            <label key={profile.id} style={{display: 'block'}}><input type="checkbox" checked={selectedIds.includes(profile.id)}
                onChange={event => setSelectedIds(current => event.target.checked ? [...current, profile.id] :
                    current.filter(id => id !== profile.id))} /> {profile.name} · {profile.domain} · {profile.preferred_format}</label>)}</fieldset>
        {profiles.length === 0 && <p>Create a Local Media Profile on a playable member first.</p>}
        {errors.root && <p role="alert">{errors.root.message}</p>}
        <div><button type="submit" className="btn btn-primary" disabled={isSubmitting}>Save Download Profile</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const StreamProfileSchema = z.object({enabled: z.boolean().default(true), name: z.string().min(1).default('Podcast feed'), format: z.enum(['audio', 'video']).default('audio'),
    source_reference_id: z.string().default(''), local_profile_ids: z.array(z.number()).default([]), refresh_minutes: z.coerce.number().int().min(15).max(10080).default(60), allow_other_renditions: z.boolean().default(false),
    selected_groups: z.array(z.string()).nullable().default(null), include_future_groups: z.boolean().default(true), member_roles: z.array(z.string()).nullable().default(null),
    max_items: z.coerce.number().int().min(0).max(10000).default(50), feed_title: z.string().max(200).default(''),
    include_live: z.boolean().default(false), local_only: z.boolean().default(true),
    published_after: z.string().default(''), published_before: z.string().default(''),
    title_contains: z.string().max(200).default('')}).refine(
        values => !values.published_after || !values.published_before || values.published_after <= values.published_before,
        {path: ['published_before'], message: 'End date must follow start date'})
type StreamFields = z.input<typeof StreamProfileSchema>

function StreamProfileForm({collection, collectionId, profiles, sourceReferenceId, initial, onCreated}: {collection: Item; collectionId: number; profiles: Profile[]; sourceReferenceId: number | null; initial?: StreamProfile; onCreated: (profile: StreamProfile) => void}) {
    const [expanded, setExpanded] = useState(false)
    const form = useForm<StreamFields, unknown, z.output<typeof StreamProfileSchema>>({
        resolver: zodResolver(StreamProfileSchema), defaultValues: {...StreamProfileSchema.partial({name: true}).parse({}), name: 'Podcast feed',
            ...(initial ? {...initial, feed_title: initial.feed_title ?? '', format: initial.format as 'audio' | 'video', published_after: initial.published_after ?? '', published_before: initial.published_before ?? '', title_contains: initial.title_contains ?? ''} : {}),
            source_reference_id: String(initial?.source_reference_id ?? sourceReferenceId ?? '')},
    })
    const {register, formState: {errors, isSubmitting}} = form
    const selectedIds = form.watch('local_profile_ids') ?? []
    const rendition = form.watch('format')
    const submit = buildServerAwareSubmit(form, (values: z.output<typeof StreamProfileSchema>) => formRequest(
        initial ? `/stream-profiles/${initial.id}` : `/library/${collectionId}/stream-profiles`, initial ? 'PUT' : 'POST', {
            ...values, published_after: values.published_after || null, published_before: values.published_before || null,
            title_contains: values.title_contains || null,
            feed_title: values.feed_title || null,
            source_reference_id: values.source_reference_id ? Number(values.source_reference_id) : null,
        }), {successStatuses: [200, 201], onSuccess: result => {onCreated(result as StreamProfile); setExpanded(false)}})
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>{initial ? 'Edit Stream Profile' : 'Create Stream Profile'}</button>
    return <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 500, margin: '12px 0'}}>
        <label><input type="checkbox" {...register('enabled')}/> Enabled</label>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Rendition <select {...register('format')}><option value="audio">Podcast audio</option>
            <option value="video">Video feed</option></select></label>
        <label>Feed title (optional) <input {...register('feed_title')}/></label>
        <label>Maximum entries (0 for all) <input type="number" min="0" max="10000" {...register('max_items')}/></label>
        <MembershipFilter form={form} collection={collection}/>
        <label>Published on or after <input type="date" {...register('published_after')} /></label>
        <label>Published on or before <input type="date" {...register('published_before')} />
            {errors.published_before && <span role="alert">{errors.published_before.message}</span>}</label>
        <label>Title contains <input {...register('title_contains')} /></label>
        <label><input type="checkbox" {...register('include_live')} /> Include live items</label>
        <label><input type="checkbox" {...register('local_only')} /> Use existing local files only</label>
        <label>Source account <select {...register('source_reference_id')}><option value="">Automatic when unambiguous</option>
            {(collection.references ?? []).map(reference => <option key={reference.id} value={reference.id}>{reference.source_id} · {reference.connection_id ? `account ${reference.connection_id}` : 'public'} · {reference.upstream_id}</option>)}</select></label>
        <label>Refresh every (minutes) <input type="number" min="15" max="10080" {...register('refresh_minutes')}/></label>
        {!form.watch('local_only') && <fieldset><legend>Prepare portable files using Local Media Profiles</legend>
            {profiles.filter(profile => (profile.preferred_format === 'format_audio_only') === (rendition === 'audio')).map(profile => <label key={profile.id} style={{display: 'block'}}>
                <input type="checkbox" checked={selectedIds.includes(profile.id)} onChange={event => form.setValue('local_profile_ids', event.target.checked ? [...selectedIds, profile.id] : selectedIds.filter(id => id !== profile.id), {shouldDirty: true})}/>
                {' '}{profile.name} · {profile.domain}</label>)}
            <p>Select MP3 or M4A audio profiles, or an MP4 video profile, for each member Domain.</p></fieldset>}
        <label><input type="checkbox" {...register('allow_other_renditions')}/> Allow other portable local renditions when the selected profile is unavailable</label>
        <p>Subscribed feeds refresh automatically. Enclosures appear when portable local files are ready and retain their published bytes. With local files only, live admission also requires an enabled Download Profile.</p>
        {errors.root && <p role="alert">{errors.root.message}</p>}
        <div><button type="submit" className="btn btn-primary" disabled={isSubmitting}>Save Stream Profile</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

function MembershipFilter({form, collection}: {form: UseFormReturn<any, any, any>; collection: Item}) {
    const groups = form.watch('selected_groups') as string[] | null
    const roles = form.watch('member_roles') as string[] | null
    const options = (available: string[] | undefined, selected: string[] | null) => [...new Set([...(available ?? []), ...(selected ?? [])])]
    const toggle = (field: string, selected: string[] | null, value: string, enabled: boolean) =>
        form.setValue(field, enabled ? [...(selected ?? []), value] : (selected ?? []).filter(v => v !== value), {shouldDirty: true})
    return <fieldset><legend>Collection members</legend>
        <label><input type="checkbox" checked={groups !== null} onChange={e => form.setValue('selected_groups', e.target.checked ? [] : null)}/> Select groups</label>
        {groups !== null && <>{options(collection.member_groups, groups).map(group => <label key={group} style={{display: 'block'}}>
            <input type="checkbox" checked={groups.includes(group)} onChange={e => toggle('selected_groups', groups, group, e.target.checked)}/> {group || 'Ungrouped'}</label>)}
            <label><input type="checkbox" {...form.register('include_future_groups')}/> Include new groups discovered after saving</label></>}
        <label><input type="checkbox" checked={roles !== null} onChange={e => form.setValue('member_roles', e.target.checked ? [] : null)}/> Select member roles</label>
        {roles !== null && options(collection.member_roles, roles).map(role => <label key={role} style={{display: 'block'}}>
            <input type="checkbox" checked={roles.includes(role)} onChange={e => toggle('member_roles', roles, role, e.target.checked)}/> {role.split('_').join(' ') || 'Unspecified'}</label>)}
    </fieldset>
}

const TargetSchema = z.object({
    kind: z.enum(['jellyfin', 'plex', 'audiobookshelf']).default('jellyfin'),
    name: z.string().min(1).default(''), base_url: z.url().default(''), library_id: z.string().min(1).default(''),
    local_prefix: z.string().startsWith('/').default('/downloads'), server_prefix: z.string().startsWith('/').default('/media'), api_key: z.string().default(''), enabled: z.boolean().default(true),
})
type TargetFields = z.input<typeof TargetSchema>

function TargetForm({initial, onCreated}: {initial?: Target; onCreated: (target: Target) => void}) {
    const [expanded, setExpanded] = useState(false)
    const form = useForm<TargetFields, unknown, z.output<typeof TargetSchema>>({
        resolver: zodResolver(TargetSchema), defaultValues: {...TargetSchema.parse({}),
            ...(initial ? {...initial, kind: initial.kind as z.output<typeof TargetSchema>['kind']} : {})},
    })
    const {register, formState: {errors, isSubmitting}} = form
    const submit = buildServerAwareSubmit(form, (values: z.output<typeof TargetSchema>) => {
        if (!initial && !values.api_key) throw new Error('An API token is required for a new connection.')
        return formRequest(initial ? `/integrations/${initial.id}` : '/integrations', initial ? 'PUT' : 'POST', {
            ...values, api_key: values.api_key || undefined,
        })
    }, {successStatuses: [200, 201], onSuccess: result => {onCreated(result as Target); setExpanded(false)}})
    if (!expanded) return <button type="button" className="btn" onClick={() => setExpanded(true)}>{initial ? 'Edit connection' : 'Connect media server'}</button>
    return <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 600}}>
        <label><input type="checkbox" {...register('enabled')}/> Enabled</label>
        <label>Server <select {...register('kind')}><option value="jellyfin">Jellyfin</option>
            <option value="plex">Plex</option><option value="audiobookshelf">Audiobookshelf podcast library</option></select></label>
        <label>Name <input {...register('name')} />{errors.name && <span role="alert">{errors.name.message}</span>}</label>
        <label>Server URL <input {...register('base_url')} placeholder="http://media-server:8096" />
            {errors.base_url && <span role="alert">{errors.base_url.message}</span>}</label>
        <label>Library ID <input {...register('library_id')} /></label>
        <label>VodLoft folder <input {...register('local_prefix')} /></label>
        <label>Server's view of that folder <input {...register('server_prefix')} /></label>
        <label>API token {initial && '(leave blank to keep the stored token)'} <input type="password" autoComplete="off" {...register('api_key')} /></label>
        {errors.root && <p role="alert">{errors.root.message}</p>}
        <div><button className="btn btn-primary" disabled={isSubmitting}>Save connection</button>{' '}
            <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const ConnectionSchema = z.object({source_id: z.string().min(1).default(''), name: z.string().min(1).default(''), enabled: z.boolean().default(true),
    configuration: z.record(z.string(), z.string()).default({})})
type ConnectionFields = z.input<typeof ConnectionSchema>

function RequestsView({me, items, onOpen}: {me: Me; items: Item[]; onOpen: (id: number) => Promise<void>}) {
    const [requests, setRequests] = useState<MediaRequest[]>([])
    const [error, setError] = useState<string | null>(null)
    const [reason, setReason] = useState('Request declined')
    const refresh = () => api<MediaRequest[]>('/requests').then(setRequests).catch(e => setError(String(e)))
    useEffect(() => {
        void refresh()
        const timer = window.setInterval(() => {if (!document.hidden) void refresh()}, 10000)
        return () => window.clearInterval(timer)
    }, [])
    const act = async (record: MediaRequest, action: 'approve' | 'reject' | 'withdraw') => {
        try {
            await api(`/requests/${record.id}${action === 'withdraw' ? '' : `/${action}`}`,
                {method: action === 'withdraw' ? 'DELETE' : 'POST',
                    body: action === 'reject' ? JSON.stringify({reason}) : undefined})
            await refresh()
        } catch (e) {setError(String(e))}
    }
    return <section><h3>{me.manages_library ? 'Media requests' : 'My requests'}</h3>
        {!requests.length && <p>No requests yet.</p>}
        {me.manages_library && requests.some(record => record.state === 'pending') &&
            <label>Decline reason <input value={reason} onChange={event => setReason(event.target.value)} maxLength={1000}/></label>}
        {requests.map(record => <div key={record.id} style={{marginBottom: 10}}>
            <button type="button" className="btn" onClick={() => void onOpen(record.item_id)}>
                {items.find(item => item.id === record.item_id)?.title ?? `Media ${record.item_id}`}</button>
            {' '}· {record.state}{record.reason && ` · ${record.reason}`}{' '}
            {me.manages_library && record.state === 'pending' && <>
                <button type="button" className="btn" onClick={() => void act(record, 'approve')}>Approve</button>{' '}
                <button type="button" className="btn" disabled={!reason.trim()} onClick={() => void act(record, 'reject')}>Decline</button>{' '}
            </>}
            {!['canceled', 'rejected'].includes(record.state) && <button type="button" className="btn" onClick={() => void act(record, 'withdraw')}>Withdraw demand</button>}
        </div>)}
        {error && <p role="alert">{error}</p>}
    </section>
}

type LocalAccount = {key: string; username: string; role: 'member' | 'manager'; enabled: boolean;
    can_subscribe: boolean; auto_approve: boolean; request_quota: number; connection_ids: number[]; target_ids: number[]}
const AccountSchema = z.object({username: z.string().regex(/^[a-z0-9][a-z0-9_.-]{0,79}$/).default(''),
    password: z.string().default('').refine(value => !value || value.length >= 7, 'Use at least seven characters'), enabled: z.boolean().default(true), role: z.enum(['member', 'manager']).default('member'),
    request_quota: z.number().int().min(1).max(10000).default(10),
    can_subscribe: z.boolean().default(true), auto_approve: z.boolean().default(false)})
type AccountFields = z.input<typeof AccountSchema>

function UsersManagement({connections, targets}: {connections: Connection[]; targets: Target[]}) {
    const [users, setUsers] = useState<LocalAccount[]>([])
    const [editing, setEditing] = useState<LocalAccount | null>(null)
    const [expanded, setExpanded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [connectionIds, setConnectionIds] = useState<number[]>([])
    const [targetIds, setTargetIds] = useState<number[]>([])
    const form = useForm<AccountFields, unknown, z.output<typeof AccountSchema>>({
        resolver: zodResolver(AccountSchema), defaultValues: AccountSchema.parse({})})
    useEffect(() => {void api<LocalAccount[]>('/users').then(setUsers).catch(e => setError(String(e)))}, [])
    const submit = buildServerAwareSubmit(form, async (values: z.output<typeof AccountSchema>) => {
        const {password, ...settings} = values
        if (!editing && !password) throw new Error('A password is required for a new local account.')
        return formRequest(editing ? `/users/${editing.key}` : '/users', editing ? 'PUT' : 'POST', {...settings, passwordHash: password ? await hashPasswordForAdminAuth(password) : undefined, connection_ids: connectionIds, target_ids: targetIds})
    }, {successStatuses: [200, 201], onSuccess: async result => {
        const updated = result as LocalAccount
        setUsers(current => editing ? current.map(value => value.key === updated.key ? updated : value) : [...current, updated]); setEditing(null); setExpanded(false); form.reset()
        setConnectionIds([]); setTargetIds([])
    }, fallbackField: 'username', fieldAlias: {passwordHash: 'password'}})
    return <section><h3>Local accounts</h3>
        {users.map(user => <p key={user.key}>{user.username} · {user.role} · {user.request_quota} open requests{' '}
            <button type="button" className="btn" onClick={() => void api<LocalAccount>(`/users/${user.key}`,
                {method: 'PUT', body: JSON.stringify({...user, enabled: !user.enabled})})
                .then(updated => setUsers(current => current.map(value => value.key === updated.key ? updated : value)))
                .catch(e => setError(String(e)))}>{user.enabled ? 'Disable account' : 'Enable account'}</button>{' '}
            <button type="button" className="btn" onClick={() => {setEditing(user); form.reset({...user, password: ''}); setConnectionIds(user.connection_ids); setTargetIds(user.target_ids); setExpanded(true)}}>Edit account</button></p>)}
        {!expanded ? <button type="button" className="btn" onClick={() => {setEditing(null); form.reset(); setConnectionIds([]); setTargetIds([]); setExpanded(true)}}>Add local account</button> :
            <form onSubmit={submit} style={{display: 'grid', maxWidth: 560, gap: 10}}>
                <label>Username <input {...form.register('username')} autoComplete="off"/></label>
                <label>Password {editing && '(leave blank to keep it)'} <input type="password" {...form.register('password')} autoComplete="new-password"/></label>
                <label><input type="checkbox" {...form.register('enabled')}/> Enabled</label>
                <label>Role <select {...form.register('role')}><option value="member">Member</option><option value="manager">Library manager</option></select></label>
                <label>Open request quota <input type="number" {...form.register('request_quota', {valueAsNumber: true})} min={1} max={10000}/></label>
                <label><input type="checkbox" {...form.register('auto_approve')}/> Automatically approve requests</label>
                <label><input type="checkbox" {...form.register('can_subscribe')}/> Allow feed subscriptions</label>
                <fieldset><legend>Upstream account access</legend>{connections.map(connection => <label key={connection.id} style={{display: 'block'}}>
                    <input type="checkbox" checked={connectionIds.includes(connection.id)} onChange={event => setConnectionIds(current => event.target.checked ? [...current, connection.id] : current.filter(id => id !== connection.id))}/>
                    {connection.name}</label>)}</fieldset>
                <fieldset><legend>Media-server access</legend>{targets.map(target => <label key={target.id} style={{display: 'block'}}>
                    <input type="checkbox" checked={targetIds.includes(target.id)} onChange={event => setTargetIds(current => event.target.checked ? [...current, target.id] : current.filter(id => id !== target.id))}/>
                    {target.name}</label>)}</fieldset>
                {Object.entries(form.formState.errors).map(([key, value]) => <p role="alert" key={key}>{String(value?.message ?? 'Check the form fields')}</p>)}
                <div><button className="btn btn-primary" disabled={form.formState.isSubmitting}>Save account</button>{' '}
                    <button type="button" className="btn" onClick={() => setExpanded(false)}>Cancel</button></div>
            </form>}
        {error && <p role="alert">{error}</p>}
    </section>
}

type AuthenticationState = {status: string; interval: number;
    challenge?: {message: string; verification_url?: string; user_code?: string; expires_at?: string} | null}

function ConnectionAuthentication({connection, onUpdated}: {connection: Connection; onUpdated: () => void}) {
    const [state, setState] = useState<AuthenticationState>({status: connection.authentication_status ?? 'expired', interval: 5})
    const [error, setError] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)
    useEffect(() => {
        if (state.status !== 'pending') return
        const timer = window.setTimeout(() => {
            void api<AuthenticationState>(`/sources/connections/${connection.id}/authentication`)
                .then(next => {setState(next); if (next.status !== 'pending') onUpdated()})
                .catch(e => {setError(String(e)); setState(current => ({...current}))})
        }, Math.max(1, state.interval) * 1000)
        return () => window.clearTimeout(timer)
    }, [state, connection.id])
    return <div style={{marginTop: 8}}>
        {state.status === 'pending' ? <>
            <p>{state.challenge?.message ?? 'Waiting for authorization…'}{' '}
                {state.challenge?.verification_url && <a href={state.challenge.verification_url} target="_blank" rel="noreferrer">Open authorization page</a>}
                {state.challenge?.user_code && <> · Code: <strong>{state.challenge.user_code}</strong></>}
            </p>
        </> : <span>{state.status === 'authorized' ? 'Account authorized. ' : state.status === 'denied' ? 'Authorization declined. ' : ''}</span>}
        <button type="button" className="btn" disabled={busy} onClick={() => {
            setBusy(true); setError(null)
            void api<AuthenticationState>(`/sources/connections/${connection.id}/authenticate`, {method: 'POST'})
                .then(setState).catch(e => setError(String(e))).finally(() => setBusy(false))
        }}>{state.status === 'pending' ? 'Restart authorization' : 'Authorize account'}</button>{' '}
        {(state.status === 'pending' || state.status === 'authorized') && <button type="button" className="btn" disabled={busy} onClick={() => {
            setBusy(true)
            void api(`/sources/connections/${connection.id}/authentication`, {method: 'DELETE'})
                .then(() => {setState({status: 'expired', interval: 5}); onUpdated()})
                .catch(e => setError(String(e))).finally(() => setBusy(false))
        }}>{state.status === 'pending' ? 'Cancel' : 'Sign out'}</button>}
        {error && <p role="alert">{error}</p>}
    </div>
}

function ConnectionForm({sources, initial, onCreated}: {sources: Source[]; initial?: Connection; onCreated: (connection: Connection) => void}) {
    const [expanded, setExpanded] = useState(false)
    const [fileSecrets, setFileSecrets] = useState<Record<string, string>>({})
    const [removeFields, setRemoveFields] = useState<string[]>([])
    const [readingFile, setReadingFile] = useState(false)
    const form = useForm<ConnectionFields, unknown, z.output<typeof ConnectionSchema>>({
        resolver: zodResolver(ConnectionSchema), defaultValues: {...ConnectionSchema.parse({}),
            ...(initial ? {source_id: initial.source_id, name: initial.name, enabled: initial.enabled,
                configuration: Object.fromEntries(Object.entries(initial.settings).map(([key, value]) => [key, String(value)]))} : {})},
    })
    const {register, watch, formState: {errors, isSubmitting}} = form
    const selected = sources.find(source => source.source_id === watch('source_id'))
    const submit = buildServerAwareSubmit(form, (values: z.output<typeof ConnectionSchema>) => {
        const settings: Record<string, string | number> = {}
        const secrets: Record<string, string> = {}
        for (const field of selected?.configuration_schema ?? []) {
            const value = field.kind === 'credential_file' ? fileSecrets[field.name] ?? '' : values.configuration[field.name]?.trim() ?? ''
            const kept = initial?.secret_fields.includes(field.name) && !removeFields.includes(field.name)
            if (field.required && !value && !kept) throw new Error(`${field.label} is required.`)
            if (!value) continue
            if (field.kind === 'secret' || field.kind === 'credential_file') secrets[field.name] = value
            else if (field.kind === 'number') {
                const number = Number(value)
                if (!Number.isFinite(number)) throw new Error(`${field.label} must be a number.`)
                settings[field.name] = number
            } else settings[field.name] = value
        }
        return formRequest(initial ? `/sources/connections/${initial.id}` : '/sources/connections', initial ? 'PUT' : 'POST', {
            source_id: values.source_id, name: values.name, enabled: values.enabled, settings, secrets,
            remove_secret_fields: removeFields,
        })
    }, {successStatuses: [200, 201], onSuccess: result => {onCreated(result as Connection); setExpanded(false); setFileSecrets({}); setRemoveFields([])}, fieldAlias: {settings: 'configuration', secrets: 'configuration'}})
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>{initial ? 'Edit account' : 'Add Source connection'}</button>
    return <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 560, margin: '12px 0'}}>
        {initial ? <p>{initial.source_id}</p> : <label>Source <select {...register('source_id')}><option value="">Select Source</option>
            {sources.map(source => <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}</select></label>}
        <label>Name <input {...register('name')}/></label>
        <label><input type="checkbox" {...register('enabled')}/> Enabled</label>
        {selected?.configuration_schema.map(field => <div key={field.name}><label>{field.label}
            {field.kind === 'credential_file' ? <input type="file" accept=".txt,text/plain" disabled={removeFields.includes(field.name)}
                onChange={event => {
                    const file = event.target.files?.[0]
                    if (!file) {setFileSecrets(current => ({...current, [field.name]: ''})); return}
                    if (file.size > 1024 * 1024) {form.setError('root', {message: 'Credential files must be at most 1 MiB.'}); return}
                    setReadingFile(true)
                    void file.text().then(content => setFileSecrets(current => ({...current, [field.name]: content})))
                        .catch(() => form.setError('root', {message: 'Could not read the credential file.'})).finally(() => setReadingFile(false))
                }}/> : field.kind === 'select' ? <select {...register(`configuration.${field.name}`)}><option value="">Choose an option</option>
                {field.options.map(option => <option key={option}>{option}</option>)}</select> :
                <input type={field.kind === 'secret' ? 'password' : field.kind === 'number' ? 'number' : 'text'}
                    autoComplete="off" disabled={removeFields.includes(field.name)} {...register(`configuration.${field.name}`)}/>}
        </label>{initial?.secret_fields.includes(field.name) && <label style={{display: 'block'}}>
            <input type="checkbox" checked={removeFields.includes(field.name)} onChange={event => {
                setRemoveFields(current => event.target.checked ? [...current, field.name] : current.filter(key => key !== field.name))
                form.setValue(`configuration.${field.name}`, ''); setFileSecrets(current => ({...current, [field.name]: ''}))
            }}/> Remove stored credential (leave the field blank to keep it)</label>}</div>)}
        {Object.entries(errors).map(([key, value]) => <p role="alert" key={key}>{String(value?.message ?? 'Check the configuration fields')}</p>)}
        <div><button className="btn btn-primary" disabled={isSubmitting || readingFile}>Save connection</button>{' '}
            <button className="btn" type="button" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}

const MetadataSchema = z.object({title: z.string().max(500).default(''), description: z.string().max(10000).default(''),
    kind: z.enum(['collection', 'video', 'movie', 'movie_extra']).default('video'), parent_ids: z.array(z.string().min(1)).max(100).default([]),
    extra_type: z.enum(['trailer', 'interview', 'behind_the_scenes', 'deleted_scene', 'featurette', 'other']).default('other')}).superRefine((values, ctx) => {
    if (values.kind === 'movie_extra' && !values.parent_ids.length) ctx.addIssue({code: 'custom', path: ['parent_ids'], message: 'Choose at least one parent Movie'})
})
type MetadataFields = z.input<typeof MetadataSchema>

function MetadataForm({item, items, onSaved}: {item: Item; items: Item[]; onSaved: (updated: Item) => void}) {
    const [expanded, setExpanded] = useState(false)
    const form = useForm<MetadataFields, unknown, z.output<typeof MetadataSchema>>({resolver: zodResolver(MetadataSchema),
        defaultValues: {...MetadataSchema.parse({}), title: item.title, description: item.description ?? '', kind: item.kind as z.output<typeof MetadataSchema>['kind'], parent_ids: (item.parent_ids ?? (item.parent_id ? [item.parent_id] : [])).map(String), extra_type: (item.extra_type ?? 'other') as z.output<typeof MetadataSchema>['extra_type']}})
    const {register, watch, formState: {errors, isSubmitting, dirtyFields}} = form
    const submit = buildServerAwareSubmit(form, (values: z.output<typeof MetadataSchema>) => formRequest(`/library/${item.id}/metadata`, 'PUT', {
        title: values.title || null, description: values.description || null,
        kind: item.kind === 'collection' ? undefined : values.kind,
        parent_ids: values.kind === 'movie_extra' && (dirtyFields.parent_ids || dirtyFields.kind) ? values.parent_ids.map(Number) : undefined,
        extra_type: values.kind === 'movie_extra' && (dirtyFields.extra_type || dirtyFields.kind) ? values.extra_type : undefined,
    }), {onSuccess: result => {onSaved(result as Item); setExpanded(false)}})
    if (!expanded) return <button className="btn" type="button" onClick={() => setExpanded(true)}>Edit library metadata</button>
    return <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 640, marginBottom: 16}}>
        <label>Display title <input {...register('title')}/></label>
        <label>Description <textarea {...register('description')} rows={4}/></label>
        {item.kind !== 'collection' && <label>Classification <select {...register('kind')}><option value="video">Video</option><option value="movie">Movie</option><option value="movie_extra">Movie Extra</option></select></label>}
        {watch('kind') === 'movie_extra' && <><fieldset><legend>Parent Movies</legend>
            {items.filter(candidate => candidate.kind === 'movie' && candidate.id !== item.id).map(movie => <label key={movie.id} style={{display: 'block'}}>
                <input type="checkbox" value={String(movie.id)} {...register('parent_ids')}/> {movie.title}</label>)}
            <small>A shared extra can belong to more than one Movie.</small></fieldset>
            <label>Extra type <select {...register('extra_type')}>{['trailer', 'interview', 'behind_the_scenes', 'deleted_scene', 'featurette', 'other'].map(kind => <option key={kind} value={kind}>{kind.replace(/_/g, ' ')}</option>)}</select></label></>}
        <p>Clear the title or description to restore the latest Source value.</p>
        {Object.entries(errors).map(([key, value]) => <p role="alert" key={key}>{String(value?.message ?? 'Check the fields')}</p>)}
        <div><button className="btn btn-primary" disabled={isSubmitting}>Save metadata</button>{' '}
            <button className="btn" type="button" onClick={() => setExpanded(false)}>Cancel</button></div>
    </form>
}


type ListeningMapping = {id: number; target_id: number; user_key: string; remote_user_id: string}
const ListeningSchema = z.object({target_id: z.string().min(1).default(''), user_key: z.string().min(1).default('admin'),
    remote_user_id: z.string().min(1).max(120).default(''), api_key: z.string().min(1).max(16384).default('')})
function ListeningAccounts({me, targets}: {me: Me; targets: Target[]}) {
    const [expanded, setExpanded] = useState(false)
    const [users, setUsers] = useState<LocalAccount[]>([])
    const [mappings, setMappings] = useState<ListeningMapping[]>([])
    const form = useForm<z.input<typeof ListeningSchema>, unknown, z.output<typeof ListeningSchema>>({resolver: zodResolver(ListeningSchema),
        defaultValues: {...ListeningSchema.parse({}), user_key: me.key}})
    const targetId = form.watch('target_id')
    const refresh = () => targetId ? api<ListeningMapping[]>(`/integrations/${targetId}/users`).then(setMappings).catch(error => form.setError('root', {message: String(error)})) : Promise.resolve()
    useEffect(() => {if (me.role === 'admin') void api<LocalAccount[]>('/users').then(setUsers)}, [me.role])
    useEffect(() => {setMappings([]); void refresh()}, [targetId])
    const submit = buildServerAwareSubmit(form, values => formRequest(`/integrations/${values.target_id}/users`, 'PUT', {
        user_key: me.role === 'admin' ? values.user_key : me.key, remote_user_id: values.remote_user_id, api_key: values.api_key,
    }), {onSuccess: () => {form.setValue('api_key', ''); void refresh()}})
    const servers = targets.filter(target => target.kind === 'audiobookshelf' && target.enabled)
    if (!servers.length) return null
    return <section><h3>Listening account mappings</h3>
        <p>Progress import uses an explicitly linked Audiobookshelf account. Imports only advance your VodLoft position.</p>
        <button className="btn" type="button" onClick={() => setExpanded(value => !value)}>{expanded ? 'Close mappings' : 'Link listening account'}</button>
        {expanded && <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 580, margin: '12px 0'}}>
            <label>Server <select {...form.register('target_id')}><option value="">Select server</option>{servers.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}</select></label>
            {me.role === 'admin' && <label>Local account <select {...form.register('user_key')}><option value="admin">Administrator</option>{users.map(user => <option key={user.key} value={user.key}>{user.username}</option>)}</select></label>}
            <label>Audiobookshelf user ID <input {...form.register('remote_user_id')}/></label>
            <label>That user's API token <input type="password" autoComplete="off" {...form.register('api_key')}/></label>
            {Object.entries(form.formState.errors).map(([key, value]) => <p role="alert" key={key}>{String(value?.message ?? 'Check the fields')}</p>)}
            <button className="btn btn-primary" disabled={form.formState.isSubmitting}>Verify and save mapping</button>
            {mappings.map(mapping => <div key={mapping.id}>{mapping.user_key === me.key ? me.username : users.find(user => user.key === mapping.user_key)?.username ?? mapping.user_key} → {mapping.remote_user_id}{' '}
                <button className="btn" type="button" onClick={() => void api(`/integrations/${targetId}/users/${mapping.user_key}`, {method: 'DELETE'}).then(refresh).catch(error => form.setError('root', {message: String(error)}))}>Unlink</button></div>)}
        </form>}
    </section>
}

const RSSDeliverySchema = z.object({target_id: z.string().min(1).default(''), stream_profile_id: z.string().min(1).default(''),
    folder_id: z.string().min(1).max(120).default(''), server_path: z.string().startsWith('/').default('/podcasts/'),
    vodloft_url: z.url().default('')})
function RSSDeliveryForm({targets, profiles}: {targets: Target[]; profiles: StreamProfile[]}) {
    const [expanded, setExpanded] = useState(false)
    const [saved, setSaved] = useState(false)
    const form = useForm<z.input<typeof RSSDeliverySchema>, unknown, z.output<typeof RSSDeliverySchema>>({resolver: zodResolver(RSSDeliverySchema),
        defaultValues: {...RSSDeliverySchema.parse({}), vodloft_url: window.location.origin}})
    const submit = buildServerAwareSubmit(form, values => formRequest('/integrations/rss', 'POST', {
        ...values, target_id: Number(values.target_id), stream_profile_id: Number(values.stream_profile_id),
    }), {successStatuses: [201], onSuccess: () => {setSaved(true); setExpanded(false)}})
    const servers = targets.filter(target => target.kind === 'audiobookshelf' && target.enabled)
    const feeds = profiles.filter(profile => profile.enabled && profile.format === 'audio')
    if (!servers.length || !feeds.length) return null
    return <div style={{margin: '12px 0'}}>
        <button className="btn" type="button" onClick={() => setExpanded(value => !value)}>Deliver a feed to Audiobookshelf</button>
        {saved && <p role="status">RSS delivery queued. Review its status in Management.</p>}
        {expanded && <form onSubmit={submit} style={{display: 'grid', gap: 10, maxWidth: 600}}>
            <p>VodLoft owns the published feed files. Audiobookshelf downloads its own copies every 15 minutes and owns their retention. Removing this delivery revokes the feed and retains Audiobookshelf's downloaded copies.</p>
            <label>Server <select {...form.register('target_id')}><option value="">Select server</option>{servers.map(target => <option key={target.id} value={target.id}>{target.name}</option>)}</select></label>
            <label>Audio Stream Profile <select {...form.register('stream_profile_id')}><option value="">Select feed</option>{feeds.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
            <label>Audiobookshelf library folder ID <input {...form.register('folder_id')}/></label>
            <label>Podcast folder on that server <input {...form.register('server_path')}/></label>
            <label>VodLoft address reachable by that server <input {...form.register('vodloft_url')}/></label>
            {Object.entries(form.formState.errors).map(([key, value]) => <p role="alert" key={key}>{String(value?.message ?? 'Check the fields')}</p>)}
            <button className="btn btn-primary" disabled={form.formState.isSubmitting}>Save RSS delivery</button>
        </form>}
    </div>
}

type FeedDelivery = {id: number; target_id: number; server_path: string; state: string; error: string | null; remote_id: string | null}
function RSSDeliveries({targets}: {targets: Target[]}) {
    const [records, setRecords] = useState<FeedDelivery[]>([])
    const [error, setError] = useState<string | null>(null)
    const refresh = () => api<FeedDelivery[]>('/integrations/rss').then(setRecords).catch(error => setError(String(error)))
    useEffect(() => {void refresh(); const timer = window.setInterval(() => {if (!document.hidden) void refresh()}, 15000); return () => window.clearInterval(timer)}, [])
    return <section><h3>Audiobookshelf RSS deliveries</h3>{!records.length && <p>Set up an audio Stream Profile on a Collection to deliver without shared storage.</p>}
        {records.map(record => <p key={record.id}>{targets.find(target => target.id === record.target_id)?.name} · {record.server_path} · {record.state} {record.error}{' '}
            {record.remote_id && <a href={`${targets.find(target => target.id === record.target_id)?.base_url}/item/${encodeURIComponent(record.remote_id)}`} target="_blank" rel="noreferrer">Open podcast</a>}{' '}
            <button className="btn" type="button" onClick={() => void api(`/integrations/rss/${record.id}/retry`, {method: 'POST'}).then(refresh).catch(error => setError(String(error)))}>Refresh delivery</button>{' '}
            <button className="btn" type="button" onClick={() => {if (window.confirm('Revoke this feed delivery? Audiobookshelf keeps its downloaded copies.')) void api(`/integrations/rss/${record.id}`, {method: 'DELETE'}).then(refresh).catch(error => setError(String(error)))}}>Revoke delivery</button></p>)}
        {error && <p role="alert">{error}</p>}
    </section>
}
