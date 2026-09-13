import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {FormEvent, useMemo, useState} from 'react'
import {api} from './api'
import type {Collection, DownloadProfile, LocalMediaProfile, StreamProfile, Video} from './schemas'

type LibraryTab = 'channels' | 'playlists' | 'videos'
type AppView = 'library' | 'profiles'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
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

  return <div className="video-actions">
    {localProfiles.length > 0 ? <>
      <select value={localId ?? ''} onChange={event => setSelectedLocalId(Number(event.target.value))}>
        {localProfiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </select>
      <button onClick={() => localId != null && onDownload(video.id, localId)}>
        {artifact?.status === 'downloaded' ? 'Redownload' : artifact?.status === 'downloading' || artifact?.status === 'queued' ? 'Queued' : 'Download'}
      </button>
      {artifact && <span className={`status status-${artifact.status}`}>{artifact.status}{artifact.format_downloaded ? ` · ${artifact.format_downloaded}` : ''}</span>}
    </> : <span className="muted">No compatible local media profile</span>}

    {streamProfiles.length > 0 && <>
      <select value={streamId ?? ''} onChange={event => setSelectedStreamId(Number(event.target.value))}>
        {streamProfiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </select>
      <button className="secondary" onClick={() => streamId != null && onPlay(video.id, streamId)}>Play</button>
    </>}
  </div>
}

function ProfilesPanel({
  collections,
  localProfiles,
  downloadProfiles,
  streamProfiles,
  createLocal,
  createDownload,
  createStream,
  deleteLocal,
  deleteDownload,
  deleteStream,
  mutationError,
}: {
  collections: Collection[]
  localProfiles: LocalMediaProfile[]
  downloadProfiles: DownloadProfile[]
  streamProfiles: StreamProfile[]
  createLocal: (payload: Parameters<typeof api.createLocalProfile>[0]) => void
  createDownload: (payload: Parameters<typeof api.createDownloadProfile>[0]) => void
  createStream: (payload: Parameters<typeof api.createStreamProfile>[0]) => void
  deleteLocal: (id: number) => void
  deleteDownload: (id: number) => void
  deleteStream: (id: number) => void
  mutationError: unknown
}) {
  const collectionLocalProfiles = localProfiles.filter(profile => profile.scope === 'collection')
  const collectionName = (id: number) => collections.find(item => item.id === id)?.title ?? `Collection ${id}`
  const localName = (id: number) => localProfiles.find(item => item.id === id)?.name ?? `Profile ${id}`

  const submitLocal = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const mediaKind = String(form.get('media_kind')) as 'video' | 'audio'
    createLocal({
      name: String(form.get('name')),
      scope: String(form.get('scope')) as 'collection' | 'video',
      media_kind: mediaKind,
      output_template: String(form.get('output_template')),
      preferred_format: String(form.get('preferred_format')),
      merge_output_format: String(form.get('merge_output_format') || '') || null,
      audio_format: String(form.get('audio_format') || '') || null,
      write_subtitles: form.get('write_subtitles') === 'on',
      embed_metadata: form.get('embed_metadata') === 'on',
      embed_thumbnail: form.get('embed_thumbnail') === 'on',
    })
    event.currentTarget.reset()
  }

  const submitDownload = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createDownload({
      name: String(form.get('name')),
      collection_id: Number(form.get('collection_id')),
      local_media_profile_id: Number(form.get('local_media_profile_id')),
      enable_profile: form.get('enable_profile') === 'on',
    })
    event.currentTarget.reset()
  }

  const submitStream = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createStream({
      name: String(form.get('name')),
      collection_id: Number(form.get('collection_id')),
      enable_profile: form.get('enable_profile') === 'on',
      use_downloads: form.get('use_downloads') === 'on',
      format_selector: String(form.get('format_selector')),
    })
    event.currentTarget.reset()
  }

  return <div className="profiles-page">
    {mutationError && <p className="error panel">{errorMessage(mutationError)}</p>}

    <section className="panel">
      <div className="section-heading"><div><h2>Local media profiles</h2><p>Defines the local representation: path, yt-dlp format selection and post-processing.</p></div></div>
      <form className="profile-form" onSubmit={submitLocal}>
        <label>Name<input name="name" required placeholder="High quality video"/></label>
        <label>Scope<select name="scope" defaultValue="collection"><option value="collection">Channel / playlist</option><option value="video">Standalone video</option></select></label>
        <label>Media<select name="media_kind" defaultValue="video"><option value="video">Video</option><option value="audio">Audio</option></select></label>
        <label className="wide">Output template<input name="output_template" required defaultValue="/downloads/%(uploader)s/%(title)s [%(id)s].%(ext)s"/></label>
        <label className="wide">yt-dlp format selector<input name="preferred_format" required defaultValue="bestvideo*+bestaudio/best"/></label>
        <label>Merge format<input name="merge_output_format" placeholder="mkv"/></label>
        <label>Audio conversion<input name="audio_format" placeholder="mp3"/></label>
        <label className="checkbox"><input type="checkbox" name="write_subtitles"/> Write subtitles</label>
        <label className="checkbox"><input type="checkbox" name="embed_metadata" defaultChecked/> Embed metadata</label>
        <label className="checkbox"><input type="checkbox" name="embed_thumbnail"/> Embed thumbnail</label>
        <button type="submit">Add local profile</button>
      </form>
      <div className="profile-list">
        {localProfiles.map(profile => <div className="profile-row" key={profile.id}>
          <div><strong>{profile.name}</strong><span>{profile.scope} · {profile.media_kind} · {profile.preferred_format}</span></div>
          <button className="danger" onClick={() => deleteLocal(profile.id)}>Delete</button>
        </div>)}
      </div>
    </section>

    <section className="panel">
      <h2>Download profiles</h2>
      <p>Collection-scoped automation. Every sync queues missing artifacts for each enabled profile.</p>
      <form className="profile-form" onSubmit={submitDownload}>
        <label>Name<input name="name" required placeholder="Main archive"/></label>
        <label>Channel / playlist<select name="collection_id" required>{collections.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label>Local media profile<select name="local_media_profile_id" required>{collectionLocalProfiles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="checkbox"><input type="checkbox" name="enable_profile" defaultChecked/> Enabled</label>
        <button type="submit" disabled={collections.length === 0 || collectionLocalProfiles.length === 0}>Add download profile</button>
      </form>
      <div className="profile-list">
        {downloadProfiles.map(profile => <div className="profile-row" key={profile.id}>
          <div><strong>{profile.name}</strong><span>{collectionName(profile.collection_id)} · {localName(profile.local_media_profile_id)} · {profile.enable_profile ? 'enabled' : 'disabled'}</span></div>
          <button className="danger" onClick={() => deleteDownload(profile.id)}>Delete</button>
        </div>)}
      </div>
    </section>

    <section className="panel">
      <h2>Stream profiles</h2>
      <p>Collection-scoped streaming policy. It can prefer a local download and otherwise resolve a fresh direct URL through yt-dlp.</p>
      <form className="profile-form" onSubmit={submitStream}>
        <label>Name<input name="name" required placeholder="Browser compatible"/></label>
        <label>Channel / playlist<select name="collection_id" required>{collections.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label className="wide">yt-dlp format selector<input name="format_selector" required defaultValue="best[protocol^=http][vcodec!=none][acodec!=none]/best"/></label>
        <label className="checkbox"><input type="checkbox" name="enable_profile" defaultChecked/> Enabled</label>
        <label className="checkbox"><input type="checkbox" name="use_downloads"/> Prefer local downloads</label>
        <button type="submit" disabled={collections.length === 0}>Add stream profile</button>
      </form>
      <div className="profile-list">
        {streamProfiles.map(profile => <div className="profile-row" key={profile.id}>
          <div><strong>{profile.name}</strong><span>{collectionName(profile.collection_id)} · {profile.use_downloads ? 'local first' : 'yt-dlp stream'} · {profile.enable_profile ? 'enabled' : 'disabled'}</span></div>
          <button className="danger" onClick={() => deleteStream(profile.id)}>Delete</button>
        </div>)}
      </div>
    </section>
  </div>
}

export default function App() {
  const queryClient = useQueryClient()
  const [view, setView] = useState<AppView>('library')
  const [tab, setTab] = useState<LibraryTab>('channels')
  const [expandedCollection, setExpandedCollection] = useState<number | null>(null)
  const [url, setUrl] = useState('')
  const [kind, setKind] = useState<'auto' | 'channel' | 'playlist' | 'video'>('auto')

  const collections = useQuery({queryKey: ['collections'], queryFn: api.collections})
  const videos = useQuery({queryKey: ['videos'], queryFn: api.videos})
  const localProfiles = useQuery({queryKey: ['local-profiles'], queryFn: () => api.localProfiles()})
  const downloadProfiles = useQuery({queryKey: ['download-profiles'], queryFn: () => api.downloadProfiles()})
  const streamProfiles = useQuery({queryKey: ['stream-profiles'], queryFn: () => api.streamProfiles()})
  const tasks = useQuery({queryKey: ['tasks'], queryFn: api.tasks, refetchInterval: 1500})

  const invalidateLibrary = async () => Promise.all([
    queryClient.invalidateQueries({queryKey: ['collections']}),
    queryClient.invalidateQueries({queryKey: ['videos']}),
    queryClient.invalidateQueries({queryKey: ['tasks']}),
  ])
  const invalidateProfiles = async () => Promise.all([
    queryClient.invalidateQueries({queryKey: ['local-profiles']}),
    queryClient.invalidateQueries({queryKey: ['download-profiles']}),
    queryClient.invalidateQueries({queryKey: ['stream-profiles']}),
    queryClient.invalidateQueries({queryKey: ['collections']}),
  ])

  const add = useMutation({
    mutationFn: async () => {
      if (kind === 'video') return api.addVideo(url)
      if (kind === 'channel' || kind === 'playlist') return api.addCollection(url, kind)
      const inspection = await api.inspect(url)
      return inspection.kind === 'video'
        ? api.addVideo(url)
        : api.addCollection(url, inspection.kind as 'channel' | 'playlist')
    },
    onSuccess: async () => { setUrl(''); await invalidateLibrary() },
  })
  const sync = useMutation({mutationFn: api.syncCollection, onSuccess: invalidateLibrary})
  const download = useMutation({
    mutationFn: ({videoId, profileId}: {videoId: number; profileId: number}) => api.downloadVideo(videoId, profileId),
    onSuccess: invalidateLibrary,
  })
  const createLocal = useMutation({mutationFn: api.createLocalProfile, onSuccess: invalidateProfiles})
  const deleteLocal = useMutation({mutationFn: api.deleteLocalProfile, onSuccess: invalidateProfiles})
  const createDownload = useMutation({mutationFn: api.createDownloadProfile, onSuccess: invalidateProfiles})
  const deleteDownload = useMutation({mutationFn: api.deleteDownloadProfile, onSuccess: invalidateProfiles})
  const createStream = useMutation({mutationFn: api.createStreamProfile, onSuccess: invalidateProfiles})
  const deleteStream = useMutation({mutationFn: api.deleteStreamProfile, onSuccess: invalidateProfiles})

  const visibleCollections = useMemo(
    () => collections.data?.filter(item => item.kind === (tab === 'channels' ? 'channel' : 'playlist')) ?? [],
    [collections.data, tab],
  )
  const standaloneProfiles = localProfiles.data?.filter(profile => profile.scope === 'video') ?? []
  const activeTasks = tasks.data?.filter(task => !['succeeded', 'failed', 'cancelled'].includes(task.status)) ?? []
  const profileMutationError = createLocal.error ?? deleteLocal.error ?? createDownload.error ?? deleteDownload.error ?? createStream.error ?? deleteStream.error

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (url.trim()) add.mutate()
  }

  const play = async (videoId: number, profileId: number) => {
    try {
      const target = await api.resolveStream(videoId, profileId)
      window.open(target.url, '_blank', 'noopener,noreferrer')
    } catch (error) {
      window.alert(errorMessage(error))
    }
  }

  const renderVideo = (video: Video, locals: LocalMediaProfile[], streams: StreamProfile[]) => <article className="video-row" key={video.id}>
    {video.thumbnail_url && <img src={video.thumbnail_url} alt=""/>}
    <div className="video-copy"><h3>{video.title}</h3><p>{video.channel ?? video.uploader ?? video.extractor}</p></div>
    <VideoActions video={video} localProfiles={locals} streamProfiles={streams} onDownload={(videoId, profileId) => download.mutate({videoId, profileId})} onPlay={play}/>
  </article>

  return <div className="app">
    <header className="app-header">
      <div><h1>VodLoft</h1><p>yt-dlp powered media library</p></div>
      <nav className="main-nav"><button className={view === 'library' ? 'active' : ''} onClick={() => setView('library')}>Library</button><button className={view === 'profiles' ? 'active' : ''} onClick={() => setView('profiles')}>Profiles</button></nav>
    </header>

    {view === 'profiles' ? <ProfilesPanel
      collections={collections.data ?? []}
      localProfiles={localProfiles.data ?? []}
      downloadProfiles={downloadProfiles.data ?? []}
      streamProfiles={streamProfiles.data ?? []}
      createLocal={payload => createLocal.mutate(payload)}
      createDownload={payload => createDownload.mutate(payload)}
      createStream={payload => createStream.mutate(payload)}
      deleteLocal={id => deleteLocal.mutate(id)}
      deleteDownload={id => deleteDownload.mutate(id)}
      deleteStream={id => deleteStream.mutate(id)}
      mutationError={profileMutationError}
    /> : <main>
      <section className="panel">
        <h2>Add source</h2>
        <form onSubmit={submit} className="add-form">
          <input value={url} onChange={event => setUrl(event.target.value)} placeholder="Video, channel or playlist URL"/>
          <select value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
            <option value="auto">Auto detect</option><option value="channel">Channel</option><option value="playlist">Playlist</option><option value="video">Video</option>
          </select>
          <button disabled={add.isPending}>{add.isPending ? 'Adding…' : 'Add'}</button>
        </form>
        {add.error && <p className="error">{add.error.message}</p>}
      </section>

      {activeTasks.length > 0 && <section className="panel">
        <h2>Operations</h2>
        {activeTasks.map(task => <div className="task" key={task.id}><span>{task.name}</span><progress value={task.progress} max={100}/><span>{task.progress}%</span></div>)}
      </section>}

      <nav className="tabs">
        <button className={tab === 'channels' ? 'active' : ''} onClick={() => setTab('channels')}>Channels</button>
        <button className={tab === 'playlists' ? 'active' : ''} onClick={() => setTab('playlists')}>Playlists</button>
        <button className={tab === 'videos' ? 'active' : ''} onClick={() => setTab('videos')}>Videos</button>
      </nav>

      {tab !== 'videos' ? <section className="collection-list">
        {visibleCollections.map(collection => {
          const collectionDownloads = (downloadProfiles.data ?? []).filter(profile => profile.collection_id === collection.id && profile.enable_profile)
          const collectionLocals = collectionDownloads.map(profile => localProfiles.data?.find(local => local.id === profile.local_media_profile_id)).filter((item): item is LocalMediaProfile => Boolean(item))
          const collectionStreams = (streamProfiles.data ?? []).filter(profile => profile.collection_id === collection.id && profile.enable_profile)
          const expanded = expandedCollection === collection.id
          return <article className="collection-card" key={collection.id}>
            <div className="collection-summary">
              {collection.thumbnail_url && <img src={collection.thumbnail_url} alt=""/>}
              <div className="collection-copy"><span className="badge">{collection.kind}</span><h2>{collection.title}</h2><p>{collection.videos.length} videos · {collection.extractor}</p><p className="muted">{collectionDownloads.length} download profile{collectionDownloads.length === 1 ? '' : 's'} · {collectionStreams.length} stream profile{collectionStreams.length === 1 ? '' : 's'}</p></div>
              <div className="collection-actions"><button className="secondary" onClick={() => setExpandedCollection(expanded ? null : collection.id)}>{expanded ? 'Close' : 'Open'}</button><button onClick={() => sync.mutate(collection.id)}>Sync now</button></div>
            </div>
            {expanded && <div className="collection-videos">
              {collection.videos.length === 0 ? <p className="muted">No videos discovered yet.</p> : collection.videos.map(video => renderVideo(video, collectionLocals, collectionStreams))}
            </div>}
          </article>
        })}
      </section> : <section className="video-list">
        {(videos.data ?? []).map(video => renderVideo(video, standaloneProfiles, []))}
      </section>}
    </main>}
  </div>
}
