import type React from 'react'
import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Route,
  ScrollRestoration,
  useNavigate,
} from 'react-router-dom'
import App from './App'
import HomePage from './pages/HomePage'
import LocalMediaProfilesPage from './pages/LocalMediaProfilesPage'
import SettingsPage from './pages/SettingsPage'
import LogsPage from './pages/LogsPage'
import TasksPage from './pages/TasksPage'
import AddShowPage from './pages/show/AddShowPage'
import AddLocalMediaProfilePage from './pages/local-media-profile/AddLocalMediaProfilePage'
import EditLocalMediaProfilePage from './pages/local-media-profile/EditLocalMediaProfilePage'
import LocalMediaProfilePage from './pages/local-media-profile/LocalMediaProfilePage'
import ShowPage from './pages/show/ShowPage'
import EditShow from './pages/show/EditShowPage'
import EpisodePage from './pages/episode/EpisodePage'
import DownloadProfilesPage from './pages/DownloadProfilesPage'
import AddDownloadProfilePage from './pages/download-profile/AddDownloadProfilePage'
import EditDownloadProfilePage from './pages/download-profile/EditDownloadProfilePage'
import StreamProfilesPage from './pages/StreamProfilesPage'
import AddStreamProfilePage from './pages/stream-profile/AddStreamProfilePage'
import EditStreamProfilePage from './pages/stream-profile/EditStreamProfilePage'
import DownloadsPage from './pages/DownloadsPage'
import QuickDownloadPage from './pages/QuickDownloadPage'
import LibraryPage from './pages/LibraryPage'
import BrowsePage from './pages/BrowsePage'
import SourceSearchPage from './pages/SourceSearchPage'
import AddMediaPage from './pages/AddMediaPage'
import MoviePage from './pages/movie/MoviePage'
import EditMoviePage from './pages/movie/EditMoviePage'
import VideoPage from './pages/video/VideoPage'
import AccountPage from './pages/AccountPage'
import { allows, getAccess, homePath, canAnySettings, type Area, type Level } from './lib/access'

function RootRoute() {
  return (
    <>
      <App />
      <ScrollRestoration />
    </>
  )
}

/** Opens the page only for people with at least ``level`` in ``area``; others go to their first page. */
function Guard({ area, level = 'view', when, children }: {
  area?: Area
  level?: Level
  when?: () => boolean
  children: React.ReactNode
}) {
  const access = getAccess()
  const allowed = when ? when() : area ? allows(access, area, level) : true
  return allowed ? <>{children}</> : <Navigate to={homePath(access)} replace />
}

function g(area: Area, element: React.ReactNode, level: Level = 'view') {
  return <Guard area={area} level={level}>{element}</Guard>
}

function AddShowRoute() {
  const navigate = useNavigate()
  return <AddShowPage onCancel={() => navigate('/library')} />
}

export const router = createBrowserRouter(
  createRoutesFromElements(
    <Route path="/" element={<RootRoute />}>
      <Route index element={g('library', <HomePage />)} />
      <Route path="library" element={g('library', <LibraryPage />)} />
      <Route path="shows" element={<Navigate to="/library?type=shows" replace />} />
      <Route path="browse" element={g('add_media', <BrowsePage />)} />
      <Route path="browse/:sourceId" element={g('add_media', <SourceSearchPage />)} />
      <Route path="add" element={g('add_media', <AddMediaPage />)} />
      <Route path="quick-download" element={g('quick_downloads', <QuickDownloadPage />)} />
      <Route path="downloads" element={g('managed_downloads', <DownloadsPage />)} />
      <Route path="local-media-profiles" element={g('local_media_profiles', <LocalMediaProfilesPage />)} />
      <Route path="settings" element={<Guard when={() => canAnySettings()}><SettingsPage /></Guard>} />
      <Route path="logs" element={g('logs', <LogsPage />)} />
      <Route path="tasks" element={g('tasks', <TasksPage />)} />
      <Route path="add-show" element={g('add_media', <AddShowRoute />)} />
      <Route path="add-local-media-profile" element={g('local_media_profiles', <AddLocalMediaProfilePage />, 'manage')} />
      <Route path="local-media-profile/:slug" element={g('local_media_profiles', <LocalMediaProfilePage />)} />
      <Route path="edit-local-media-profile/:slug" element={g('local_media_profiles', <EditLocalMediaProfilePage />, 'manage')} />
      <Route path="download-profiles" element={g('download_profiles', <DownloadProfilesPage />)} />
      <Route path="add-download-profile" element={g('download_profiles', <AddDownloadProfilePage />, 'manage')} />
      <Route path="edit-download-profile/:id" element={g('download_profiles', <EditDownloadProfilePage />, 'manage')} />
      <Route path="stream-profiles" element={g('stream_profiles', <StreamProfilesPage />)} />
      <Route path="add-stream-profile" element={g('stream_profiles', <AddStreamProfilePage />)} />
      <Route path="edit-stream-profile/:type/:id" element={g('stream_profiles', <EditStreamProfilePage />)} />
      <Route path="show/:id" element={g('library', <ShowPage />)} />
      <Route path="movie/:slug" element={g('library', <MoviePage />)} />
      <Route path="edit-movie/:slug" element={g('library', <EditMoviePage />, 'manage')} />
      <Route path="video/:id" element={g('library', <VideoPage />)} />
      <Route path="show/:id/episode/:episodeId" element={g('library', <EpisodePage />)} />
      <Route path="edit-show/:id" element={g('library', <EditShow />, 'manage')} />
      <Route path="account" element={<AccountPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>,
  ),
)
