import {apiUrl} from '../../lib/api'
/** Sign out and reload, so the app starts over at the sign-in page. */
export async function signOut() {
  const base = apiUrl()
  try {
    await fetch(`${base}/auth/logout`, { method: 'POST', credentials: 'include' })
  } catch {
    // Reloading shows whether the session is still there.
  } finally {
    window.location.reload()
  }
}
