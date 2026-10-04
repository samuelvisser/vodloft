import {useState} from 'react'

type Props = {adminPasswordConfigured: boolean; onComplete: () => void}

export default function VodLoftOnboarding({adminPasswordConfigured, onComplete}: Props) {
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const finish = async () => {
        setBusy(true); setError(null)
        try {
            const base = (window as any).appConfig?.API_URL || '/api'
            const response = await fetch(`${base}/onboarding/complete`, {method: 'POST', credentials: 'include'})
            if (!response.ok) throw new Error(`HTTP ${response.status}`)
            onComplete()
        } catch (e) { setError(String(e)) } finally { setBusy(false) }
    }
    return <main className="onboarding-bootstrap" style={{minHeight: '100vh'}}>
        <section style={{maxWidth: 600, margin: 'auto', padding: 32}}>
            <h1>Welcome to VodLoft</h1>
            <p>Build a local library from web media. Start by adding a video, channel, or playlist URL.</p>
            {!adminPasswordConfigured && <p>For a server accessible to others, set
                <code> WL_ADMIN_AUTH__PASSWORD </code> in the container environment and restart VodLoft.
                This inherited setting protects the library and download actions.</p>}
            {error && <p role="alert">{error}</p>}
            <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void finish()}>
                Open VodLoft
            </button>
        </section>
    </main>
}
