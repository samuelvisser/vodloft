import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {FormEvent, useMemo, useState} from 'react'
import {api} from './api'
import type {Video} from './schemas'

type LibraryTab = 'channels' | 'playlists' | 'videos'

export default function App() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<LibraryTab>('channels')
  const collections = useQuery({queryKey: ['collections'], queryFn: api.collections})
  const videos = useQuery({queryKey: ['videos'], queryFn: api.videos})
  const profiles = useQuery({queryKey: ['download-profiles'], queryFn: api.downloadProfiles})
  const tasks = useQuery({queryKey: ['tasks'], queryFn: api.tasks, refetchInterval: 1500})
  const [url, setUrl] = useState('')
  const [kind, setKind] = useState<'auto' | 'channel' | 'playlist' | 'video'>('auto')

  const add = useMutation({
    mutationFn: async () => {
      if (kind === 'video') return api.addVideo(url)
      if (kind === 'channel' || kind === 'playlist') return api.addCollection(url, kind)
      const inspection = await api.inspect(url)
      return inspection.kind === 'video'
        ? api.addVideo(url)
        : api.addCollection(url, inspection.kind as 'channel' | 'playlist')
    },
    onSuccess: async () => {
      setUrl('')
      await Promise.all([
        queryClient.invalidateQueries({queryKey: ['collections']}),
        queryClient.invalidateQueries({queryKey: ['videos']}),
      ])
    },
  })

  const sync = useMutation({
    mutationFn: api.syncCollection,
    onSuccess: () => queryClient.invalidateQueries({queryKey: ['tasks']}),
  })

  const download = useMutation({
    mutationFn: ({videoId, profileId}: {videoId: number; profileId: number}) => api.downloadVideo(videoId, profileId),
    onSuccess: () => queryClient.invalidateQueries({queryKey: ['tasks']}),
  })

  const visibleCollections = useMemo(
    () => collections.data?.filter(item => item.kind === (tab === 'channels' ? 'channel' : 'playlist')) ?? [],
    [collections.data, tab],
  )
  const defaultProfile = profiles.data?.[0]
  const activeTasks = tasks.data?.filter(task => !['succeeded', 'failed', 'cancelled'].includes(task.status)) ?? []

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (url.trim()) add.mutate()
  }

  const videoCard = (video: Video) => <article className="card" key={video.id}>
    {video.thumbnail_url && <img src={video.thumbnail_url} alt=""/>}
    <div>
      <h3>{video.title}</h3>
      <p>{video.channel ?? video.uploader ?? video.extractor}</p>
      <div className="card-actions">
        {video.downloaded_path
          ? <span className="badge">Downloaded · {video.downloaded_format ?? 'unknown format'}</span>
          : <button disabled={!defaultProfile || download.isPending} onClick={() => defaultProfile && download.mutate({videoId: video.id, profileId: defaultProfile.id})}>
              Download{defaultProfile ? ` · ${defaultProfile.name}` : ''}
            </button>}
      </div>
    </div>
  </article>

  return <div className="app">
    <header><h1>VodLoft</h1><p>yt-dlp powered media library</p></header>
    <main>
      <section className="panel">
        <h2>Add source</h2>
        <form onSubmit={submit} className="add-form">
          <input value={url} onChange={e => setUrl(e.target.value)} placeholder="Video, channel or playlist URL"/>
          <select value={kind} onChange={e => setKind(e.target.value as typeof kind)}>
            <option value="auto">Auto detect</option><option value="channel">Channel</option>
            <option value="playlist">Playlist</option><option value="video">Video</option>
          </select>
          <button disabled={add.isPending}>{add.isPending ? 'Adding…' : 'Add'}</button>
        </form>
        {add.error && <p className="error">{add.error.message}</p>}
      </section>

      {activeTasks.length > 0 && <section className="panel">
        <h2>Operations</h2>
        {activeTasks.map(task => <div className="task" key={task.id}>
          <span>{task.name}</span><progress value={task.progress} max={100}/><span>{task.progress}%</span>
        </div>)}
      </section>}

      <nav className="tabs">
        <button className={tab === 'channels' ? 'active' : ''} onClick={() => setTab('channels')}>Channels</button>
        <button className={tab === 'playlists' ? 'active' : ''} onClick={() => setTab('playlists')}>Playlists</button>
        <button className={tab === 'videos' ? 'active' : ''} onClick={() => setTab('videos')}>Videos</button>
      </nav>

      {tab !== 'videos' ? <section><div className="grid">
        {visibleCollections.map(item => <article className="card" key={item.id}>
          {item.thumbnail_url && <img src={item.thumbnail_url} alt=""/>}
          <div>
            <span className="badge">{item.kind}</span><h3>{item.title}</h3>
            <p>{item.videos.length} videos · {item.extractor}</p>
            <div className="card-actions"><button disabled={sync.isPending} onClick={() => sync.mutate(item.id)}>Sync now</button></div>
          </div>
        </article>)}
      </div></section> : <section><div className="grid">{videos.data?.map(videoCard)}</div></section>}
    </main>
  </div>
}
