import {useEffect, useState} from 'react'
import SettingsPage from './SettingsPage'

const apiBase = () => (window as any).appConfig?.API_URL || '/api'

export default function VodLoftSettingsPage() {
    const [actor, setActor] = useState<{username: string; role: string} | null>(null)
    const [error, setError] = useState<string | null>(null)
    useEffect(() => {
        void fetch(`${apiBase()}/vodloft/me`, {credentials: 'include'}).then(r => {
            if (!r.ok) throw new Error('Could not read your account')
            return r.json()
        }).then(setActor).catch(error => setError(String(error)))
    }, [])
    return <>{actor?.role === 'admin' ? <SettingsPage/> : <section className="page"><h1>Settings</h1>
        <p>Signed in as {actor?.username ?? '…'} · {actor?.role}</p>
        {actor && <p>Application settings are managed by an administrator.</p>}
        {error && <p role="alert">{error}</p>}
    </section>}
    <section className="page"><button type="button" className="btn" onClick={() => void fetch(`${apiBase()}/auth/logout`,
        {method: 'POST', credentials: 'include'}).then(() => window.location.reload())}>Sign out</button></section></>
}
