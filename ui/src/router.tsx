import {createBrowserRouter, createRoutesFromElements, Navigate, Route, ScrollRestoration} from 'react-router-dom'
import App from './App'
import WebMediaPage from './pages/WebMediaPage'
import VodLoftSettingsPage from './pages/VodLoftSettingsPage'
import TasksPage from './pages/TasksPage'
import LogsPage from './pages/LogsPage'

function RootRoute() {return <><App/><ScrollRestoration/></>}
export const router = createBrowserRouter(createRoutesFromElements(
    <Route path="/" element={<RootRoute/>}>
        <Route index element={<WebMediaPage key="home" initialView="home"/>}/>
        <Route path="discover" element={<WebMediaPage key="discover" initialView="discover"/>}/>
        <Route path="library" element={<WebMediaPage key="library" initialView="library"/>}/>
        <Route path="management" element={<WebMediaPage key="management" initialView="management"/>}/>
        <Route path="settings" element={<VodLoftSettingsPage/>}/>
        <Route path="tasks" element={<TasksPage/>}/>
        <Route path="logs" element={<LogsPage/>}/>
        <Route path="web-media" element={<Navigate to="/" replace/>}/>
        <Route path="*" element={<Navigate to="/" replace/>}/>
    </Route>
))
