import {useEffect, useRef, useState} from 'react'
import {useForm} from 'react-hook-form'
import {zodResolver} from '@hookform/resolvers/zod'
import {z} from 'zod'
import {buildServerAwareSubmit} from '../../utils/buildServerAwareSubmit'
import {vodloftApi as api} from '../../lib/vodloftApi'
import ProgressButton from '../common/ProgressButton'
import {frontendOperationDefinitions as operations} from '../../lib/operationDefinitions'
import './Discovery.css'

export type DiscoveryReference = {source_id: string; domain: string; namespace: string; upstream_id: string; url: string}
type Result = {reference: DiscoveryReference; kind: string; title: string; description?: string | null}
type Policy = {scopeKey?: string; effective_capabilities: string[]; capability_reasons: Record<string, string>}
type Domain = {id: number; hostname: string; display_name: string;
    sources: (Policy & {source_id: string; display_name: string; support: string; aliases: string[]})[]}
type DomainPage = {items: Domain[]; next_cursor: string | null; exhaustive: boolean}
type BrowsePage = {items: Result[]; next_cursor: string | null; categories?: {id: string; title: string; description?: string}[]}
const FilterSchema = z.object({query: z.string().max(200).default('')})
const ScopeSchema = z.object({source_id: z.string().default(''), connection_id: z.string().default(''), category_id: z.string().default('')})
const SearchSchema = z.object({query: z.string().trim().min(1).max(200).default('')})

