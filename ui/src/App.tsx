import { useCallback, useEffect, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import Sidebar from './components/Sidebar'
import Footer from './components/Sidebar/Footer'
import OnboardingFlow from './components/Onboarding/OnboardingFlow'
import BackgroundMigrationBanner from './components/BackgroundMigrationBanner/BackgroundMigrationBanner'
import LoginPage from './pages/LoginPage'
import PullToRefresh from './components/PullToRefresh/PullToRefresh'
import OperationNotifier from './components/OperationNotifier/OperationNotifier'
import ImportMatchesWatcher from './components/ExistingFiles/ImportMatchesWatcher'
import {operationNotificationDefinitions} from './components/OperationNotifier/OperationNotificationDefinitions'
import FrontendPuller from './lib/puller'
import ForcedPasswordChangePage from './pages/ForcedPasswordChangePage'
import { accessChecked, getAccess, loadAccess } from './lib/access'

type OnboardingStatus = {
  completed: boolean
  adminPasswordConfigured: boolean
}

export default function App() {
  const navigate = useNavigate()

  // main.tsx asked who is signed in before rendering; ask again only if that failed.
  const [authState, setAuthState] = useState<'checking' | 'ok' | 'no'>(getAccess() ? 'ok' : accessChecked() ? 'no' : 'checking')
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatus | null>(null)
  const [onboardingError, setOnboardingError] = useState<string | null>(null)

  useEffect(() => {
    if (authState !== 'checking') return
    let cancelled = false
    loadAccess()
      .then((access) => {
        if (!cancelled) setAuthState(access ? 'ok' : 'no')
      })
      .catch(() => {
        if (!cancelled) setAuthState('no')
      })
    return () => {
      cancelled = true
    }
  }, [authState])

  const loadOnboardingStatus = useCallback(async () => {
    setOnboardingError(null)
    try {
      const base = (window as any).appConfig?.API_URL || '/api'
      const response = await fetch(`${base}/onboarding/status`, { credentials: 'include' })
      if (response.status === 401) {
        setAuthState('no')
        return
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setOnboardingStatus(await response.json())
    } catch {
      setOnboardingError('VODLoft could not determine whether first-run setup is complete.')
    }
  }, [])

  const mustChangePassword = Boolean(getAccess()?.user?.mustChangePassword)

  useEffect(() => {
    if (authState !== 'ok' || mustChangePassword) return
    void loadOnboardingStatus()
  }, [authState, mustChangePassword, loadOnboardingStatus])

  if (authState === 'checking') {
    return null
  }

  if (authState === 'no') {
    return <LoginPage />
  }

  if (mustChangePassword) {
    return <ForcedPasswordChangePage />
  }

  if (!onboardingStatus) {
    if (!onboardingError) return null
    return (
      <div className="onboarding-bootstrap">
        <div>
          <p role="alert">{onboardingError}</p>
          <button className="btn btn-primary" type="button" onClick={() => void loadOnboardingStatus()}>
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!onboardingStatus.completed) {
    return (
      <OnboardingFlow
        adminPasswordConfigured={onboardingStatus.adminPasswordConfigured}
        onComplete={() => {
          setOnboardingStatus((current) => current ? { ...current, completed: true } : current)
          navigate('/', { replace: true })
          toast.success(
            'VODLoft is setup. Look around a little and explore your very own media manager. Enjoy!',
            { duration: 8000 },
          )
        }}
      />
    )
  }

  return (
    <FrontendPuller onUnauthorized={() => setAuthState('no')}>
      <OperationNotifier definitions={operationNotificationDefinitions}>
        <div className="app">
          <PullToRefresh />
          {/* After onboarding too, so an import started there still says when its matches are ready. */}
          <ImportMatchesWatcher />
          <Sidebar />
          <main className="content" role="main">
            {/* Deliberately mounted only after onboarding so first-run setup never shows this banner. */}
            <BackgroundMigrationBanner />
            <Outlet />
          </main>
          <Footer wrapperClass="page-footer" />
        </div>
      </OperationNotifier>
    </FrontendPuller>
  )
}
