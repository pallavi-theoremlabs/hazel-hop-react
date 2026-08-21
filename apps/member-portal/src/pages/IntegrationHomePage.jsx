import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import Button from '../components/Button'
import { integrationCasePath } from '../services/integrationContext'

export default function IntegrationHomePage() {
  const { t } = useTranslation('public')
  const navigate = useNavigate()
  const [caseId, setCaseId] = useState('')
  const [institutionId, setInstitutionId] = useState('')
  const [error, setError] = useState('')

  function openCase(event) {
    event.preventDefault()
    const path = integrationCasePath(caseId, institutionId)
    if (!path) {
      setError(t('integrationHome.invalidContext'))
      return
    }
    navigate(path)
  }

  return <div className="auth sign-in-page"><main id="main" className="auth-card">
    <p className="eyebrow">{t('integrationHome.eyebrow')}</p>
    <h1>{t('integrationHome.title')}</h1>
    <p className="lead">{t('integrationHome.description')}</p>
    {error && <div className="alert danger" role="alert">{error}</div>}
    <form onSubmit={openCase} noValidate>
      <div className="field">
        <label htmlFor="integration-case-id">{t('integrationHome.caseId')}</label>
        <input className="input" id="integration-case-id" value={caseId} onChange={(event) => setCaseId(event.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="integration-institution-id">{t('integrationHome.institutionId')}</label>
        <input className="input" id="integration-institution-id" value={institutionId} onChange={(event) => setInstitutionId(event.target.value)} required />
      </div>
      <div className="actions"><Button>{t('integrationHome.openCase')}</Button></div>
      <p className="submission-note">{t('integrationHome.note')}</p>
    </form>
  </main></div>
}
