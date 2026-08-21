import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'

import Button from '../../components/shared/Button'
import {
  PASSWORD_REQUIREMENTS,
  canBeginSubmission,
  passwordRequirementState,
  togglePasswordVisibility,
  validateCreateAccount,
} from './createAccountState'
import { testOnboardingDestination } from './testOnboardingContext'

function PasswordField({
  children,
  describedBy,
  error,
  id,
  label,
  onBlur,
  onChange,
  onToggleVisibility,
  t,
  value,
  visible,
}) {
  return (
    <div className={`field span-2${error ? ' has-error' : ''}`}>
      <label htmlFor={id}>
        {label} <span aria-hidden="true">*</span>
      </label>
      <div className="password-wrap">
        <input
          id={id}
          name={id}
          className="input"
          type={visible ? 'text' : 'password'}
          autoComplete="new-password"
          required
          value={value}
          aria-describedby={describedBy}
          aria-invalid={error ? 'true' : undefined}
          onBlur={onBlur}
          onChange={onChange}
        />
        <button
          className="password-toggle"
          type="button"
          aria-controls={id}
          aria-pressed={visible}
          onClick={onToggleVisibility}
        >
          {visible ? t('createAccount.actions.hide') : t('createAccount.actions.show')}
        </button>
      </div>
      {children}
      {error ? (
        <p id={`${id}-error`} className="field-error">
          {t(error.messageKey)}
        </p>
      ) : null}
    </div>
  )
}

export default function CreateAccountPage() {
  const { t } = useTranslation('portal')
  const { search } = useLocation()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [confirmationVisible, setConfirmationVisible] = useState(false)
  const [errors, setErrors] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const errorSummaryRef = useRef(null)
  const testDestination = testOnboardingDestination(search)

  const requirementState = useMemo(() => passwordRequirementState(password), [password])
  const errorSignature = errors.map(({ field, messageKey }) => `${field}:${messageKey}`).join('|')
  const passwordError = errors.find(({ field }) => field === 'password')
  const confirmationError = errors.find(({ field }) => field === 'confirmation')

  useEffect(() => {
    if (errors.length > 0) {
      errorSummaryRef.current?.focus()
    }
  }, [errorSignature, errors.length])

  function replaceFieldError(field, nextError) {
    setErrors((currentErrors) => [
      ...currentErrors.filter((error) => error.field !== field),
      ...(nextError ? [nextError] : []),
    ])
  }

  function handlePasswordChange(event) {
    setPassword(event.target.value)
    setSubmitting(false)
    setErrors((currentErrors) =>
      currentErrors.filter(({ field }) => field !== 'password' && field !== 'confirmation'),
    )
  }

  function handleConfirmationChange(event) {
    setConfirmation(event.target.value)
    setSubmitting(false)
    replaceFieldError('confirmation', null)
  }

  function handlePasswordBlur() {
    if (!password) return

    const nextError = validateCreateAccount(password, confirmation).find(
      ({ field }) => field === 'password',
    )
    replaceFieldError('password', nextError)
  }

  function handleConfirmationBlur() {
    if (!confirmation) return

    const nextError = validateCreateAccount(password, confirmation).find(
      ({ field }) => field === 'confirmation',
    )
    replaceFieldError('confirmation', nextError)
  }

  function handleSubmit(event) {
    event.preventDefault()

    const nextErrors = validateCreateAccount(password, confirmation)
    setErrors(nextErrors)

    if (canBeginSubmission(nextErrors, submitting)) {
      if (testDestination) {
        navigate(testDestination)
        return
      }
      setSubmitting(true)
    }
  }

  return (
    <div className="auth create-account">
      <main id="main" className="auth-card">
        <h1>{t('createAccount.title')}</h1>
        <p className="lead">{t('createAccount.description')}</p>

        {testDestination ? (
          <section className="local-dev-simulation" aria-label={t('createAccount.testHandoff.label')}>
            <span className="dev-label">{t('createAccount.testHandoff.label')}</span>
            <h2>{t('createAccount.testHandoff.title')}</h2>
            <p className="hint">{t('createAccount.testHandoff.description')}</p>
          </section>
        ) : null}

        {errors.length > 0 ? (
          <section className="error-summary" role="alert" tabIndex="-1" ref={errorSummaryRef}>
            <h2>{t('createAccount.validation.errorTitle')}</h2>
            <ul>
              {errors.map((error) => (
                <li key={error.field}>
                  <a
                    href={`#${error.field === 'password' ? 'new-password' : 'confirm-password'}`}
                    onClick={(event) => {
                      event.preventDefault()
                      document.getElementById(event.currentTarget.hash.slice(1))?.focus()
                    }}
                  >
                    {t(error.messageKey)}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <form noValidate aria-busy={submitting ? 'true' : undefined} onSubmit={handleSubmit}>
          <div className="form-grid">
            <PasswordField
              id="new-password"
              label={t('createAccount.fields.password.label')}
              value={password}
              visible={passwordVisible}
              error={passwordError}
              describedBy={`password-requirements${passwordError ? ' new-password-error' : ''}`}
              t={t}
              onChange={handlePasswordChange}
              onBlur={handlePasswordBlur}
              onToggleVisibility={() => setPasswordVisible(togglePasswordVisibility)}
            >
              <ul id="password-requirements" className="password-requirements" aria-live="polite">
                {PASSWORD_REQUIREMENTS.map((requirement) => (
                  <li key={requirement} className={requirementState[requirement] ? 'met' : undefined}>
                    {t(`createAccount.requirements.${requirement}`)}
                  </li>
                ))}
              </ul>
            </PasswordField>

            <PasswordField
              id="confirm-password"
              label={t('createAccount.fields.confirmPassword.label')}
              value={confirmation}
              visible={confirmationVisible}
              error={confirmationError}
              describedBy={confirmationError ? 'confirm-password-error' : undefined}
              t={t}
              onChange={handleConfirmationChange}
              onBlur={handleConfirmationBlur}
              onToggleVisibility={() => setConfirmationVisible(togglePasswordVisibility)}
            />
          </div>

          <div className="actions">
            <Button type="submit" disabled={submitting}>
              {testDestination
                ? t('createAccount.actions.continueOnboarding')
                : submitting
                ? t('createAccount.actions.creating')
                : t('createAccount.actions.create')}
            </Button>
          </div>
        </form>
      </main>
    </div>
  )
}
