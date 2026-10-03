import {useEffect, useMemo, useState} from 'react'
import CodeMirror from '@uiw/react-codemirror'
import {jinja} from '@codemirror/lang-jinja'
import {autocompletion} from '@codemirror/autocomplete'
import {Controller, useWatch, type UseFormReturn} from 'react-hook-form'
import {parseOutputTemplate, renderCompactOutputTemplate, renderEditorOutputTemplate} from './outputTemplateFormatting'
import './OutputTemplateEditor.css'
import './OutputTemplateEditorIde.css'

const variables = {domain: 'Canonical website hostname', title: 'Effective library title', id: 'Stable VodLoft media ID',
    upstream_id: 'Upstream identity', media_type: 'Video, Movie or Movie Extra', collection: 'Collection display title',
    group: 'Season or group', episode_number: 'Collection episode number', published_date: 'Publication date',
    author: 'Creator or author', duration: 'Duration in seconds', movie_year: 'Movie release year'}

export default function DomainTemplateEditor({form, domain}: {form: UseFormReturn<any, any, any>; domain: string}) {
    const template = useWatch({control: form.control, name: 'output_template'}) as string
    const format = useWatch({control: form.control, name: 'preferred_format'}) as string
    const container = useWatch({control: form.control, name: 'container'}) as string
    const [kind, setKind] = useState('video')
    const [search, setSearch] = useState('')
    const [examples, setExamples] = useState<{id: number; label: string}[]>([])
    const [example, setExample] = useState<number | null>(null)
    const [preview, setPreview] = useState<{path: string; values: Record<string, unknown>} | null>(null)
    const [error, setError] = useState<string | null>(null)
    const base = `${(window as any).appConfig?.API_URL || '/api'}/vodloft/profiles`
    useEffect(() => {
        const controller = new AbortController()
        const timer = window.setTimeout(() => {
            const query = new URLSearchParams({domain, kind, search})
            void fetch(`${base}/template-sources?${query}`, {credentials: 'include', signal: controller.signal})
                .then(r => r.json()).then(setExamples).catch(() => {})
        }, 250)
        return () => {window.clearTimeout(timer); controller.abort()}
    }, [domain, kind, search])
    useEffect(() => {
        const controller = new AbortController()
        const timer = window.setTimeout(() => {
            const extension = container && container !== 'source' ? container : format === 'format_audio_only' ? 'mp3' : 'mp4'
            void fetch(`${base}/template-preview`, {method: 'POST', credentials: 'include', signal: controller.signal,
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({domain, kind, template,
                    item_id: example, extension})}).then(async response => {
                    const data = await response.json()
                    if (!response.ok) throw new Error(data.detail ?? 'Template is invalid')
                    setPreview(data); setError(null)
                }).catch(error => {if (error.name !== 'AbortError') {setError(String(error)); setPreview(null)}})
        }, 350)
        return () => {window.clearTimeout(timer); controller.abort()}
    }, [domain, kind, template, example, format, container])
    const extensions = useMemo(() => [jinja(), autocompletion({override: [context => {
        const word = context.matchBefore(/[a-zA-Z_]*/)
        if (!word || word.from === word.to && !context.explicit) return null
        return {from: word.from, options: Object.entries(variables).map(([label, detail]) => ({label, detail, type: 'variable'}))}
    }]})], [])
    return <fieldset className="output-template-editor"><legend>Output template</legend>
        <Controller name="output_template" control={form.control} render={({field}) =>
            <CodeMirror value={renderEditorOutputTemplate(parseOutputTemplate(field.value ?? '', 'compact')).value} extensions={extensions}
                minHeight="130px" theme="dark" onBlur={field.onBlur}
                onChange={value => field.onChange(renderCompactOutputTemplate(parseOutputTemplate(value, 'editor')))}
                aria-label="Output path template"/>}/>
        <p>Use <code>{'{{ title }}'}</code> and conditions to organize files. The final path must stay inside your library folder.</p>
        <details><summary>Template variables</summary><dl>{Object.entries(variables).map(([key, value]) =>
            <div key={key}><dt><code>{key}</code></dt><dd>{value}</dd></div>)}</dl></details>
        <label>Example media type <select value={kind} onChange={e => {setKind(e.target.value); setExample(null)}}>
            <option value="video">Video</option><option value="movie">Movie</option><option value="movie_extra">Movie Extra</option>
        </select></label>
        <label>Find an example <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search ${domain} media`}/></label>
        <label>Example <select value={example ?? ''} onChange={e => setExample(Number(e.target.value) || null)}>
            <option value="">Sample values</option>{examples.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select></label>
        {preview && <p aria-live="polite">Preview: <code>{preview.path}</code></p>}
        {error && <p role="alert">{error}</p>}
        {form.formState.errors.output_template && <p role="alert">{String(form.formState.errors.output_template.message)}</p>}
    </fieldset>
}
