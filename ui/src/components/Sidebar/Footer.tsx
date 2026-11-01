import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { NavLink } from 'react-router-dom'
import {getCurrentAppVersion} from "../../utils/helpers";
import {faIcon} from '../../icons/faIcon'
import { getAccess } from '../../lib/access'
import { signOut } from '../Account/signOut'

interface FooterProps {
  wrapperClass: string
}

export default function Footer({ wrapperClass }: FooterProps) {
  const publicConfig = (window as any).publicConfig
  const signInRequired = Boolean(publicConfig?.adminAuth?.enabled || publicConfig?.userAccounts?.enabled)
  const access = getAccess()
  const user = access?.user ?? null

  return (
    <footer className={wrapperClass} aria-label="Footer">
      <div className="footer-links">
        <a
          href="https://github.com/samuelvisser/vodloft"
          target="_blank"
          rel="noreferrer"
          className="footer-link"
        >
          <span className="icon" aria-hidden>
            <FontAwesomeIcon icon={faIcon('fab', 'github')} />
          </span>
          <span>GitHub</span>
        </a>
        {(user || access?.recovery) && (
          <NavLink to="/account" className="footer-link account-link" title="Your account">
            <span className="icon" aria-hidden>
              <FontAwesomeIcon icon={faIcon('fass', 'user')} />
            </span>
            <span>{user ? user.username : 'Recovery sign-in'}</span>
          </NavLink>
        )}
        {signInRequired && (
          <button
            type="button"
            className="footer-link"
            onClick={() => void signOut()}
            style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left', cursor: 'pointer' }}
          >
            <span className="icon" aria-hidden>
              <FontAwesomeIcon icon={faIcon('fass', 'right-from-bracket')} />
            </span>
            <span>Sign out</span>
          </button>
        )}
      </div>
      <div className="footer-meta" style={{ textAlign: 'center' }}>
        <span className="version" aria-label="App version" style={{ color: 'gray' }}>
          v{getCurrentAppVersion() ?? 'Unknown app version'}
        </span>
      </div>
    </footer>
  )
}
