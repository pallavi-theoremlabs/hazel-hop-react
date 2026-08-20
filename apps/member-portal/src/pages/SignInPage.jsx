import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button'

export default function SignInPage() {
  const { t } = useTranslation('public')
  const navigate = useNavigate()
  const [visible, setVisible] = useState(false)
  const [message, setMessage] = useState('')

  function unavailable(event) {
    event.preventDefault()
    setMessage(t('signIn.unavailable'))
  }

  return <div className="auth sign-in-page"><main id="main" className="auth-card">
    <h1>{t('signIn.title')}</h1>
    <p className="lead">{t('signIn.description')}</p>
    {message && <div className="alert warning" role="status"><strong>{t('signIn.unavailableTitle')}</strong><br />{message}</div>}
    <form onSubmit={unavailable} noValidate>
      <div className="field">
        <label htmlFor="login-email">{t('signIn.email')} <span className="required" aria-hidden="true">*</span></label>
        <input className="input" id="login-email" name="login-email" type="email" autoComplete="username" inputMode="email" required />
      </div>
      <div className="field">
        <label htmlFor="login-password">{t('signIn.password')} <span className="required" aria-hidden="true">*</span></label>
        <div className="password-wrap">
          <input className="input" id="login-password" name="login-password" type={visible ? 'text' : 'password'} autoComplete="current-password" required />
          <button className="password-toggle" type="button" aria-controls="login-password" aria-pressed={visible} onClick={() => setVisible((value) => !value)}>{visible ? t('signIn.hide') : t('signIn.show')}</button>
        </div>
      </div>
      <button type="button" className="text-action" onClick={() => setMessage(t('signIn.resetUnavailable'))}>{t('signIn.forgot')}</button>
      <div className="actions"><Button type="submit">{t('signIn.action')}</Button><Button type="button" variant="secondary" onClick={() => navigate('/submit-interest')}>{t('signIn.back')}</Button></div>
      <p className="submission-note">{t('signIn.integrationNote')}</p>
    </form>
  </main></div>
}
