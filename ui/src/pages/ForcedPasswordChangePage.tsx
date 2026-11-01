import ChangePasswordForm from '../components/Account/ChangePasswordForm'
import { getAccess } from '../lib/access'
import { signOut } from '../components/Account/signOut'

/** Shown instead of VODLoft until a user given a one-time password picks their own. */
export default function ForcedPasswordChangePage() {
  const username = getAccess()?.user?.username

  return (
    <div className="forced-password-page">
      <div className="forced-password-card">
        <img src="/logo-square-full.png" alt="VODLoft" className="forced-password-logo" />
        <h1>Choose your own password</h1>
        <p>
          {username ? <><b>{username}</b>, your </> : 'Your '}
          password was set by an administrator. Choose your own before you continue.
        </p>
        <ChangePasswordForm submitLabel="Save and continue" />
        <button type="button" className="btn forced-password-signout" onClick={() => void signOut()}>
          Sign out
        </button>
      </div>
    </div>
  )
}
