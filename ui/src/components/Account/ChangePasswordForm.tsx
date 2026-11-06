import './Account.css'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { buildServerAwareSubmit } from '../../utils/buildServerAwareSubmit'
import { hashPasswordForAdminAuth } from '../../utils/security/adminAuth'
import {apiUrl} from '../../lib/api'

const ChangePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, 'Enter your current password'),
    newPassword: z.string().min(7, 'Use at least 7 characters'),
    confirmPassword: z.string(),
  })
  .refine((values) => values.newPassword === values.confirmPassword, {
    path: ['confirmPassword'],
    message: 'The two new passwords differ',
  })
type ChangePasswordValues = z.input<typeof ChangePasswordSchema>

type Props = {
  /** Shown above the button, such as "Choose a new password" on the forced page. */
  submitLabel?: string
}

/** Change the signed-in user's own password. Other sessions are signed out; this one reloads. */
export default function ChangePasswordForm({ submitLabel = 'Change password' }: Props) {
  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(ChangePasswordSchema),
    defaultValues: { currentPassword: '', newPassword: '', confirmPassword: '' },
    shouldFocusError: true,
  })
  const {
    register,
    formState: { errors, isSubmitting },
  } = form

  const onSubmit = buildServerAwareSubmit<ChangePasswordValues>(
    form,
    async (data) => {
      const base = apiUrl()
      return await fetch(`${base}/auth/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          currentPasswordHash: await hashPasswordForAdminAuth(data.currentPassword),
          newPasswordHash: await hashPasswordForAdminAuth(data.newPassword),
        }),
      })
    },
    {
      successStatuses: [204],
      onSuccess: async () => {
        window.location.reload()
      },
      fieldAlias: { currentPasswordHash: 'currentPassword', newPasswordHash: 'newPassword' },
      fallbackField: 'currentPassword',
      rootServerValidationMessage: 'Your password was not changed.',
    },
  )

  return (
    <form className="form account-password-form" onSubmit={onSubmit} noValidate>
      {errors.root && (
        <div className="form-error-card" role="alert" aria-live="polite">
          {String(errors.root.message)}
        </div>
      )}
      <div className="form-row">
        <label htmlFor="current-password">Current password</label>
        <input id="current-password" className="input" type="password" autoComplete="current-password" {...register('currentPassword')} />
        {errors.currentPassword && <div className="error" role="alert">{String(errors.currentPassword.message)}</div>}
      </div>
      <div className="form-row">
        <label htmlFor="new-password">New password</label>
        <input id="new-password" className="input" type="password" autoComplete="new-password" {...register('newPassword')} />
        {errors.newPassword && <div className="error" role="alert">{String(errors.newPassword.message)}</div>}
      </div>
      <div className="form-row">
        <label htmlFor="confirm-password">New password again</label>
        <input id="confirm-password" className="input" type="password" autoComplete="new-password" {...register('confirmPassword')} />
        {errors.confirmPassword && <div className="error" role="alert">{String(errors.confirmPassword.message)}</div>}
      </div>
      <div className="actions">
        <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
          {submitLabel}
        </button>
      </div>
      <p className="account-note">Changing your password signs you out on your other devices.</p>
    </form>
  )
}
