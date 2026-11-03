import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faIcon } from '../icons/faIcon'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { buildServerAwareSubmit } from '../utils/buildServerAwareSubmit'
import { hashPasswordForAdminAuth } from '../utils/security/adminAuth'
import { getPublicConfig } from '../lib/publicConfig'
import { ClearInputButton } from '../components/common/ClearInputButton'
import './LoginPage.css'

const LoginSchema = z.object({
  // Only asked for once user accounts are on; empty signs in with the environment password.
  username: z.string().trim().default(''),
  password: z.string().min(7, 'Password must be at least 7 characters'),
})
type LoginValues = z.input<typeof LoginSchema>

export default function LoginPage() {
  const accountsEnabled = Boolean(getPublicConfig()?.userAccounts?.enabled)
  const [showPassword, setShowPassword] = useState(false)
  const form = useForm<LoginValues>({
    resolver: zodResolver(LoginSchema),
    defaultValues: LoginSchema.partial().parse({}),
    shouldFocusError: true,
  })

  const handleSubmit = buildServerAwareSubmit<LoginValues>(
    form,
    async (data) => {
      const base = (window as any).appConfig?.API_URL || '/api'
      const passwordHash = await hashPasswordForAdminAuth(data.password)
      const username = data.username?.trim()
      const payload = username ? { username, passwordHash } : { passwordHash }
      return await fetch(`${base}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload),
      })
    },
    {
      // login returns 204 No Content
      successStatuses: [204],
      onSuccess: async () => {
        // Reload to let the app re-check auth
        window.location.reload()
      },
      fallbackField: 'password',
      rootServerValidationMessage: accountsEnabled
        ? 'Sign-in failed. Please check your username and password and try again.'
        : 'Login failed. Please check the password and try again.',
    },
  )

  const {
    register,
    watch,
    setValue,
    setFocus,
    formState: { errors },
  } = form
  const username = watch('username')
  const password = watch('password')
  const clearField = (field: keyof LoginValues) => {
    setValue(field, '', { shouldDirty: true })
    setFocus(field)
  }

  return (
    <div className="login-page" style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', background: 'linear-gradient(135deg, #0b1020, #1b1f3b)' }}>
      <div style={{ width: 'min(440px, 92vw)', background: 'rgba(0,0,0,0.4)', borderRadius: 16, padding: 28, boxShadow: '0 20px 60px rgba(0,0,0,0.5)', border: '1px solid rgba(255,255,255,0.08)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, marginBottom: 18 }}>
          <img src="/logo-square-full.png" alt="VODLoft" style={{ width: 200, objectFit: 'contain', filter: 'drop-shadow(0 6px 16px rgba(0,0,0,0.5))' }} />
          <h1 style={{ color: 'white', fontSize: 24, margin: 0, fontWeight: 600 }}>Welcome</h1>
          <p style={{ color: 'rgba(255,255,255,0.7)', margin: 0, fontSize: 14 }}>
            {accountsEnabled ? 'Sign in with your username and password' : 'Enter the admin password to continue'}
          </p>
        </div>

        {/* Root error banner */}
        {errors.root && (
          <div role="alert" style={{ background: 'rgba(255, 77, 77, 0.12)', color: '#ffb3b3', border: '1px solid rgba(255,77,77,0.3)', borderRadius: 10, padding: '10px 12px', marginBottom: 12 }}>
            {errors.root.message?.toString()}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ display: 'grid', gap: 10 }}>
            {accountsEnabled && (
              <>
                <label htmlFor="username" style={{ color: 'rgba(255,255,255,0.85)', fontSize: 13 }}>Username</label>
                <div className="login-field">
                  <input
                    id="username"
                    type="text"
                    autoFocus
                    autoComplete="username"
                    autoCapitalize="none"
                    {...register('username')}
                    placeholder="Enter username"
                    style={{ ...inputStyle(Boolean(errors.username)), paddingRight: username ? 48 : 14 }}
                  />
                  {username && (
                    <div className="login-field-actions">
                      <ClearInputButton label="Clear the username" onClear={() => clearField('username')} />
                    </div>
                  )}
                </div>
                {errors.username && (
                  <div role="alert" style={{ color: '#ffb3b3', fontSize: 12 }}>{errors.username.message?.toString()}</div>
                )}
              </>
            )}
            <label htmlFor="password" style={{ color: 'rgba(255,255,255,0.85)', fontSize: 13 }}>Password</label>
            <div className="login-field">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoFocus={!accountsEnabled}
                autoComplete="current-password"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                {...register('password')}
                placeholder="Enter password"
                style={{ ...inputStyle(Boolean(errors.password)), paddingRight: password ? 84 : 48 }}
              />
              <div className="login-field-actions">
                {password && <ClearInputButton label="Clear the password" onClear={() => clearField('password')} />}
                <button
                  type="button"
                  className="login-field-action"
                  onClick={() => setShowPassword((shown) => !shown)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  title={showPassword ? 'Hide password' : 'Show password'}
                >
                  <FontAwesomeIcon icon={showPassword ? faIcon('fass', 'eye-slash') : faIcon('fass', 'eye')} />
                </button>
              </div>
            </div>
            {errors.password && (
              <div role="alert" style={{ color: '#ffb3b3', fontSize: 12 }}>{errors.password.message?.toString()}</div>
            )}

            <button type="submit" style={{ marginTop: 12, background: 'linear-gradient(135deg, #4a6bff, #5f9dff)', color: 'white', fontWeight: 600, border: 'none', borderRadius: 10, padding: '12px 14px', fontSize: 14, cursor: 'pointer', boxShadow: '0 10px 20px rgba(79,131,255,0.25)' }}>
              {accountsEnabled ? 'Sign in' : 'Unlock'}
            </button>
          </div>
        </form>

        <div style={{ marginTop: 18, textAlign: 'center', color: 'rgba(255,255,255,0.55)', fontSize: 12 }}>
          {accountsEnabled
            ? 'Forgot your password? Ask the person who runs this VODLoft.'
            : 'Protected by local password set by the admin. Only authorized users are allowed to access VODLoft.'}
        </div>
      </div>
    </div>
  )
}


function inputStyle(invalid: boolean): React.CSSProperties {
  return {
    WebkitAppearance: 'none',
    background: 'rgba(255,255,255,0.07)',
    border: `1px solid ${invalid ? 'rgba(255,77,77,0.5)' : 'rgba(255,255,255,0.15)'}`,
    color: 'white',
    padding: '12px 14px',
    borderRadius: 10,
    outline: 'none',
    // 16px or larger keeps iOS Safari from zooming in when the field gets focus.
    fontSize: 16,
    boxShadow: invalid ? '0 0 0 3px rgba(255,77,77,0.15)' : 'none',
  }
}