export default function DomainBrowser({connections, onPreview, onAddURL, busy = false}: {
    busy?: boolean;
    connections: {id: number; source_id: string; name: string; enabled: boolean}[];
    onPreview: (reference: DiscoveryReference, connectionId: number | null) => Promise<void>;
    onAddURL: (sourceId: string, connectionId: number | null) => void;
}) {
    const filter = useForm<z.input<typeof FilterSchema>, unknown, z.output<typeof FilterSchema>>({
        resolver: zodResolver(FilterSchema), defaultValues: FilterSchema.parse({})})
    const scope = useForm<z.input<typeof ScopeSchema>, unknown, z.output<typeof ScopeSchema>>({
        resolver: zodResolver(ScopeSchema), defaultValues: ScopeSchema.parse({})})
    const search = useForm<z.input<typeof SearchSchema>, unknown, z.output<typeof SearchSchema>>({
        resolver: zodResolver(SearchSchema), defaultValues: SearchSchema.parse({})})
    const [domains, setDomains] = useState<DomainPage | null>(null)
    const [domainQuery, setDomainQuery] = useState('')
    const [domain, setDomain] = useState<Domain | null>(null)
    const [savedPolicy, setPolicy] = useState<Policy | null>(null)
    const [page, setPage] = useState<BrowsePage | null>(null)
    const [categories, setCategories] = useState<NonNullable<BrowsePage['categories']>>([])
    const [mode, setMode] = useState<'browse' | 'search'>('browse')
    const [searchQuery, setSearchQuery] = useState('')
    const [loading, setLoading] = useState(false)
    const [previewing, setPreviewing] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const abort = useRef<AbortController | null>(null)
    const domainAbort = useRef<AbortController | null>(null)
    const sourceId = scope.watch('source_id') || ''
    const connectionId = Number(scope.watch('connection_id')) || null
    const categoryId = scope.watch('category_id') || ''
    const scopeKey = `${domain?.hostname}:${sourceId}:${connectionId}`
    const policy = savedPolicy?.scopeKey === scopeKey ? savedPolicy : null

    const loadDomains = async (query: string, cursor?: string) => {
        domainAbort.current?.abort()
        const controller = new AbortController(); domainAbort.current = controller
        const params = new URLSearchParams({query, limit: '30'})
        if (cursor) params.set('cursor', cursor)
        try {
            const result = await api<DomainPage>(`/discover/domains?${params}`, {signal: controller.signal})
            if (controller.signal.aborted) return
            setDomains(previous => cursor && previous ? {...result, items: [...previous.items, ...result.items]} : result)
            setDomainQuery(query)
        } catch (e) { if (!controller.signal.aborted) setError(String(e)) }
    }
    useEffect(() => { void loadDomains(''); return () => {domainAbort.current?.abort(); abort.current?.abort()} }, [])
    const filterSubmit = filter.handleSubmit(values => {setError(null); void loadDomains(values.query)})

    const loadResults = async (operation: 'browse' | 'search', query = '', cursor?: string) => {
        if (!domain || !sourceId) return
        abort.current?.abort()
        const controller = new AbortController(); abort.current = controller
        setLoading(true); setError(null)
        try {
            let result: BrowsePage
            if (operation === 'browse') {
                result = await api<BrowsePage>(`/sources/${encodeURIComponent(sourceId)}/browse`, {method: 'POST',
                    signal: controller.signal, body: JSON.stringify({domain: domain.hostname,
                        category_id: categoryId || null, connection_id: connectionId, cursor: cursor || null, limit: 30})})
            } else {
                const params = new URLSearchParams({query, domain: domain.hostname, limit: '30'})
                if (connectionId) params.set('connection_id', String(connectionId))
                if (cursor) params.set('cursor', cursor)
                result = await api<BrowsePage>(`/sources/${encodeURIComponent(sourceId)}/search?${params}`, {signal: controller.signal})
            }
            if (controller.signal.aborted) return
            setMode(operation); setSearchQuery(query)
            if (result.categories) setCategories(result.categories)
            setPage(previous => cursor && previous ? {...result, items: [...previous.items, ...result.items]} : result)
        } catch (e) { if (!controller.signal.aborted) setError(String(e)) }
        finally { if (!controller.signal.aborted) setLoading(false) }
    }
    useEffect(() => {
        abort.current?.abort(); setPolicy(null); setPage(null); setCategories([]); setError(null)
        if (!domain || !sourceId) return
        const controller = new AbortController(); abort.current = controller
        setLoading(true)
        const params = new URLSearchParams({domain: domain.hostname})
        if (connectionId) params.set('connection_id', String(connectionId))
        void api<Policy>(`/sources/${encodeURIComponent(sourceId)}/capabilities?${params}`, {signal: controller.signal})
            .then(result => {
                if (controller.signal.aborted) return
                setPolicy({...result, scopeKey})
                if (result.effective_capabilities.includes('browse')) void loadResults('browse')
                else setLoading(false)
            }).catch(e => {if (!controller.signal.aborted) {setError(String(e)); setLoading(false)}})
        return () => controller.abort()
    }, [domain?.hostname, sourceId, connectionId])
    useEffect(() => {
        if (policy?.effective_capabilities.includes('browse')) void loadResults('browse')
        return () => abort.current?.abort()
    }, [categoryId])
    const searchSubmit = buildServerAwareSubmit(search, async values => {
        await loadResults('search', values.query)
    })
    const selectedSource = domain?.sources.find(source => source.source_id === sourceId)
    const chooseDomain = (next: Domain) => {
        abort.current?.abort(); setLoading(false); setDomain(next)
        scope.reset({...ScopeSchema.parse({}), source_id: next.sources[0]?.source_id || ''})
        search.reset(SearchSchema.parse({}))
    }
    return <section className="vodloft-discovery" aria-label="Browse Domains">
        <h2>Browse Domains</h2>
        <p>Choose a website to see the browsing and search tools its Sources provide. Any supported public URL can also be added above.</p>
        <form className="vodloft-fields" onSubmit={filterSubmit}>
            <label>Find a Domain <input {...filter.register('query')} placeholder="Website name or hostname"/></label>
            <button className="btn" type="submit">Find Domains</button>
            {filter.formState.errors.query && <p role="alert">{filter.formState.errors.query.message}</p>}
        </form>
        <div className="vodloft-domain-grid">
            {domains?.items.map(value => <button className={`btn ${domain?.id === value.id ? 'is-selected' : ''}`}
                type="button" disabled={busy || previewing} key={value.id} aria-pressed={domain?.id === value.id} onClick={() => chooseDomain(value)}>
                <strong>{value.display_name}</strong><span>{value.hostname}</span>
                <small>{value.sources.map(source => source.display_name).join(', ')}</small>
            </button>)}
        </div>
        {domains?.items.length === 0 && <p>No advertised Domains match. Try Add URL.</p>}
        {domains?.next_cursor && <button type="button" className="btn" onClick={() => void loadDomains(domainQuery, domains.next_cursor!)}>More Domains</button>}
        {domains && !domains.exhaustive && <p>These catalogues cover only some supported websites.</p>}
        {domain && <section className="vodloft-domain-detail">
            <h3>{domain.display_name}</h3>
            <div className="vodloft-fields">
                <label>Source <select disabled={busy || previewing} {...scope.register('source_id', {onChange: () => {
                    scope.setValue('connection_id', ''); scope.setValue('category_id', '')
                }})}>{domain.sources.map(source => <option key={source.source_id} value={source.source_id}>{source.display_name}</option>)}</select></label>
                <label>Connection <select disabled={busy || previewing} {...scope.register('connection_id', {onChange: () => scope.setValue('category_id', '')})}><option value="">Anonymous</option>
                    {connections.filter(c => c.enabled && c.source_id === sourceId).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select></label>
                <button className="btn" type="button" disabled={busy || previewing} onClick={() => onAddURL(sourceId, connectionId)}>Add a URL with this Source</button>
            </div>
            <p>{domain.hostname} · {selectedSource?.display_name} · {selectedSource?.support.replace(/_/g, ' ')}</p>
            {policy && !policy.effective_capabilities.includes('browse') && <p>{policy.capability_reasons.browse}. Add a URL{policy.effective_capabilities.includes('search') ? ' or search this Domain' : ''}.</p>}
            {policy?.effective_capabilities.includes('browse') && <div className="vodloft-fields">
                {categories.length > 0 && <label>Category <select {...scope.register('category_id')}><option value="">Default</option>
                    {categories.map(category => <option key={category.id} value={category.id}>{category.title}</option>)}</select></label>}
                <ProgressButton definition={operations.vodloft_source_browse} label="Browse" active={loading && mode === 'browse'}
                    disabled={loading} onClick={() => void loadResults('browse')}/>
            </div>}
            {policy?.effective_capabilities.includes('search') && <form className="vodloft-fields" onSubmit={searchSubmit}>
                <label>Search this Domain <input {...search.register('query')}/></label>
                <button className="btn" type="submit" disabled={loading}>Search</button>
                {search.formState.errors.query && <p role="alert">{search.formState.errors.query.message}</p>}
            </form>}
            {loading && <p role="status">Working with {selectedSource?.display_name}…</p>}
            {page && <div className="vodloft-result-grid">
                {page.items.map((item, index) => <button className="btn" type="button" disabled={previewing || loading || busy}
                    key={`${item.reference.namespace}:${item.reference.upstream_id}:${index}`} onClick={() => {
                        setPreviewing(true)
                        void onPreview(item.reference, connectionId).finally(() => setPreviewing(false))
                    }}><strong>{item.title}</strong><span>{item.kind} · {item.reference.domain} · {item.reference.source_id}</span>
                    {item.description && <small>{item.description.slice(0, 180)}</small>}</button>)}
                {page.items.length === 0 && <p>No results for these filters.</p>}
                {page.next_cursor && <button type="button" className="btn" disabled={loading}
                    onClick={() => void loadResults(mode, searchQuery, page.next_cursor!)}>More results</button>}
            </div>}
            {previewing && <p role="status">Resolving preview…</p>}
        </section>}
        {error && <p role="alert">{error}</p>}
    </section>
}
