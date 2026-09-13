import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {FormEvent, useState} from 'react'
import {api} from './api'

export default function App() {
  const queryClient = useQueryClient()
  const collections = useQuery({queryKey: ['collections'], queryFn: api.collections})
  const videos = useQuery({queryKey: ['videos'], queryFn: api.videos})
  const [url, setUrl] = useState('')
  const [kind, setKind] = useState<'auto' | 'channel' | 'playlist' | 'video'>('auto')
  const add = useMutation({
    mutationFn: async () => {
      if (kind === 'video') return api.addVideo(url)
      if (kind === 'channel' || kind === 'playlist') return api.addCollection(url, kind)
      const inspection = await api.inspect(url)
      return inspection.kind === 'video' ? api.addVideo(url) : api.addCollection(url, inspection.kind as 'channel' | 'playlist')
    },
    onSuccess: async () => {
      setUrl('')
      await Promise.all([queryClient.invalidateQueries({queryKey: ['collections']}), queryClient.invalidateQueries({queryKey: ['videos']})])
    },
  })

  const submit = (event: FormEvent) => { event.preventDefault(); if (url.trim()) add.mutate() }

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

      <section><h2>Channels & playlists</h2><div className="grid">
        {collections.data?.map(item => <article className="card" key={item.id}>
          {item.thumbnail_url && <img src={item.thumbnail_url} alt=""/>}
          <div><span className="badge">{item.kind}</span><h3>{item.title}</h3><p>{item.videos.length} videos · {item.extractor}</p></div>
        </article>)}
      </div></section>

      <section><h2>Videos</h2><div className="grid">
        {videos.data?.map(video => <article className="card" key={video.id}>
          {video.thumbnail_url && <img src={video.thumbnail_url} alt=""/>}
          <div><h3>{video.title}</h3><p>{video.channel ?? video.uploader ?? video.extractor}</p>{video.downloaded_path && <span className="badge">Downloaded</span>}</div>
        </article>)}
      </div></section>
    </main>
  </div>
}
