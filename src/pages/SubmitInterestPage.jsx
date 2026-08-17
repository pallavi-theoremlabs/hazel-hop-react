import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button'
import StatusBadge from '../components/StatusBadge'
import { submitInterest } from '../services/api'

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

const INSTITUTION_TYPES = [
  'National bank',
  'State member bank',
  'State nonmember bank',
  'Savings association',
  'Credit union',
  'Other',
]

const FIELDS = [
  { name: 'legal_name', label: 'Legal institution name', type: 'text', autoComplete: 'organization', hint: 'Use the institution’s complete legal name.' },
  { name: 'fdic_certificate_number', label: 'FDIC certificate number', type: 'text', autoComplete: 'off', inputMode: 'numeric', hint: 'Hazel uses this number to match your institution to authoritative FDIC records.' },
  { name: 'website', label: 'Institution website', type: 'url', autoComplete: 'url' },
  { name: 'institution_type', label: 'Institution type', type: 'select' },
  { name: 'contact_name', label: 'Contact name', type: 'text', autoComplete: 'name', hint: 'Enter the person Hazel should contact about this inquiry.' },
  { name: 'contact_title', label: 'Role / title', type: 'text', autoComplete: 'organization-title' },
  { name: 'contact_email', label: 'Business email', type: 'email', autoComplete: 'email', inputMode: 'email', hint: 'Hazel will send the inquiry response to this address.' },
  { name: 'phone', label: 'Phone', type: 'tel', autoComplete: 'tel', inputMode: 'tel' },
]

function validate(values) {
  const errors = {}
  for (const field of FIELDS) {
    if (!values[field.name].trim()) errors[field.name] = `Enter the ${field.label.toLowerCase()}.`
  }
  if (values.fdic_certificate_number && !/^\d{1,10}$/.test(values.fdic_certificate_number)) errors.fdic_certificate_number = 'Enter the FDIC certificate number using digits only.'
  if (values.website) {
    try {
      const url = new URL(values.website)
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid protocol')
    } catch { errors.website = 'Enter a valid institution website.' }
  }
  if (values.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.contact_email)) errors.contact_email = 'Enter a valid business email address.'
  return errors
}

function InterestField({ field, value, error, onChange }) {
  const hintId = field.hint ? `${field.name}-hint` : undefined
  const errorId = `${field.name}-error`
  return <div className={`field ${error ? 'has-error' : ''}`}>
    <label htmlFor={field.name}>{field.label} <span className="required" aria-hidden="true">*</span></label>
    {field.hint && <p className="hint" id={hintId}>{field.hint}</p>}
    {field.type === 'select' ? <select className="input" id={field.name} name={field.name} value={value} onChange={onChange} required aria-describedby={errorId}>
      {INSTITUTION_TYPES.map((option) => <option key={option}>{option}</option>)}
    </select> : <input className="input" id={field.name} name={field.name} type={field.type} value={value} onChange={onChange} required autoComplete={field.autoComplete} inputMode={field.inputMode} aria-describedby={[hintId, errorId].filter(Boolean).join(' ')} aria-invalid={error ? 'true' : undefined} />}
    {error && <p className="field-error" id={errorId}>{error}</p>}
  </div>
}

function ReviewRow({ label, value, onChange }) {
  return <div className="review-row"><div><dt>{label}</dt><dd>{value}</dd></div><button type="button" className="text-action" onClick={onChange} aria-label={`Change ${label}`}>Change</button></div>
}

