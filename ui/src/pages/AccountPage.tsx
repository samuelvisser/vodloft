import ChangePasswordForm from '../components/Account/ChangePasswordForm'
import PageSubtitle from '../components/common/PageSubtitle'
import { Link } from 'react-router-dom'
import { getAccess } from '../lib/access'

/** The signed-in user's own account: who they are, and changing their password. */
export default function AccountPage() {
  const access = getAccess()
  const user = access?.user

  return (
    <section className="view account-view" aria-labelledby="account-title">
      <div className="view-header">
        <h1 id="account-title">Your account</h1>
        <PageSubtitle summary={user ? <>Signed in as <b>{user.username}</b>.</> : <>Signed in with the admin password.</>} />
      </div>
      <div className="account-card">
        <h2>Notifications</h2>
        <p>Get a push message on your phone or computer when your Quick downloads finish or new episodes arrive. <Link to="/account/notifications">Set up notifications</Link></p>
      </div>
      {user ? (
        <div className="account-card">
          <h2>Password</h2>
          <ChangePasswordForm />
        </div>
      ) : (
        <p>
          {access?.recovery
            ? 'You signed in with the environment password because no administrator can sign in. Give an administrator a new password in Settings › Users.'
            : 'The admin password is set in VODLoft’s environment, not here.'}
        </p>
      )}
    </section>
  )
}
