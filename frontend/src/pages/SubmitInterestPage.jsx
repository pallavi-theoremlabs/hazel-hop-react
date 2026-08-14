import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button'
import StatusBadge from '../components/StatusBadge'
import { lookupBankByFdic, submitInterest } from '../services/api'

const INITIAL_VALUES = {
  legal_name: 'Northstar Community Bank, N.A.',
  fdic_certificate_number: '12001',
  website: 'https://northstar.example',
  institution_type: 'National bank',
  contact_name: 'Jamie Chen',
  contact_title: 'Chief Operating Officer',
  contact_email: 'jamie.chen@northstar.example',
  phone: '(555) 010-0200',
  reason_for_interest: 'Explore Hazel for tokenized deposits, settlement services, and modern payment infrastructure.',
}

const FIELDS = [
  { name: 'legal_name', copyKey: 'legalName', type: 'text', autoComplete: 'organization' },
  { name: 'fdic_certificate_number', copyKey: 'fdic', type: 'text', autoComplete: 'off', inputMode: 'numeric' },
  { name: 'website', copyKey: 'website', type: 'url', autoComplete: 'url' },
  { name: 'institution_type', copyKey: 'institutionType', type: 'select' },
  { name: 'contact_name', copyKey: 'contactName', type: 'text', autoComplete: 'name' },
  { name: 'contact_title', copyKey: 'contactTitle', type: 'text', autoComplete: 'organization-title' },
  { name: 'contact_email', copyKey: 'contactEmail', type: 'email', autoComplete: 'email', inputMode: 'email' },
  { name: 'phone', copyKey: 'phone', type: 'tel', autoComplete: 'tel', inputMode: 'tel' },
]

function validate(values, fields, t) {
  const errors = {}
  for (const field of fields) {
    if (!values[field.name].trim()) errors[field.name] = t('submitInterest.validation.required', { field: field.label.toLowerCase() })
  }
  if (values.fdic_certificate_number && !/^\d{1,10}$/.test(values.fdic_certificate_number)) errors.fdic_certificate_number = t('submitInterest.validation.fdic')
  if (values.website) {
    try {
      const url = new URL(values.website)
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid protocol')
    } catch { errors.website = t('submitInterest.validation.website') }
  }
  if (values.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.contact_email)) errors.contact_email = t('submitInterest.validation.email')
  return errors
}

function InterestField({ field, value, error, onChange, institutionTypes, readOnly = false, children }) {
  const hintId = field.hint ? `${field.name}-hint` : undefined
  const errorId = `${field.name}-error`
  return <div className={`field ${error ? 'has-error' : ''}`}>
    <label htmlFor={field.name}>{field.label} <span className="required" aria-hidden="true">*</span></label>
    {field.hint && <p className="hint" id={hintId}>{field.hint}</p>}
    {field.type === 'select' ? <select className="input" id={field.name} name={field.name} value={value} onChange={onChange} required aria-describedby={errorId}>
      {institutionTypes.map((option) => <option key={option}>{option}</option>)}
    </select> : <input className="input" id={field.name} name={field.name} type={field.type} value={value} onChange={onChange} readOnly={readOnly} required autoComplete={field.autoComplete} inputMode={field.inputMode} aria-describedby={[hintId, errorId].filter(Boolean).join(' ')} aria-invalid={error ? 'true' : undefined} />}
    {error && <p className="field-error" id={errorId}>{error}</p>}
    {children}
  </div>
}