export default function SubmitInterestPage() {
  const navigate = useNavigate()
  const [values, setValues] = useState(INITIAL_VALUES)
  const [step, setStep] = useState('form')
  const [errors, setErrors] = useState({})
  const [requestError, setRequestError] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const update = (event) => {
    const { name, value } = event.target
    setValues((current) => ({ ...current, [name]: value }))
    setErrors((current) => ({ ...current, [name]: '' }))
  }

  function review(event) {
    event.preventDefault()
    const nextErrors = validate(values)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      document.getElementById(Object.keys(nextErrors)[0])?.focus()
      return
    }
    setStep('review')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function edit(fieldName) {
    setStep('form')
    window.requestAnimationFrame(() => document.getElementById(fieldName)?.focus())
  }

  async function sendInquiry() {
    setBusy(true); setRequestError('')
    try {
      const created = await submitInterest(values)
      setResult(created)
      setStep('complete')
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (error) { setRequestError(error.message) } finally { setBusy(false) }
  }

  if (step === 'complete') return <div className="auth public-interest"><main className="auth-card" id="main">
    <div className="success-mark" aria-hidden="true">✓</div><StatusBadge tone="success">Inquiry received</StatusBadge>
    <h1>Thank you.</h1><p className="lead">Hazel will review your institution’s eligibility and contact the approved representative with next steps.</p>
    <div className="alert"><strong>Reference {result.inquiry_reference}</strong><br />Your Hazel inquiry and institution record have been created. No Coverbase intake was created during Submit Interest.</div>
    <section className="local-dev-simulation" aria-label="Local development workflow simulation">
      <span className="dev-label">Local development simulation</span><h2>Continue the approved test path</h2>
      <div className="task-list"><div className="task complete"><span className="task-icon">✓</span><div><strong>RAFA screening approved</strong><p>Mocked locally for workflow testing.</p></div></div><div className="task complete"><span className="task-icon">✓</span><div><strong>Invitation approved</strong><p>Mocked locally; the private HOP case starts at NDA.</p></div></div></div>
      <div className="actions"><Button onClick={() => navigate(result.next_path)}>Open NDA</Button></div>
    </section>
  </main></div>

  if (step === 'review') return <div className="auth public-interest"><main className="auth-card" id="main">
    <p className="eyebrow">Institution inquiry</p><h1>Check your answers</h1><p className="lead">Confirm these details before sending the inquiry to Hazel.</p>
    <dl className="review-list">{FIELDS.map((field) => <ReviewRow key={field.name} label={field.label} value={values[field.name]} onChange={() => edit(field.name)} />)}{values.reason_for_interest && <ReviewRow label="Reason for interest" value={values.reason_for_interest} onChange={() => edit('reason_for_interest')} />}</dl>
    {requestError && <div className="alert danger">{requestError}</div>}
    <div className="actions"><Button disabled={busy} onClick={sendInquiry}>{busy ? 'Sending inquiry…' : 'Send inquiry to Hazel'}</Button><Button variant="secondary" disabled={busy} onClick={() => setStep('form')}>Back</Button></div>
    <p className="submission-note">Submitting creates a Hazel inquiry only. For local development, RAFA and invitation approval are simulated before the NDA.</p>
  </main></div>

  return <div className="auth public-interest"><main className="auth-card" id="main">
    <p className="eyebrow">For regulated institutions</p><h1>Express interest</h1><p className="lead">Send Hazel the core institution and representative details needed to review your inquiry. This does not create a portal account.</p>
    {Object.keys(errors).length > 0 && <div className="error-summary" role="alert"><h2>There is a problem</h2><ul>{Object.entries(errors).map(([name, message]) => <li key={name}><a href={`#${name}`}>{message}</a></li>)}</ul></div>}
    <form className="interest-form" onSubmit={review} noValidate><div className="form-grid">{FIELDS.map((field) => <InterestField key={field.name} field={field} value={values[field.name]} error={errors[field.name]} onChange={update} />)}
      <div className="field span-2"><label htmlFor="reason_for_interest">Reason for interest <span className="muted small">Optional</span></label><textarea className="input" id="reason_for_interest" name="reason_for_interest" value={values.reason_for_interest} onChange={update} autoComplete="off" /></div>
    </div><div className="actions"><Button>Submit interest</Button></div><p className="submission-note">Required fields are marked with an asterisk. Local development only—submission creates a synthetic Hazel case.</p></form>
  </main></div>
}
