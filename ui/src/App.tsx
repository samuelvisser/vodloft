import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {FormEvent, useMemo, useState} from 'react'
import {api, type DownloadProfileInput, type LocalMediaProfileInput, type StreamProfileInput} from './api'
import type {
  AuthStatus, Collection, DownloadProfile, LocalMediaProfile, MediaDownload, StreamProfile, TaskDefinition, TaskRun, Video,
} from './schemas'

type LibraryTab = 'channels' | 'playlists' | 'videos'
type AppView = 'library' | 'downloads' | 'profiles' | 'tasks' | 'settings'

const TERMINAL_TASKS = new Set(['succeeded', 'failed', 'canceled'])

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function bytes(value: number | null): string {
  if (value == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

function LoginPanel({auth}: {auth: AuthStatus}) {
  const queryClient = useQueryClient()
  const login = useMutation({
    mutationFn: ({username, password}: {username: string; password: string}) => api.login(username, password),
    onSuccess: data => queryClient.setQueryData(['auth-status'], data),
  })
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    login.mutate({username: String(form.get('username')), password: String(form.get('password'))})
  }
  return <main className="login-shell">
    <form className="panel login-panel" onSubmit={submit}>
      <h1>VodLoft</h1>
      <p>Sign in to manage your media library.</p>
      {login.error && <p className="error">{errorMessage(login.error)}</p>}
      <label>Username<input name="username" defaultValue={auth.username} autoComplete="username" required/></label>
      <label>Password<input name="password" type="password" autoComplete="current-password" required/></label>
      <button type="submit" disabled={login.isPending}>{login.isPending ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
}

function VideoActions({
  video,
  localProfiles,
  streamProfiles,
  onDownload,
  onPlay,
}: {
  video: Video
  localProfiles: LocalMediaProfile[]
  streamProfiles: StreamProfile[]
  onDownload: (videoId: number, profileId: number) => void
  onPlay: (videoId: number, profileId: number) => void
}) {
  const [selectedLocalId, setSelectedLocalId] = useState<number | null>(null)
  const [selectedStreamId, setSelectedStreamId] = useState<number | null>(null)
  const localId = selectedLocalId ?? localProfiles[0]?.id ?? null
  const streamId = selectedStreamId ?? streamProfiles[0]?.id ?? null
  const artifact = localId == null ? undefined : video.media_downloads.find(item => item.local_media_profile_id === localId)
  const pending = artifact?.status === 'downloading' || artifact?.status === 'queued'

  return <div className="video-actions">
    {localProfiles.length > 0 ? <>
      <select value={localId ?? ''} onChange={event => setSelectedLocalId(Number(event.target.value))}>
        {localProfiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </select>
      <button onClick={() => localId != null && onDownload(video.id, localId)} disabled={pending}>
        {artifact?.status === 'downloaded' ? 'Redownload' : pending ? 'Queued' : 'Download'}
      </button>
      {artifact && <span className={`status status-${artifact.status}`}>
        {artifact.status}{artifact.format_downloaded ? ` · ${artifact.format_downloaded}` : ''}{artifact.downloaded_bytes ? ` · ${bytes(artifact.downloaded_bytes)}` : ''}
      </span>}
    </> : <span className="muted">No compatible local media profile</span>}

    {streamProfiles.length > 0 && <>
      <select value={streamId ?? ''} onChange={event => setSelectedStreamId(Number(event.target.value))}>
        {streamProfiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </select>
      <button className="secondary" onClick={() => streamId != null && onPlay(video.id, streamId)}>Play</button>
    </>}
  </div>
}

function LocalProfileFields({profile}: {profile?: LocalMediaProfile}) {
  return <>
    <label>Name<input name="name" required defaultValue={profile?.name ?? ''} placeholder="High quality video"/></label>
    <label>Scope<select name="scope" defaultValue={profile?.scope ?? 'collection'}><option value="collection">Channel / playlist</option><option value="video">Standalone video</option></select></label>
    <label>Media<select name="media_kind" defaultValue={profile?.media_kind ?? 'video'}><option value="video">Video</option><option value="audio">Audio</option></select></label>
    <label className="wide">Output template<input name="output_template" required defaultValue={profile?.output_template ?? '/downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s'}/></label>
    <label className="wide">yt-dlp format selector<input name="preferred_format" required defaultValue={profile?.preferred_format ?? 'bestvideo*+bestaudio/best'}/></label>
    <label>Merge format<input name="merge_output_format" defaultValue={profile?.merge_output_format ?? ''} placeholder="mkv"/></label>
    <label>Audio conversion<input name="audio_format" defaultValue={profile?.audio_format ?? ''} placeholder="mp3"/></label>
    <label className="checkbox"><input type="checkbox" name="write_subtitles" defaultChecked={profile?.write_subtitles ?? false}/> Write subtitles</label>
    <label className="checkbox"><input type="checkbox" name="embed_metadata" defaultChecked={profile?.embed_metadata ?? true}/> Embed metadata</label>
    <label className="checkbox"><input type="checkbox" name="embed_thumbnail" defaultChecked={profile?.embed_thumbnail ?? false}/> Embed thumbnail</label>
  </>
}

function localPayload(form: FormData): LocalMediaProfileInput {
  return {
    name: String(form.get('name')),
    scope: String(form.get('scope')) as 'collection' | 'video',
    media_kind: String(form.get('media_kind')) as 'video' | 'audio',
    output_template: String(form.get('output_template')),
    preferred_format: String(form.get('preferred_format')),
    merge_output_format: String(form.get('merge_output_format') || '') || null,
    audio_format: String(form.get('audio_format') || '') || null,
    write_subtitles: form.get('write_subtitles') === 'on',
    embed_metadata: form.get('embed_metadata') === 'on',
    embed_thumbnail: form.get('embed_thumbnail') === 'on',
  }
}

function ProfilesPanel({
  collections, localProfiles, downloadProfiles, streamProfiles, invalidate,
}: {
  collections: Collection[]
  localProfiles: LocalMediaProfile[]
  downloadProfiles: DownloadProfile[]
  streamProfiles: StreamProfile[]
  invalidate: () => Promise<unknown>
}) {
  const [editingLocal, setEditingLocal] = useState<number | null>(null)
  const [editingDownload, setEditingDownload] = useState<number | null>(null)
  const [editingStream, setEditingStream] = useState<number | null>(null)
  const [templatePreview, setTemplatePreview] = useState<string | null>(null)
  const collectionLocalProfiles = localProfiles.filter(profile => profile.scope === 'collection')
  const collectionName = (id: number) => collections.find(item => item.id === id)?.title ?? `Collection ${id}`
  const localName = (id: number) => localProfiles.find(item => item.id === id)?.name ?? `Profile ${id}`

  const createLocal = useMutation({mutationFn: api.createLocalProfile, onSuccess: invalidate})
  const updateLocal = useMutation({mutationFn: ({id, payload}: {id: number; payload: LocalMediaProfileInput}) => api.updateLocalProfile(id, payload), onSuccess: async () => {setEditingLocal(null); await invalidate()}})
  const deleteLocal = useMutation({mutationFn: api.deleteLocalProfile, onSuccess: invalidate})
  const createDownload = useMutation({mutationFn: api.createDownloadProfile, onSuccess: invalidate})
  const updateDownload = useMutation({mutationFn: ({id, payload}: {id: number; payload: Omit<DownloadProfileInput, 'collection_id'>}) => api.updateDownloadProfile(id, payload), onSuccess: async () => {setEditingDownload(null); await invalidate()}})
  const deleteDownload = useMutation({mutationFn: api.deleteDownloadProfile, onSuccess: invalidate})
  const createStream = useMutation({mutationFn: api.createStreamProfile, onSuccess: invalidate})
  const updateStream = useMutation({mutationFn: ({id, payload}: {id: number; payload: Omit<StreamProfileInput, 'collection_id'>}) => api.updateStreamProfile(id, payload), onSuccess: async () => {setEditingStream(null); await invalidate()}})
  const deleteStream = useMutation({mutationFn: api.deleteStreamProfile, onSuccess: invalidate})
  const preview = useMutation({mutationFn: api.previewOutputTemplate, onSuccess: result => setTemplatePreview(result.valid ? (result.example_output ?? result.normalized_template ?? 'Valid') : (result.error ?? 'Invalid template'))})
  const mutationError = createLocal.error ?? updateLocal.error ?? deleteLocal.error ?? createDownload.error ?? updateDownload.error ?? deleteDownload.error ?? createStream.error ?? updateStream.error ?? deleteStream.error ?? preview.error

  const submitLocalCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    createLocal.mutate(localPayload(new FormData(event.currentTarget)))
    event.currentTarget.reset()
  }
  const submitDownloadCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createDownload.mutate({name: String(form.get('name')), collection_id: Number(form.get('collection_id')), local_media_profile_id: Number(form.get('local_media_profile_id')), enable_profile: form.get('enable_profile') === 'on'})
    event.currentTarget.reset()
  }
  const submitStreamCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createStream.mutate({name: String(form.get('name')), collection_id: Number(form.get('collection_id')), enable_profile: form.get('enable_profile') === 'on', use_downloads: form.get('use_downloads') === 'on', format_selector: String(form.get('format_selector'))})
    event.currentTarget.reset()
  }

  return <div className="profiles-page">
    {mutationError && <p className="error panel">{errorMessage(mutationError)}</p>}
    <section className="panel">
      <div className="section-heading"><div><h2>Local media profiles</h2><p>Defines the path, yt-dlp format selection and post-processing. VodLoft automatically appends the video ID when a template would otherwise allow title collisions.</p></div></div>
      <form className="profile-form" onSubmit={submitLocalCreate}>
        <LocalProfileFields/>
        <button type="submit">Add local profile</button>
      </form>
      <div className="inline-tools">
        <input id="template-preview" placeholder="/downloads/%(uploader)s/%(title)s.%(ext)s"/>
        <button className="secondary" onClick={() => {
          const input = document.getElementById('template-preview') as HTMLInputElement | null
          if (input?.value) preview.mutate(input.value)
        }}>Preview template</button>
        {templatePreview && <code>{templatePreview}</code>}
      </div>
      <div className="profile-list">
        {localProfiles.map(profile => <div className="profile-row-wrap" key={profile.id}>
          <div className="profile-row">
            <div><strong>{profile.name}</strong><span>{profile.scope} · {profile.media_kind} · {profile.preferred_format}</span></div>
            <div className="row-actions"><button className="secondary" onClick={() => setEditingLocal(editingLocal === profile.id ? null : profile.id)}>{editingLocal === profile.id ? 'Close' : 'Edit'}</button><button className="danger" onClick={() => deleteLocal.mutate(profile.id)}>Delete</button></div>
          </div>
          {editingLocal === profile.id && <form className="profile-form edit-form" onSubmit={event => {event.preventDefault(); updateLocal.mutate({id: profile.id, payload: localPayload(new FormData(event.currentTarget))})}}>
            <LocalProfileFields profile={profile}/>
            <button type="submit">Save changes</button>
          </form>}
        </div>)}
      </div>
    </section>

    <section className="panel">
      <h2>Download profiles</h2><p>Collection-scoped automation. Sync events plan any missing downloads using enabled profiles.</p>
      <form className="profile-form" onSubmit={submitDownloadCreate}>
        <label>Name<input name="name" required placeholder="Main archive"/></label>
        <label>Channel / playlist<select name="collection_id" required>{collections.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label>Local media profile<select name="local_media_profile_id" required>{collectionLocalProfiles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="checkbox"><input type="checkbox" name="enable_profile" defaultChecked/> Enabled</label>
        <button type="submit" disabled={!collections.length || !collectionLocalProfiles.length}>Add download profile</button>
      </form>
      <div className="profile-list">
        {downloadProfiles.map(profile => <div className="profile-row-wrap" key={profile.id}>
          <div className="profile-row"><div><strong>{profile.name}</strong><span>{collectionName(profile.collection_id)} · {localName(profile.local_media_profile_id)} · {profile.enable_profile ? 'enabled' : 'disabled'}</span></div><div className="row-actions"><button className="secondary" onClick={() => setEditingDownload(editingDownload === profile.id ? null : profile.id)}>{editingDownload === profile.id ? 'Close' : 'Edit'}</button><button className="danger" onClick={() => deleteDownload.mutate(profile.id)}>Delete</button></div></div>
          {editingDownload === profile.id && <form className="profile-form edit-form" onSubmit={event => {event.preventDefault(); const form = new FormData(event.currentTarget); updateDownload.mutate({id: profile.id, payload: {name: String(form.get('name')), local_media_profile_id: Number(form.get('local_media_profile_id')), enable_profile: form.get('enable_profile') === 'on'}})}}>
            <label>Name<input name="name" required defaultValue={profile.name}/></label>
            <label>Local media profile<select name="local_media_profile_id" defaultValue={profile.local_media_profile_id}>{collectionLocalProfiles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label className="checkbox"><input type="checkbox" name="enable_profile" defaultChecked={profile.enable_profile}/> Enabled</label>
            <button type="submit">Save changes</button>
          </form>}
        </div>)}
      </div>
    </section>

    <section className="panel">
      <h2>Stream profiles</h2><p>Collection-scoped streaming policy. Prefer local downloads or resolve a fresh direct stream through yt-dlp.</p>
      <form className="profile-form" onSubmit={submitStreamCreate}>
        <label>Name<input name="name" required placeholder="Browser compatible"/></label>
        <label>Channel / playlist<select name="collection_id" required>{collections.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label className="wide">yt-dlp format selector<input name="format_selector" required defaultValue="best[protocol^=http][vcodec!=none][acodec!=none]/best"/></label>
        <label className="checkbox"><input type="checkbox" name="enable_profile" defaultChecked/> Enabled</label>
        <label className="checkbox"><input type="checkbox" name="use_downloads"/> Prefer local downloads</label>
        <button type="submit" disabled={!collections.length}>Add stream profile</button>
      </form>
      <div className="profile-list">
        {streamProfiles.map(profile => <div className="profile-row-wrap" key={profile.id}>
          <div className="profile-row"><div><strong>{profile.name}</strong><span>{collectionName(profile.collection_id)} · {profile.use_downloads ? 'local first' : 'yt-dlp stream'} · {profile.enable_profile ? 'enabled' : 'disabled'}</span></div><div className="row-actions"><button className="secondary" onClick={() => setEditingStream(editingStream === profile.id ? null : profile.id)}>{editingStream === profile.id ? 'Close' : 'Edit'}</button><button className="danger" onClick={() => deleteStream.mutate(profile.id)}>Delete</button></div></div>
          {editingStream === profile.id && <form className="profile-form edit-form" onSubmit={event => {event.preventDefault(); const form = new FormData(event.currentTarget); updateStream.mutate({id: profile.id, payload: {name: String(form.get('name')), enable_profile: form.get('enable_profile') === 'on', use_downloads: form.get('use_downloads') === 'on', format_selector: String(form.get('format_selector'))}})}}>
            <label>Name<input name="name" required defaultValue={profile.name}/></label>
            <label className="wide">yt-dlp format selector<input name="format_selector" required defaultValue={profile.format_selector}/></label>
            <label className="checkbox"><input type="checkbox" name="enable_profile" defaultChecked={profile.enable_profile}/> Enabled</label>
            <label className="checkbox"><input type="checkbox" name="use_downloads" defaultChecked={profile.use_downloads}/> Prefer local downloads</label>
            <button type="submit">Save changes</button>
          </form>}
        </div>)}
      </div>
    </section>
  </div>
}

function TaskProgress({run}: {run: TaskRun}) {
  return <div className="task-progress"><progress max={100} value={run.progress}/><span>{run.progress}%</span></div>
}

function TasksPanel() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const ledger = useQuery({queryKey: ['task-ledger', page], queryFn: () => api.taskLedger(page, 50), refetchInterval: 2000})
  const definitions = useQuery({queryKey: ['task-definitions'], queryFn: api.taskDefinitions})
  const schedules = useQuery({queryKey: ['task-schedules'], queryFn: api.taskSchedules, refetchInterval: 5000})
  const operations = useQuery({queryKey: ['task-operations'], queryFn: api.taskOperations, refetchInterval: 3000})
  const refresh = async () => Promise.all([
    queryClient.invalidateQueries({queryKey: ['task-ledger']}),
    queryClient.invalidateQueries({queryKey: ['task-schedules']}),
    queryClient.invalidateQueries({queryKey: ['task-operations']}),
  ])
  const cancel = useMutation({mutationFn: api.cancelTask, onSuccess: refresh})
  const createSchedule = useMutation({mutationFn: api.createTaskSchedule, onSuccess: refresh})
  const updateSchedule = useMutation({mutationFn: ({id, active}: {id: number; active: boolean}) => api.updateTaskSchedule(id, {active}), onSuccess: refresh})
  const deleteSchedule = useMutation({mutationFn: api.deleteTaskSchedule, onSuccess: refresh})
  const [scheduleTaskKey, setScheduleTaskKey] = useState('')
  const selectedDefinition = definitions.data?.find(item => item.key === scheduleTaskKey) ?? definitions.data?.[0]

  const submitSchedule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const taskKey = String(form.get('task_key'))
    const definition = definitions.data?.find(item => item.key === taskKey)
    const triggerType = String(form.get('trigger_type')) as 'cron' | 'interval'
    createSchedule.mutate({
      task_key: taskKey,
      name: String(form.get('name')),
      resource_type: String(form.get('resource_type') || definition?.allowed_resource_types[0] || 'system'),
      resource_id: Number(form.get('resource_id') || 0),
      trigger_type: triggerType,
      cron: triggerType === 'cron' ? String(form.get('cron')) : null,
      interval_minutes: triggerType === 'interval' ? Number(form.get('interval_minutes')) : null,
      active: true,
      coalesce: true,
    })
    event.currentTarget.reset()
  }
  const mutationError = cancel.error ?? createSchedule.error ?? updateSchedule.error ?? deleteSchedule.error

  return <div className="tasks-page">
    {mutationError && <p className="error panel">{errorMessage(mutationError)}</p>}
    <section className="panel">
      <div className="section-heading"><div><h2>Task ledger</h2><p>Durable task history survives application restarts and records retries, cancellation and progress.</p></div><span className="badge">{ledger.data?.total ?? 0} runs</span></div>
      <div className="table-scroll"><table className="ledger-table"><thead><tr><th>Task</th><th>Resource</th><th>Status</th><th>Progress</th><th>Attempts</th><th>Started</th><th></th></tr></thead><tbody>
        {ledger.data?.items.map(run => <tr key={run.id}><td><strong>{run.task_title}</strong><small>#{run.id} · {run.source}</small>{run.last_error && <small className="error">{run.last_error}</small>}</td><td>{run.resource_type}:{run.resource_id}</td><td><span className={`status status-${run.status}`}>{run.status}</span></td><td><TaskProgress run={run}/></td><td>{run.attempt_count}/{run.max_retries + 1}</td><td>{formatDate(run.started_at ?? run.queued_at)}</td><td>{!TERMINAL_TASKS.has(run.status) && <button className="danger compact" onClick={() => cancel.mutate(run.id)}>Cancel</button>}</td></tr>)}
      </tbody></table></div>
      <div className="pager"><button className="secondary" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {ledger.data?.page ?? page} of {ledger.data?.pages ?? 1}</span><button className="secondary" disabled={page >= (ledger.data?.pages ?? 1)} onClick={() => setPage(value => value + 1)}>Next</button></div>
    </section>

    <section className="panel">
      <h2>Schedules</h2><p>Decorator-defined schedules are read-only here. User schedules are stored in the database and restored on startup.</p>
      <form className="profile-form" onSubmit={submitSchedule}>
        <label>Task<select name="task_key" required value={scheduleTaskKey || selectedDefinition?.key || ''} onChange={event => setScheduleTaskKey(event.target.value)}>{definitions.data?.map(item => <option key={item.key} value={item.key}>{item.title}</option>)}</select></label>
        <label>Name<input name="name" required placeholder="Nightly sync"/></label>
        <label>Resource type<select name="resource_type" key={selectedDefinition?.key}>{selectedDefinition?.allowed_resource_types.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <label>Resource ID<input name="resource_id" type="number" min="0" defaultValue="0"/></label>
        <label>Trigger<select name="trigger_type" defaultValue="cron"><option value="cron">Cron</option><option value="interval">Interval</option></select></label>
        <label>Cron<input name="cron" defaultValue="0 3 * * *"/></label>
        <label>Interval minutes<input name="interval_minutes" type="number" min="1" defaultValue="60"/></label>
        <button type="submit" disabled={!definitions.data?.length}>Add schedule</button>
      </form>
      <div className="schedule-list">{schedules.data?.map(schedule => <div className="profile-row" key={schedule.id}><div><strong>{schedule.name}</strong><span>{schedule.task_title} · {schedule.trigger_type} {JSON.stringify(schedule.trigger_args)} · next {formatDate(schedule.next_run_time)}</span>{schedule.last_error && <span className="error">{schedule.last_error}</span>}</div><div className="row-actions"><span className="badge">{schedule.source}</span>{schedule.source !== 'registry' && <><button className="secondary" onClick={() => updateSchedule.mutate({id: schedule.id, active: !schedule.active})}>{schedule.active ? 'Disable' : 'Enable'}</button><button className="danger" onClick={() => deleteSchedule.mutate(schedule.id)}>Delete</button></>}</div></div>)}</div>
    </section>

    <section className="panel">
      <h2>Operations</h2><p>Grouped work such as a collection sync planning multiple downloads is tracked as one operation.</p>
      <div className="operation-grid">{operations.data?.slice(0, 20).map(operation => <div className="operation-card" key={operation.id}><strong>{operation.title}</strong><span className={`status status-${operation.status}`}>{operation.status}</span><p>{operation.completed_tasks}/{operation.total_tasks} completed · {operation.failed_tasks} failed · {operation.canceled_tasks} canceled</p></div>)}</div>
    </section>
  </div>
}

function DownloadsPanel() {
  const queryClient = useQueryClient()
  const downloads = useQuery({queryKey: ['media-downloads'], queryFn: api.mediaDownloads, refetchInterval: 1500})
  const videos = useQuery({queryKey: ['all-videos'], queryFn: api.allVideos})
  const profiles = useQuery({queryKey: ['local-profiles'], queryFn: () => api.localProfiles()})
  const tasks = useQuery({queryKey: ['tasks'], queryFn: api.tasks, refetchInterval: 1500})
  const [filter, setFilter] = useState('all')
  const refresh = async () => Promise.all([
    queryClient.invalidateQueries({queryKey: ['media-downloads']}),
    queryClient.invalidateQueries({queryKey: ['tasks']}),
    queryClient.invalidateQueries({queryKey: ['task-ledger']}),
    queryClient.invalidateQueries({queryKey: ['collections']}),
    queryClient.invalidateQueries({queryKey: ['videos']}),
  ])
  const retry = useMutation({mutationFn: api.retryMediaDownload, onSuccess: refresh})
  const cancel = useMutation({mutationFn: api.cancelMediaDownload, onSuccess: refresh})
  const prioritize = useMutation({mutationFn: api.prioritizeMediaDownload, onSuccess: refresh})
  const remove = useMutation({mutationFn: api.deleteMediaDownload, onSuccess: refresh})
  const mutationError = retry.error ?? cancel.error ?? prioritize.error ?? remove.error
  const taskById = new Map((tasks.data ?? []).map(run => [run.id, run]))
  const videoById = new Map((videos.data ?? []).map(video => [video.id, video]))
  const profileById = new Map((profiles.data ?? []).map(profile => [profile.id, profile]))
  const rows = (downloads.data ?? []).filter(item => filter === 'all' || item.status === filter)
  const statuses = Array.from(new Set((downloads.data ?? []).map(item => item.status))).sort()

  const actions = (item: MediaDownload) => {
    const run = item.task_run_id == null ? undefined : taskById.get(item.task_run_id)
    const isQueued = run?.status === 'queued' || item.status === 'queued'
    const isActive = (run != null && !TERMINAL_TASKS.has(run.status)) || item.status === 'queued' || item.status === 'downloading'
    return <div className="row-actions download-actions">
      {isQueued && <button className="secondary compact" onClick={() => prioritize.mutate(item.id)}>Prioritize</button>}
      {isActive && <button className="danger compact" onClick={() => cancel.mutate(item.id)}>Cancel</button>}
      {!isActive && ['failed', 'cancelled', 'missing'].includes(item.status) && <button className="secondary compact" onClick={() => retry.mutate(item.id)}>Retry</button>}
      {item.status === 'downloaded' && <button className="secondary compact" onClick={() => window.open(`/api/media-downloads/${item.id}/file`, '_blank', 'noopener,noreferrer')}>Open</button>}
      {!isActive && <button className="danger compact" onClick={() => remove.mutate(item.id)}>Delete</button>}
    </div>
  }

  return <div className="downloads-page">
    {mutationError && <p className="error panel">{errorMessage(mutationError)}</p>}
    <section className="panel">
      <div className="section-heading"><div><h2>Downloads</h2><p>The persistent media ledger. Queued downloads can be prioritized; failed, canceled or missing media can be retried without recreating profiles.</p></div><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All statuses</option>{statuses.map(status => <option key={status} value={status}>{status}</option>)}</select></div>
      <div className="table-scroll"><table className="ledger-table downloads-table"><thead><tr><th>Media</th><th>Profile</th><th>Status</th><th>Progress</th><th>Size / format</th><th>Updated</th><th></th></tr></thead><tbody>
        {rows.map(item => {
          const video = videoById.get(item.video_id)
          const profile = profileById.get(item.local_media_profile_id)
          const run = item.task_run_id == null ? undefined : taskById.get(item.task_run_id)
          return <tr key={item.id}><td><strong>{video?.title ?? `Video ${item.video_id}`}</strong><small>Artifact #{item.id}{item.file_path ? ` · ${item.file_path}` : ''}</small>{item.error && <small className="error">{item.error}</small>}</td><td>{profile?.name ?? `Profile ${item.local_media_profile_id}`}</td><td><span className={`status status-${item.status}`}>{item.status}</span></td><td>{run ? <TaskProgress run={run}/> : '—'}</td><td>{bytes(item.downloaded_bytes)}{item.format_downloaded ? ` · ${item.format_downloaded}` : ''}</td><td>{formatDate(item.updated_at)}</td><td>{actions(item)}</td></tr>
        })}
      </tbody></table></div>
      {!rows.length && <p className="muted empty-state">No downloads match this filter.</p>}
    </section>
  </div>
}

function SettingsPanel({collections, auth}: {collections: Collection[]; auth: AuthStatus}) {
  const queryClient = useQueryClient()
  const settings = useQuery({queryKey: ['settings'], queryFn: api.settings})
  const invalidate = async () => Promise.all([queryClient.invalidateQueries({queryKey: ['settings']}), queryClient.invalidateQueries({queryKey: ['auth-status']})])
  const update = useMutation({mutationFn: api.updateSettings, onSuccess: invalidate})
  const rotate = useMutation({mutationFn: api.rotateRssToken, onSuccess: invalidate})
  const updateRuntime = useMutation({mutationFn: api.updateRuntimeSettings, onSuccess: invalidate})
  const setup = useMutation({mutationFn: ({username, password}: {username: string; password: string}) => api.authSetup(username, password), onSuccess: async data => {queryClient.setQueryData(['auth-status'], data); await invalidate()}})
  const password = useMutation({mutationFn: ({current, next}: {current: string | null; next: string}) => api.changePassword(current, next), onSuccess: invalidate})
  const mutationError = update.error ?? updateRuntime.error ?? rotate.error ?? setup.error ?? password.error
  const data = settings.data

  const submitGeneral = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    update.mutate({admin_username: String(form.get('admin_username')), rss_item_limit: Number(form.get('rss_item_limit')), auth_enabled: form.get('auth_enabled') === 'on', onboarding_completed: true})
  }
  const submitRuntime = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    let ytDlpOptions: Record<string, unknown>
    try {
      ytDlpOptions = JSON.parse(String(form.get('yt_dlp_options') || '{}')) as Record<string, unknown>
    } catch {
      window.alert('yt-dlp options must be valid JSON')
      return
    }
    updateRuntime.mutate({
      worker_threads: Number(form.get('worker_threads')),
      scheduler_enabled: form.get('scheduler_enabled') === 'on',
      collection_sync_interval_minutes: Number(form.get('collection_sync_interval_minutes')),
      verification_interval_minutes: Number(form.get('verification_interval_minutes')),
      default_max_retries: Number(form.get('default_max_retries')),
      retry_backoff_base_seconds: Number(form.get('retry_backoff_base_seconds')),
      retry_backoff_max_seconds: Number(form.get('retry_backoff_max_seconds')),
      stalled_timeout_minutes: Number(form.get('stalled_timeout_minutes')),
      download_max_concurrency: Number(form.get('download_max_concurrency')),
      yt_dlp_options: ytDlpOptions,
    })
  }
  const submitSetup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setup.mutate({username: String(form.get('username')), password: String(form.get('password'))})
  }
  const submitPassword = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    password.mutate({current: String(form.get('current_password') || '') || null, next: String(form.get('new_password'))})
    event.currentTarget.reset()
  }
  const rssBase = typeof window === 'undefined' ? '' : window.location.origin

  return <div className="settings-page">
    {mutationError && <p className="error panel">{errorMessage(mutationError)}</p>}
    <section className="panel"><h2>Application</h2>{data ? <>
      <form className="settings-form" onSubmit={submitGeneral}>
        <label>Administrator username<input name="admin_username" defaultValue={data.admin_username}/></label>
        <label>RSS item limit<input name="rss_item_limit" type="number" min="0" max="10000" defaultValue={data.rss_item_limit}/></label>
        <label className="checkbox"><input name="auth_enabled" type="checkbox" defaultChecked={data.auth_enabled} disabled={auth.setup_required}/> Require sign-in for admin API</label>
        <button type="submit">Save settings</button>
      </form>
      <div className="settings-grid"><div><span>Database revision</span><strong>{data.alembic_version_num ?? 'unknown'}</strong></div><div><span>Workers</span><strong>{data.worker_threads}</strong></div><div><span>Download concurrency</span><strong>{data.download_max_concurrency}</strong></div><div><span>Retry policy</span><strong>{data.default_max_retries} retries, {data.retry_backoff_base_seconds}–{data.retry_backoff_max_seconds}s backoff</strong></div><div><span>Stalled timeout</span><strong>{data.stalled_timeout_minutes} min without progress</strong></div><div><span>Collection sync</span><strong>{data.scheduler_enabled ? `every ${data.collection_sync_interval_minutes} min` : 'disabled'}</strong></div><div><span>Download verification</span><strong>{data.scheduler_enabled ? `every ${data.verification_interval_minutes} min` : 'disabled'}</strong></div></div>
    </> : <p>Loading…</p>}</section>

    <section className="panel"><h2>Runtime configuration</h2>{data ? <><p>These values are written to <code>config.yml</code>. yt-dlp options and retry/stall policy are read dynamically; worker-pool size, download concurrency, and decorator-backed schedule intervals take full effect after restarting VodLoft.</p><form className="settings-form runtime-form" onSubmit={submitRuntime}><label>Worker threads<input name="worker_threads" type="number" min="1" max="32" defaultValue={data.worker_threads}/></label><label>Download concurrency<input name="download_max_concurrency" type="number" min="1" max="32" defaultValue={data.download_max_concurrency}/></label><label>Collection sync (minutes)<input name="collection_sync_interval_minutes" type="number" min="1" defaultValue={data.collection_sync_interval_minutes}/></label><label>Verification (minutes)<input name="verification_interval_minutes" type="number" min="5" defaultValue={data.verification_interval_minutes}/></label><label>Default retries<input name="default_max_retries" type="number" min="0" max="20" defaultValue={data.default_max_retries}/></label><label>Backoff base (seconds)<input name="retry_backoff_base_seconds" type="number" min="1" defaultValue={data.retry_backoff_base_seconds}/></label><label>Backoff maximum (seconds)<input name="retry_backoff_max_seconds" type="number" min="1" defaultValue={data.retry_backoff_max_seconds}/></label><label>Stalled timeout (minutes)<input name="stalled_timeout_minutes" type="number" min="5" defaultValue={data.stalled_timeout_minutes}/></label><label className="checkbox"><input name="scheduler_enabled" type="checkbox" defaultChecked={data.scheduler_enabled}/> Scheduled maintenance enabled</label><label className="wide-json">yt-dlp options (JSON)<textarea name="yt_dlp_options" defaultValue={JSON.stringify(data.yt_dlp_options, null, 2)}/></label><button type="submit">Save runtime config</button></form></> : <p>Loading…</p>}</section>

    <section className="panel"><h2>Authentication</h2>{auth.setup_required ? <><p>Authentication is optional. Configure an administrator password before enabling it.</p><form className="settings-form" onSubmit={submitSetup}><label>Username<input name="username" defaultValue={data?.admin_username ?? 'admin'} required/></label><label>Password<input name="password" type="password" minLength={8} required/></label><button type="submit">Configure authentication</button></form></> : <><p>Change the administrator password. Authentication can be enabled or disabled above without removing the password.</p><form className="settings-form" onSubmit={submitPassword}><label>Current password<input name="current_password" type="password" required/></label><label>New password<input name="new_password" type="password" minLength={8} required/></label><button type="submit">Change password</button></form></>}</section>

    <section className="panel"><div className="section-heading"><div><h2>Private RSS feeds</h2><p>Feeds use a separate token and remain available when admin authentication is enabled.</p></div><button className="secondary" onClick={() => rotate.mutate()}>Rotate token</button></div>{data && <div className="rss-list"><label>Downloaded media feed<code>{rssBase}/api/rss/downloads.xml?token={data.rss_token}</code></label>{collections.map(collection => <label key={collection.id}>{collection.title}<code>{rssBase}/api/rss/collections/{collection.id}.xml?token={data.rss_token}</code></label>)}</div>}</section>
  </div>
}

function LibraryPanel({
  collections, standaloneVideos, localProfiles, downloadProfiles, streamProfiles, activeTasks, invalidate,
}: {
  collections: Collection[]
  standaloneVideos: Video[]
  localProfiles: LocalMediaProfile[]
  downloadProfiles: DownloadProfile[]
  streamProfiles: StreamProfile[]
  activeTasks: TaskRun[]
  invalidate: () => Promise<unknown>
}) {
  const [tab, setTab] = useState<LibraryTab>('channels')
  const [expandedCollection, setExpandedCollection] = useState<number | null>(null)
  const [url, setUrl] = useState('')
  const [kind, setKind] = useState<'auto' | 'channel' | 'playlist' | 'video'>('auto')
  const add = useMutation({mutationFn: async () => {if (kind === 'video') return api.addVideo(url); if (kind === 'channel' || kind === 'playlist') return api.addCollection(url, kind); const inspection = await api.inspect(url); return inspection.kind === 'video' ? api.addVideo(url) : api.addCollection(url, inspection.kind as 'channel' | 'playlist')}, onSuccess: async () => {setUrl(''); await invalidate()}})
  const sync = useMutation({mutationFn: api.syncCollection, onSuccess: invalidate})
  const download = useMutation({mutationFn: ({videoId, profileId}: {videoId: number; profileId: number}) => api.downloadVideo(videoId, profileId), onSuccess: invalidate})
  const deleteCollection = useMutation({mutationFn: api.deleteCollection, onSuccess: invalidate})
  const deleteVideo = useMutation({mutationFn: api.deleteVideo, onSuccess: invalidate})
  const visibleCollections = useMemo(() => collections.filter(item => item.kind === (tab === 'channels' ? 'channel' : 'playlist')), [collections, tab])
  const standaloneProfiles = localProfiles.filter(profile => profile.scope === 'video')
  const submit = (event: FormEvent) => {event.preventDefault(); if (url.trim()) add.mutate()}
  const play = async (videoId: number, profileId: number) => {try {const target = await api.resolveStream(videoId, profileId); window.open(target.url, '_blank', 'noopener,noreferrer')} catch (error) {window.alert(errorMessage(error))}}
  const renderVideo = (video: Video, locals: LocalMediaProfile[], streams: StreamProfile[]) => <article className="video-row" key={video.id}>{video.thumbnail_url && <img src={video.thumbnail_url} alt=""/>}<div className="video-copy"><h3>{video.title}</h3><p>{video.channel ?? video.uploader ?? video.extractor}</p></div><VideoActions video={video} localProfiles={locals} streamProfiles={streams} onDownload={(videoId, profileId) => download.mutate({videoId, profileId})} onPlay={play}/>{video.standalone && <button className="danger compact remove-video" onClick={() => deleteVideo.mutate(video.id)}>Remove</button>}</article>
  const error = add.error ?? sync.error ?? download.error ?? deleteCollection.error ?? deleteVideo.error

  return <>
    <section className="panel"><form className="add-form" onSubmit={submit}><input value={url} onChange={event => setUrl(event.target.value)} placeholder="Paste a URL supported by yt-dlp" required/><select value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="auto">Detect automatically</option><option value="channel">Channel</option><option value="playlist">Playlist</option><option value="video">Video</option></select><button type="submit" disabled={add.isPending}>{add.isPending ? 'Adding…' : 'Add'}</button></form>{error && <p className="error">{errorMessage(error)}</p>}</section>
    {activeTasks.length > 0 && <section className="panel"><h2>Active work</h2>{activeTasks.slice(0, 8).map(task => <div className="task" key={task.id}><strong>{task.task_title}</strong><TaskProgress run={task}/><span className={`status status-${task.status}`}>{task.status}</span></div>)}</section>}
    <div className="tabs"><button className={tab === 'channels' ? 'active' : ''} onClick={() => setTab('channels')}>Channels</button><button className={tab === 'playlists' ? 'active' : ''} onClick={() => setTab('playlists')}>Playlists</button><button className={tab === 'videos' ? 'active' : ''} onClick={() => setTab('videos')}>Videos</button></div>
    {tab === 'videos' ? <div className="video-list">{standaloneVideos.map(video => renderVideo(video, standaloneProfiles, streamProfiles.filter(profile => profile.collection_id == null)))}</div> : <div className="collection-list">{visibleCollections.map(collection => {
      const locals = localProfiles.filter(profile => profile.scope === 'collection' && downloadProfiles.some(downloadProfile => downloadProfile.collection_id === collection.id && downloadProfile.local_media_profile_id === profile.id))
      const streams = streamProfiles.filter(profile => profile.collection_id === collection.id && profile.enable_profile)
      return <section className="collection-card" key={collection.id}><div className="collection-summary">{collection.thumbnail_url && <img src={collection.thumbnail_url} alt=""/>}<div className="collection-copy"><span className="badge">{collection.kind}</span><h2>{collection.title}</h2><p>{collection.channel ?? collection.uploader ?? collection.extractor}</p><p>Last synchronized: {formatDate(collection.last_synced_at)}</p></div><div className="collection-actions"><button className="secondary" onClick={() => setExpandedCollection(expandedCollection === collection.id ? null : collection.id)}>{expandedCollection === collection.id ? 'Hide videos' : `${collection.videos.length} videos`}</button><button onClick={() => sync.mutate(collection.id)}>Sync now</button><button className="danger" onClick={() => deleteCollection.mutate(collection.id)}>Remove</button></div></div>{expandedCollection === collection.id && <div className="collection-videos">{collection.videos.map(video => renderVideo(video, locals, streams))}</div>}</section>
    })}</div>}
  </>
}

function AuthenticatedApp({auth}: {auth: AuthStatus}) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<AppView>('library')
  const collections = useQuery({queryKey: ['collections'], queryFn: api.collections, refetchInterval: 5000})
  const videos = useQuery({queryKey: ['videos'], queryFn: api.videos, refetchInterval: 5000})
  const localProfiles = useQuery({queryKey: ['local-profiles'], queryFn: () => api.localProfiles()})
  const downloadProfiles = useQuery({queryKey: ['download-profiles'], queryFn: () => api.downloadProfiles()})
  const streamProfiles = useQuery({queryKey: ['stream-profiles'], queryFn: () => api.streamProfiles()})
  const tasks = useQuery({queryKey: ['tasks'], queryFn: api.tasks, refetchInterval: 1500})
  const invalidateLibrary = async () => Promise.all([queryClient.invalidateQueries({queryKey: ['collections']}), queryClient.invalidateQueries({queryKey: ['videos']}), queryClient.invalidateQueries({queryKey: ['tasks']}), queryClient.invalidateQueries({queryKey: ['task-ledger']})])
  const invalidateProfiles = async () => Promise.all([queryClient.invalidateQueries({queryKey: ['local-profiles']}), queryClient.invalidateQueries({queryKey: ['download-profiles']}), queryClient.invalidateQueries({queryKey: ['stream-profiles']}), queryClient.invalidateQueries({queryKey: ['collections']}), queryClient.invalidateQueries({queryKey: ['tasks']})])
  const logout = useMutation({mutationFn: api.logout, onSuccess: async () => {await queryClient.invalidateQueries({queryKey: ['auth-status']})}})
  const activeTasks = tasks.data?.filter(task => !TERMINAL_TASKS.has(task.status)) ?? []

  return <div className="app"><header className="app-header"><div><h1>VodLoft</h1><p>yt-dlp powered media library</p></div><nav className="main-nav"><button className={view === 'library' ? 'active' : ''} onClick={() => setView('library')}>Library</button><button className={view === 'downloads' ? 'active' : ''} onClick={() => setView('downloads')}>Downloads</button><button className={view === 'profiles' ? 'active' : ''} onClick={() => setView('profiles')}>Profiles</button><button className={view === 'tasks' ? 'active' : ''} onClick={() => setView('tasks')}>Tasks</button><button className={view === 'settings' ? 'active' : ''} onClick={() => setView('settings')}>Settings</button>{auth.auth_enabled && <button onClick={() => logout.mutate()}>Sign out</button>}</nav></header>
    {view === 'library' && <LibraryPanel collections={collections.data ?? []} standaloneVideos={videos.data ?? []} localProfiles={localProfiles.data ?? []} downloadProfiles={downloadProfiles.data ?? []} streamProfiles={streamProfiles.data ?? []} activeTasks={activeTasks} invalidate={invalidateLibrary}/>} 
    {view === 'downloads' && <DownloadsPanel/>}
    {view === 'profiles' && <ProfilesPanel collections={collections.data ?? []} localProfiles={localProfiles.data ?? []} downloadProfiles={downloadProfiles.data ?? []} streamProfiles={streamProfiles.data ?? []} invalidate={invalidateProfiles}/>} 
    {view === 'tasks' && <TasksPanel/>}
    {view === 'settings' && <SettingsPanel collections={collections.data ?? []} auth={auth}/>} 
  </div>
}

export default function App() {
  const auth = useQuery({queryKey: ['auth-status'], queryFn: api.authStatus, retry: false})
  if (auth.isPending) return <main className="login-shell"><div className="panel login-panel"><h1>VodLoft</h1><p>Loading…</p></div></main>
  if (auth.error || !auth.data) return <main className="login-shell"><div className="panel login-panel"><h1>VodLoft</h1><p className="error">{errorMessage(auth.error ?? 'Unable to load authentication state')}</p></div></main>
  if (auth.data.auth_enabled && !auth.data.authenticated) return <LoginPanel auth={auth.data}/>
  return <AuthenticatedApp auth={auth.data}/>
}