export default function SubmitInterestPage() {
  const { t, i18n } = useTranslation(['public', 'common'])
  const fields = FIELDS.map((field) => {
    const hintKey = `public:submitInterest.fields.${field.copyKey}.hint`
    return {
      ...field,
      label: t(`public:submitInterest.fields.${field.copyKey}.label`),
      hint: i18n.exists(hintKey) ? t(hintKey) : '',
    }
  })
  const institutionTypes = t('public:submitInterest.institutionTypes', { returnObjects: true })
  const navigate = useNavigate()
  const [values, setValues] = useState(INITIAL_VALUES)
  const [errors, setErrors] = useState({})
  const [requestError, setRequestError] = useState('')
  const [busy, setBusy] = useState(false)
  const [lookupBusy, setLookupBusy] = useState(false)
  const [bankMatch, setBankMatch] = useState(null)
  const [verifiedFdic, setVerifiedFdic] = useState('')
  const [result, setResult] = useState(null)

  const update = (event) => {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    if (name === 'fdic_certificate_number') {
      setBankMatch(null)
      setVerifiedFdic('')
    }
    setErrors((current) => {
      if (!(name in current)) return current
      const next = { ...current }
      delete next[name]
      return next
    })
  }

  async function verifyFdic() {
    const certificate = values.fdic_certificate_number.trim()
    if (!/^\d{1,10}$/.test(certificate)) {
      setErrors((current) => ({ ...current, fdic_certificate_number: t('public:submitInterest.validation.fdic') }))
      document.getElementById('fdic_certificate_number')?.focus()
      return
    }
    setLookupBusy(true)
    setRequestError('')
    setBankMatch(null)
    setVerifiedFdic('')
    try {
      setBankMatch(await lookupBankByFdic(certificate))
    } catch (error) {
      setErrors((current) => ({ ...current, fdic_certificate_number: error.message }))
    } finally {
      setLookupBusy(false)
    }
  }

  function useBankMatch() {
    setValues((current) => ({
      ...current,
      legal_name: bankMatch.legal_name,
      fdic_certificate_number: bankMatch.fdic_certificate_number,
    }))
    setVerifiedFdic(bankMatch.fdic_certificate_number)
    setErrors((current) => {
      const next = { ...current }
      delete next.legal_name
      delete next.fdic_certificate_number
      return next
    })
  }

  async function sendInquiry(event) {
    event.preventDefault()
    const nextErrors = validate(values, fields, (key, options) => t(`public:${key}`, options))
    if (verifiedFdic !== values.fdic_certificate_number.trim()) {
      nextErrors.fdic_certificate_number = t('public:submitInterest.validation.verifyFdic')
    }
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      document.getElementById(Object.keys(nextErrors)[0])?.focus()
      return
    }
    setBusy(true)
    setRequestError('')
    try {
      const created = await submitInterest(values)
      setResult(created)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (error) {
      setRequestError(error.message)
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const eligible = result.eligible === true
    return <div className="auth public-interest"><main className="auth-card" id="main">
      <div className={`success-mark ${eligible ? '' : 'warning'}`} aria-hidden="true">{eligible ? '✓' : '!'}</div>
      <StatusBadge tone={eligible ? 'success' : 'warning'}>{t(`public:submitInterest.${eligible ? 'eligibleStatus' : 'rejectedStatus'}`)}</StatusBadge>
      <h1>{t('public:submitInterest.completeTitle')}</h1><p className="lead">{t(`public:submitInterest.${eligible ? 'eligibleDescription' : 'rejectedDescription'}`)}</p>
      <div className="alert"><strong>{t('public:submitInterest.reference', { reference: result.inquiry_reference })}</strong><br />{t('public:submitInterest.hazelOnly')}</div>
      <section className="local-dev-simulation" aria-label="Local development workflow simulation">
        <span className="dev-label">{t('public:submitInterest.devSimulation')}</span><h2>{t(`public:submitInterest.${eligible ? 'devTitle' : 'rejectedDevTitle'}`)}</h2>
        <div className="task-list">
          <div className={`task ${eligible ? 'complete' : ''}`}><span className="task-icon">{eligible ? '✓' : '!'}</span><div><strong>{t(`public:submitInterest.${eligible ? 'rafaTitle' : 'rafaRejectedTitle'}`)}</strong><p>{t(`public:submitInterest.${eligible ? 'rafaDescription' : 'rafaRejectedDescription'}`, { score: result.rafa_score })}</p></div></div>
          <div className={`task ${eligible ? 'complete' : ''}`}><span className="task-icon">{eligible ? '✓' : '—'}</span><div><strong>{t(`public:submitInterest.${eligible ? 'invitationTitle' : 'invitationNotCreatedTitle'}`)}</strong><p>{t(`public:submitInterest.${eligible ? 'invitationDescription' : 'invitationNotCreatedDescription'}`)}</p></div></div>
        </div>
        {eligible && <div className="actions"><Button onClick={() => navigate(result.next_path)}>{t('public:submitInterest.openNda')}</Button></div>}
      </section>
    </main></div>
  }

  return <div className="auth public-interest"><main className="auth-card" id="main">
    <p className="eyebrow">{t('public:submitInterest.eyebrow')}</p><h1>{t('public:submitInterest.title')}</h1><p className="lead">{t('public:submitInterest.description')}</p>
    {Object.keys(errors).length > 0 && <div className="error-summary" role="alert"><h2>{t('public:submitInterest.errorTitle')}</h2><ul>{Object.entries(errors).map(([name, message]) => <li key={name}><a href={`#${name}`}>{message}</a></li>)}</ul></div>}
    {requestError && <div className="alert danger" role="alert">{requestError}</div>}
    <form className="interest-form" onSubmit={sendInquiry} noValidate><div className="form-grid">{fields.map((field) => <InterestField key={field.name} field={field} value={values[field.name]} error={errors[field.name]} onChange={update} institutionTypes={institutionTypes} readOnly={field.name === 'legal_name' && verifiedFdic === values.fdic_certificate_number}>
      {field.name === 'fdic_certificate_number' && <div className="fdic-lookup">
        <Button type="button" variant="secondary" disabled={lookupBusy || busy} onClick={verifyFdic}>{lookupBusy ? t('public:submitInterest.lookup.checking') : t('public:submitInterest.lookup.action')}</Button>
        {bankMatch && <div className="alert bank-match"><strong>{bankMatch.legal_name}</strong><br /><span>{t('public:submitInterest.lookup.details', { fdic: bankMatch.fdic_certificate_number, rssd: bankMatch.rssd_id || t('public:submitInterest.lookup.notAvailable') })}</span>{verifiedFdic !== bankMatch.fdic_certificate_number ? <div className="actions"><Button type="button" onClick={useBankMatch}>{t('public:submitInterest.lookup.useMatch')}</Button></div> : <p className="hint bank-match-confirmed">✓ {t('public:submitInterest.lookup.confirmed')}</p>}</div>}
      </div>}
    </InterestField>)}
      <div className="field span-2"><label htmlFor="reason_for_interest">{t('public:submitInterest.reasonLabel')} <span className="muted small">{t('public:submitInterest.optional')}</span></label><textarea className="input" id="reason_for_interest" name="reason_for_interest" value={values.reason_for_interest} onChange={update} autoComplete="off" /></div>
    </div><div className="actions"><Button disabled={busy || lookupBusy}>{busy ? t('public:submitInterest.sending') : t('public:submitInterest.submit')}</Button></div><p className="submission-note">{t('public:submitInterest.requiredNote')}</p></form>
  </main></div>
}
