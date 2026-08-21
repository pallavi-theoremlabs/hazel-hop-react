import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button'
import StatusBadge from '../components/StatusBadge'
import { lookupBankByFdic, submitInterest } from '../services/api'

const DEV_MODE = import.meta.env.DEV && import.meta.env.VITE_DEV_MODE === 'true'

const EMPTY_VALUES = {
  institution_type: 'Bank',
  legal_name: '',
  fdic_certificate_number: '',
  website: '',
  institution_location: '',
  contact_name: '',
  contact_title: '',
  contact_email: '',
  phone: '',
}

const DEV_VALUES = {
  ...EMPTY_VALUES,
  fdic_certificate_number: '12001',
  website: 'https://northstar.example',
  contact_name: 'Jamie Chen',
  contact_title: 'Chief Operating Officer',
  contact_email: 'jamie.chen@northstar.example',
  phone: '(555) 010-0200',
}

const CONTACT_FIELDS = [
  { name: 'contact_name', copyKey: 'contactName', requiredKey: 'contactNameRequired', type: 'text', autoComplete: 'name' },
  { name: 'contact_title', copyKey: 'contactTitle', requiredKey: 'contactTitleRequired', type: 'text', autoComplete: 'organization-title' },
  { name: 'contact_email', copyKey: 'contactEmail', requiredKey: 'contactEmailRequired', type: 'email', autoComplete: 'email', inputMode: 'email' },
  { name: 'phone', copyKey: 'phone', requiredKey: 'phoneRequired', type: 'tel', autoComplete: 'tel', inputMode: 'tel' },
]

function fieldCopy(field, t, i18n) {
  const hintKey = `public:submitInterest.fields.${field.copyKey}.hint`
  return {
    ...field,
    label: t(`public:submitInterest.fields.${field.copyKey}.label`),
    hint: i18n.exists(hintKey) ? t(hintKey) : '',
  }
}

function validate(values, bankMatch, fields, t) {
  const errors = {}
  if (values.institution_type === 'Bank') {
    if (!values.fdic_certificate_number.trim()) errors.institution_search = t('submitInterest.validation.fdicRequired')
    else if (!/^\d{1,10}$/.test(values.fdic_certificate_number.trim())) errors.institution_search = t('submitInterest.validation.fdic')
    else if (!bankMatch || bankMatch.fdic_certificate_number !== values.fdic_certificate_number.trim()) errors.institution_search = t('submitInterest.validation.verifyFdic')
    if (bankMatch && !values.website.trim()) errors.website = t('submitInterest.validation.websiteRequired')
  }
  for (const field of fields) {
    if (!values[field.name].trim()) errors[field.name] = field.requiredKey
      ? t(`submitInterest.validation.${field.requiredKey}`)
      : t('submitInterest.validation.required', { field: field.label.toLowerCase() })
  }
  if (values.website) {
    try {
      const url = new URL(values.website)
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid protocol')
    } catch { errors.website = t('submitInterest.validation.website') }
  }
  if (values.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.contact_email)) errors.contact_email = t('submitInterest.validation.email')
  return errors
}

function InterestField({ field, value, error, onChange, required = true, className = '' }) {
  const hintId = field.hint ? `${field.name}-hint` : undefined
  const errorId = `${field.name}-error`
  return <div className={`field ${className} ${error ? 'has-error' : ''}`.trim()}>
    <label htmlFor={field.name}>{field.label} {required ? <span className="required" aria-hidden="true">*</span> : <span className="muted small">Optional</span>}</label>
    {field.hint && <p className="hint" id={hintId}>{field.hint}</p>}
    <input className="input" id={field.name} name={field.name} type={field.type} value={value} onChange={onChange} required={required} autoComplete={field.autoComplete} inputMode={field.inputMode} aria-describedby={[hintId, error ? errorId : ''].filter(Boolean).join(' ') || undefined} aria-invalid={error ? 'true' : undefined} />
    {error && <p className="field-error" id={errorId}>{error}</p>}
  </div>
}

export default function SubmitInterestPage() {
  const { t, i18n } = useTranslation(['public', 'common'])
  const navigate = useNavigate()
  const contactFields = CONTACT_FIELDS.map((field) => fieldCopy(field, t, i18n))
  const institutionTypes = t('public:submitInterest.institutionTypes', { returnObjects: true })
  const [values, setValues] = useState(DEV_MODE ? DEV_VALUES : EMPTY_VALUES)
  const [errors, setErrors] = useState({})
  const [requestError, setRequestError] = useState('')
  const [busy, setBusy] = useState(false)
  const [lookupBusy, setLookupBusy] = useState(false)
  const [bankMatch, setBankMatch] = useState(null)
  const [result, setResult] = useState(null)

  const clearError = (name) => setErrors((current) => {
    if (!(name in current)) return current
    const next = { ...current }
    delete next[name]
    return next
  })

  const update = (event) => {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    clearError(name)
  }

  const updateCertificate = (event) => {
    const certificate = event.target.value
    setValues((current) => ({ ...current, fdic_certificate_number: certificate, legal_name: '' }))
    setBankMatch(null)
    clearError('institution_search')
  }

  const updateInstitutionType = (event) => {
    const institutionType = event.target.value
    setValues((current) => ({
      ...current,
      institution_type: institutionType,
      legal_name: '',
      fdic_certificate_number: '',
      website: '',
      institution_location: '',
    }))
    setBankMatch(null)
    setRequestError('')
    setErrors({})
  }

  async function verifyFdic() {
    const certificate = values.fdic_certificate_number.trim()
    if (!certificate) {
      setErrors((current) => ({ ...current, institution_search: t('public:submitInterest.validation.fdicRequired') }))
      document.getElementById('institution_search')?.focus()
      return
    }
    if (!/^\d{1,10}$/.test(certificate)) {
      setErrors((current) => ({ ...current, institution_search: t('public:submitInterest.validation.fdic') }))
      document.getElementById('institution_search')?.focus()
      return
    }
    setLookupBusy(true)
    setRequestError('')
    setBankMatch(null)
    try {
      const match = await lookupBankByFdic(certificate)
      setBankMatch(match)
      setValues((current) => ({
        ...current,
        legal_name: match.legal_name,
        fdic_certificate_number: match.fdic_certificate_number,
        institution_location: match.headquarters || '',
      }))
      clearError('institution_search')
    } catch (error) {
      const messageKey = error.status === 404 ? 'lookup.notFound' : 'lookup.unavailable'
      setErrors((current) => ({ ...current, institution_search: t(`public:submitInterest.${messageKey}`) }))
    } finally {
      setLookupBusy(false)
    }
  }

  function changeInstitution() {
    setBankMatch(null)
    setValues((current) => ({ ...current, legal_name: '', fdic_certificate_number: '', institution_location: '' }))
    clearError('institution_search')
    window.setTimeout(() => document.getElementById('institution_search')?.focus(), 0)
  }

  async function sendInquiry(event) {
    event.preventDefault()
    if (values.institution_type !== 'Bank') return
    const nextErrors = validate(values, bankMatch, contactFields, (key, options) => t(`public:${key}`, options))
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      document.getElementById(Object.keys(nextErrors)[0])?.focus()
      return
    }
    setBusy(true)
    setRequestError('')
    try {
      const created = await submitInterest({
        legal_name: bankMatch.legal_name,
        fdic_certificate_number: bankMatch.fdic_certificate_number,
        website: values.website.trim(),
        institution_type: values.institution_type,
        contact_name: values.contact_name.trim(),
        contact_title: values.contact_title.trim(),
        contact_email: values.contact_email.trim(),
        phone: values.phone.trim(),
        reason_for_interest: '',
      })
      setResult(created)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch {
      setRequestError(t('public:submitInterest.submissionError'))
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    return <div className="auth public-interest"><main className="auth-card" id="main">
      <div className="success-mark" aria-hidden="true">✓</div>
      <StatusBadge tone="success">{t('public:submitInterest.receivedStatus')}</StatusBadge>
      <h1>{t('public:submitInterest.completeTitle')}</h1>
      <p className="lead">{t('public:submitInterest.completeDescription')}</p>
      {DEV_MODE && result.eligible && result.next_path && <section className="local-dev-simulation" aria-label={t('public:submitInterest.devSimulation')}>
        <span className="dev-label">{t('public:submitInterest.devSimulation')}</span>
        <h2>{t('public:submitInterest.devTitle')}</h2>
        <p className="hint">{t('public:submitInterest.devDescription')}</p>
        <div className="actions"><Button onClick={() => navigate(`${result.next_path}?dev_institution_id=${encodeURIComponent(result.institution_id)}`)}>{t('public:submitInterest.openNda')}</Button></div>
      </section>}
    </main></div>
  }

  const unsupported = values.institution_type !== 'Bank'
  const websiteField = fieldCopy({ name: 'website', copyKey: 'website', type: 'url', autoComplete: 'url' }, t, i18n)

  return <div className="auth public-interest"><main className="auth-card" id="main">
    <p className="eyebrow">{t('public:submitInterest.eyebrow')}</p>
    <h1>{t('public:submitInterest.title')}</h1>
    <p className="lead">{t('public:submitInterest.description')}</p>
    {Object.keys(errors).length > 0 && <div className="error-summary" role="alert"><h2>{t('public:submitInterest.errorTitle')}</h2><ul>{Object.entries(errors).map(([name, message]) => <li key={name}><a href={`#${name}`}>{message}</a></li>)}</ul></div>}
    {requestError && <div className="alert danger" role="alert">{requestError}</div>}
    <form className="interest-form" onSubmit={sendInquiry} noValidate>
      <div className="form-grid">
        <div className="field span-2">
          <label htmlFor="institution_type">{t('public:submitInterest.fields.institutionType.label')} <span className="required" aria-hidden="true">*</span></label>
          <select className="input" id="institution_type" name="institution_type" value={values.institution_type} onChange={updateInstitutionType} required>
            {institutionTypes.map((option) => <option key={option}>{option}</option>)}
          </select>
        </div>

        {unsupported ? <>
          <InterestField field={{ name: 'legal_name', type: 'text', autoComplete: 'organization', label: values.institution_type === 'Other' ? t('public:submitInterest.fields.organizationName.label') : t('public:submitInterest.fields.institutionName.label') }} value={values.legal_name} error={errors.legal_name} onChange={update} />
          <InterestField field={{ name: 'institution_location', type: 'text', autoComplete: 'address-level2', label: t('public:submitInterest.fields.institutionLocation.label') }} value={values.institution_location} error={errors.institution_location} onChange={update} required={false} />
          <div className="alert warning span-2 unsupported-institution" role="status"><strong>{t('public:submitInterest.unsupportedTitle')}</strong><br />{t('public:submitInterest.unsupportedDescription')}</div>
        </> : <>
          <div className={`field span-2 institution-search-field ${errors.institution_search ? 'has-error' : ''}`}>
            <label htmlFor="institution_search">{t('public:submitInterest.lookup.label')} <span className="required" aria-hidden="true">*</span></label>
            <p className="hint institution-search-helper" id="institution-search-hint">{t('public:submitInterest.lookup.hint')}</p>
            <div className="institution-search-control">
              <input className="input" id="institution_search" name="institution_search" type="search" value={values.fdic_certificate_number} onChange={updateCertificate} placeholder={t('public:submitInterest.lookup.placeholder')} autoComplete="off" inputMode="numeric" aria-describedby={`institution-search-hint${errors.institution_search ? ' institution-search-error' : ''}`} aria-invalid={errors.institution_search ? 'true' : undefined} />
              <Button type="button" variant="secondary" disabled={lookupBusy || busy} onClick={verifyFdic}>{lookupBusy ? t('public:submitInterest.lookup.checking') : t('public:submitInterest.lookup.action')}</Button>
            </div>
            <div className="institution-search-state" role="status" aria-live="polite">{lookupBusy && <><span className="spinner" aria-hidden="true" /><span>{t('public:submitInterest.lookup.searching')}</span></>}</div>
            {errors.institution_search && <p className="field-error" id="institution-search-error">{errors.institution_search}</p>}
          </div>

          {bankMatch && <section className="card span-2 selected-institution" aria-labelledby="selected-institution-heading">
            <div className="selected-institution-head"><div className="selected-institution-title"><h2 id="selected-institution-heading">{t('public:submitInterest.lookup.selectedTitle')}</h2><strong className="selected-institution-name">{bankMatch.legal_name}</strong>{bankMatch.headquarters && <p className="selected-institution-sub">{bankMatch.headquarters}</p>}</div><StatusBadge tone="success">{t('public:submitInterest.lookup.validated')}</StatusBadge></div>
            <dl className="selected-institution-meta"><div><dt>{t('public:submitInterest.lookup.registry')}</dt><dd>{t('public:submitInterest.lookup.fdicRegistry')}</dd></div><div><dt>{t('public:submitInterest.fields.fdic.label')}</dt><dd>{bankMatch.fdic_certificate_number}</dd></div></dl>
            <div className="actions"><Button type="button" variant="secondary" onClick={changeInstitution}>{t('public:submitInterest.lookup.change')}</Button></div>
          </section>}

          {bankMatch && <InterestField className="span-2" field={websiteField} value={values.website} error={errors.website} onChange={update} />}
        </>}

        {contactFields.map((field) => <InterestField key={field.name} field={field} value={values[field.name]} error={errors[field.name]} onChange={update} />)}
      </div>
      <div className="actions"><Button disabled={busy || lookupBusy || unsupported}>{busy ? t('public:submitInterest.sending') : t('public:submitInterest.submit')}</Button></div>
      <p className="submission-note">{t('public:submitInterest.requiredNote')}</p>
    </form>
  </main></div>
}
