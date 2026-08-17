import React from "react";
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { getRiskQuestions, saveRiskAnswer, submitRiskQuestions } from '../services/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'
const FILTERS = [
  ['needs-input', 'Needs input'],
  ['review', 'Require review'],
  ['confirmed', 'Confirmed'],
  ['remaining', 'Remaining'],
]
const EMPTY_CONTACT = { name: '', title: '', email: '', phone_number: '', linkedin: '' }

function isEmpty(answer) {
  if (answer?.response_type === 'contacts') {
    const contacts = answer?.response_data?.type === 'contacts' && Array.isArray(answer.response_data.contacts) ? answer.response_data.contacts : []
    return !contacts.some((contact) => contact && ['name', 'email', 'phone_number', 'linkedin'].some((field) => String(contact[field] || '').trim()))
  }
  return !String(answer?.response || '').trim()
    && !(answer?.selected_option_ids || []).length
    && !answer?.response_data
}

function stateFor(answer) {
  if (answer?.response_type === 'contacts' && isEmpty(answer)) return 'needs-input'
  if (answer?.reviewed) return 'confirmed'
  if (isEmpty(answer)) return 'needs-input'
  return 'review'
}

function answerFor(question) {
  return {
    response: question.response ?? '',
    selected_option_ids: question.selected_option_ids ?? null,
    response_data: question.response_data,
    response_type: question.response_type,
    comment: question.comment ?? null,
    reviewed: Boolean(question.reviewed),
  }
}

function suggestedAnswer(question) {
  if (question.original_ai_response != null) return String(question.original_ai_response)
  if (question.response != null && question.response !== '') return String(question.response)
  const selected = new Set(question.original_ai_selected_option_ids || question.selected_option_ids || [])
  return (question.options || []).filter((option) => selected.has(option.id)).map((option) => option.label).join(', ')
}

export default function RiskQuestionsPage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { refreshCase } = useCaseContext()
  const [result, setResult] = useState(null)
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [filter, setFilter] = useState('all')
  const [busy, setBusy] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [pendingSaves, setPendingSaves] = useState(0)
  const [error, setError] = useState('')

  const load = async () => {
    setError('')
    const next = await getRiskQuestions(caseId)
    setResult(next)
    setQuestions(next.questions || [])
    setAnswers(Object.fromEntries((next.questions || []).map((question) => [String(question.question_id), answerFor(question)])))
  }

  useEffect(() => { load().catch((err) => setError(err.message)) }, [caseId])

  const counts = useMemo(() => {
    const states = questions.map((question) => stateFor(answers[String(question.question_id)]))
    const confirmed = states.filter((state) => state === 'confirmed').length
    return {
      'needs-input': states.filter((state) => state === 'needs-input').length,
      review: states.filter((state) => state === 'review').length,
      confirmed,
      remaining: questions.length - confirmed,
    }
  }, [answers, questions])

  const filtered = useMemo(() => questions.filter((question) => {
    const state = stateFor(answers[String(question.question_id)])
    return filter === 'all' || filter === 'remaining' ? filter === 'all' || state !== 'confirmed' : state === filter
  }), [answers, filter, questions])

  const sections = useMemo(() => {
    const groups = new Map()
    filtered.forEach((question) => {
      const label = question.section_name || 'Questionnaire'
      if (!groups.has(label)) groups.set(label, [])
      groups.get(label).push(question)
    })
    return [...groups.entries()]
  }, [filtered])

  function requestFor(answer) {
    const payload = {
      response: answer.response ?? '',
      selected_option_ids: answer.selected_option_ids ?? null,
      comment: answer.comment ?? null,
      reviewed: true,
    }
    if (answer.response_data !== undefined) payload.response_data = answer.response_data
    return payload
  }

  async function update(questionId, patch) {
    const previous = answers[questionId]
    const next = { ...previous, ...patch, reviewed: true }
    if (next.response_type === 'contacts' && isEmpty(next)) {
      setAnswers((current) => ({ ...current, [questionId]: { ...next, reviewed: false } }))
      return
    }
    setAnswers((current) => ({ ...current, [questionId]: next }))
    setError('')
    setPendingSaves((count) => count + 1)
    try {
      const saved = await saveRiskAnswer(caseId, questionId, requestFor(next))
      setQuestions((current) => current.map((question) => question.question_id === questionId ? saved.question : question))
      setAnswers((current) => ({ ...current, [questionId]: answerFor(saved.question) }))
      return saved
    } catch (err) {
      setAnswers((current) => ({ ...current, [questionId]: previous }))
      setError(err.message)
      return null
    } finally {
      setPendingSaves((count) => Math.max(0, count - 1))
    }
  }

  async function saveContacts(questionId, contacts) {
    const normalized = contacts.map((contact) => ({
      name: String(contact.name || '').trim(),
      title: String(contact.title || '').trim(),
      linkedin: String(contact.linkedin || '').trim(),
      email: String(contact.email || '').trim(),
      phone_number: String(contact.phone_number || '').trim(),
    }))
    const response = normalized.map((contact) => [contact.name, contact.email, contact.phone_number, contact.title, contact.linkedin].filter(Boolean).join(' — ')).join('; ')
    const saved = await update(questionId, {
      response,
      response_data: { type: 'contacts', contacts: normalized },
      reviewed: true,
    })
    if (!saved) return false
    await load()
    return true
  }

  async function submitQuestionnaire() {
    if (pendingSaves > 0) {
      setError('Wait for the current Risk Question save to finish before submitting.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await submitRiskQuestions(caseId)
      await refreshCase()
      navigate(`/case/${caseId}/review`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function confirmAll() {
    setBusy(true)
    setError('')
    try {
      for (const question of questions) {
        const id = String(question.question_id)
        const answer = answers[id]
        if (!answer?.reviewed && !(answer?.response_type === 'contacts' && isEmpty(answer))) await update(id, {})
      }
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function selectOne(question, option) {
    const id = String(question.question_id)
    update(id, { response: option.label, selected_option_ids: [option.id] })
  }

  function selectMultiple(question, option, checked) {
    const id = String(question.question_id)
    const selected = new Set(answers[id]?.selected_option_ids || [])
    if (checked) selected.add(option.id)
    else selected.delete(option.id)
    const selectedIds = (question.options || []).map((item) => item.id).filter((optionId) => selected.has(optionId))
    const response = (question.options || []).filter((item) => selected.has(item.id)).map((item) => item.label).join(', ')
    update(id, { response, selected_option_ids: selectedIds })
  }

  if (!result && !error) return <>
    <PageHeader eyebrow="Risk Questions" title="Review suggested answers" description="Loading Coverbase questionnaire responses." action={<StatusBadge tone="warning">Loading</StatusBadge>} />
    <Card title="Loading Risk Questions" className="processing-card"><p className="lead">Hazel is loading the questionnaire generated for this intake session.</p></Card>
  </>

  if (result?.status === 'processing') return <>
    <PageHeader eyebrow="Risk Questions" title="Preparing suggested answers" description="Coverbase is processing the questionnaire for member review." action={<StatusBadge tone="warning">Processing</StatusBadge>} />
    <Card title="Risk Questions are processing" className="processing-card"><p className="lead">Questionnaire responses are not ready yet. Hazel will not substitute fallback questions for this live Coverbase session.</p>{DEV_MODE && <p className="sub">Session: {result.debug?.coverbase_session_id} · Responses: {result.debug?.questionnaire_response_count ?? 0} · Processing: {String(result.debug?.is_processing_questions)}</p>}{error && <div className="alert danger">{error}</div>}<div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button disabled={busy} onClick={async () => { setBusy(true); try { await load() } finally { setBusy(false) } }}>{busy ? 'Checking…' : 'Check again'}</Button></div></Card>
  </>

  if (error && !result) return <>
    <PageHeader eyebrow="Risk Questions" title="Risk Questions unavailable" description="Hazel could not load this Coverbase questionnaire." action={<StatusBadge tone="warning">Action needed</StatusBadge>} />
    <Card title="Unable to load Risk Questions" className="processing-card"><div className="alert danger">{error}</div><div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button onClick={() => load().catch((err) => setError(err.message))}>Try again</Button></div></Card>
  </>

  return <>
    <PageHeader eyebrow="Risk Questions" title="Review suggested answers" description="Review and save each Coverbase answer before certification." action={<span className="autosave-line">Changes save to Coverbase</span>} />
    {DEV_MODE && <div className="alert"><strong>Coverbase debug</strong><br />Session: {result.debug?.coverbase_session_id} · Responses: {result.debug?.questionnaire_response_count} · Processing: {String(result.debug?.is_processing_questions)} · Reviewed: {result.debug?.reviewed_count} · AI generated: {result.debug?.ai_generated_count} · Needs input: {result.debug?.needs_input_count} · Needs review: {result.debug?.needs_review_count}</div>}
    <div className="risk-bulk-actions"><p><strong>Questionnaire review</strong><br /><span className="sub">Review every generated response and provide missing institution answers.</span></p><Button variant="secondary" disabled={busy || !questions.length} onClick={confirmAll}>{busy ? 'Confirming…' : 'Confirm all'}</Button></div>
    <div className="risk-filter-grid" role="group" aria-label="Filter questions by review status">{FILTERS.map(([key, label]) => <button className="risk-filter" type="button" aria-pressed={filter === key} onClick={() => setFilter(key)} key={key}><strong>{counts[key]}</strong><span>{label}</span></button>)}</div>
    <div className="risk-results-summary"><div><strong>{filter === 'all' ? `Showing all ${questions.length} questions` : `Showing ${filtered.length} ${FILTERS.find(([key]) => key === filter)?.[1].toLowerCase()} questions`}</strong><p className="sub">Across {sections.length} section{sections.length === 1 ? '' : 's'}. The first matching section is open below.</p></div>{filter !== 'all' && <button className="text-action" type="button" onClick={() => setFilter('all')}>Clear filter</button>}</div>
    <div className="risk-progress-bar"><div><span>Section progress</span><strong>{counts.confirmed} of {questions.length} reviewed</strong></div><div><span>Questions remaining</span><strong>{counts.remaining}</strong></div><div><span>Current filter</span><strong>{filter === 'all' ? 'All questions' : FILTERS.find(([key]) => key === filter)?.[1]}</strong></div><button className="text-action" type="button" onClick={() => setFilter('all')}>Show all</button></div>
    <div className="risk-section-accordion">{sections.map(([section, items], sectionIndex) => <details className="risk-section-panel" open={sectionIndex === 0} key={section}>
      <summary><div><strong>{sectionIndex + 1}. {section}</strong><span>{items.filter((question) => answers[String(question.question_id)]?.reviewed).length} / {items.length} reviewed</span></div><span className="risk-section-toggle" aria-hidden="true" /></summary>
      <div className="risk-section-panel-body"><p className="sub">Review every suggested response and add applicant context where it will help Hazel.</p><div className="risk-question-list">{items.map((question) => {
        const id = String(question.question_id)
        const answer = answers[id] || {}
        const state = stateFor(answer)
        const type = question.response_type
        const emptyContacts = type === 'contacts' && isEmpty(answer)
        return <article className={`risk-question-card ${state === 'confirmed' ? 'confirmed' : 'attention'}`} key={id}>
          <div className="question-meta"><span className="question-number">Question {questions.indexOf(question) + 1} of {questions.length}</span><StatusBadge tone={state === 'confirmed' ? 'success' : state === 'needs-input' ? 'warning' : 'info'}>{state === 'confirmed' ? 'Confirmed' : state === 'needs-input' ? 'Answer needed' : 'Review required'}</StatusBadge></div>
          <h2>{question.question_text}</h2>
          <div className="question-hierarchy"><div className="question-detail risk-answer-choice"><label className="choice"><input type="checkbox" checked={Boolean(answer.reviewed)} disabled={Boolean(answer.reviewed) || emptyContacts} onChange={(event) => { if (event.target.checked) update(id, { reviewed: true }) }} /><span><span className="question-detail-label">Coverbase suggested answer</span><span>{suggestedAnswer(question) || 'No answer was generated.'}</span></span></label><span className="source-chip suggested">{question.is_ai_generated ? 'Coverbase generated' : 'Member edited'}</span></div>
            <div className="field risk-inline-editor"><label>Institution answer</label>
              {(type === 'select_one' || type === 'single_select') && (question.options || []).map((option) => <label className="choice" key={option.id}><input type="radio" name={`risk-answer-${id}`} checked={(answer.selected_option_ids || []).includes(option.id)} onChange={() => selectOne(question, option)} /><span>{option.label}</span></label>)}
              {(type === 'select_multiple' || type === 'multi_select') && (question.options || []).map((option) => <label className="choice" key={option.id}><input type="checkbox" checked={(answer.selected_option_ids || []).includes(option.id)} onChange={(event) => selectMultiple(question, option, event.target.checked)} /><span>{option.label}</span></label>)}
              {type === 'contacts' && <ContactEditor initialContacts={answer.response_data?.type === 'contacts' ? answer.response_data.contacts : []} onSave={(contacts) => saveContacts(id, contacts)} />}
              {!['select_one', 'single_select', 'select_multiple', 'multi_select', 'contacts'].includes(type) && <textarea id={`risk-answer-${id}`} className="input" value={answer.response || ''} onChange={(event) => setAnswers((current) => ({ ...current, [id]: { ...current[id], response: event.target.value, reviewed: false } }))} onBlur={() => update(id, { response: answers[id]?.response ?? '' })} />}
            </div>
            <details className="reasoning"><summary>Why suggested</summary><p>{question.detailed_reasoning || question.reasoning || 'No member-safe reasoning was returned.'}</p>{question.ai_confidence && <p className="sub">AI confidence: {question.ai_confidence}</p>}</details>
            <div className="field question-comment-field"><label htmlFor={`risk-comment-${id}`}>Applicant comment <span className="muted">(optional)</span></label><textarea id={`risk-comment-${id}`} className="input" placeholder="Add context for Hazel" value={answer.comment || ''} onChange={(event) => setAnswers((current) => ({ ...current, [id]: { ...current[id], comment: event.target.value } }))} onBlur={() => update(id, { comment: answers[id]?.comment ?? '' })} /></div>
          </div><p className="provenance">Generated by Coverbase · reviewed in Hazel</p>
        </article>
      })}</div></div>
    </details>)}</div>
    {counts.remaining === 0 && <section className="card outcome-card risk-ready-panel"><h2>Questionnaire review complete</h2><p className="sub">✓ {counts.confirmed} / {questions.length} Coverbase responses have been reviewed. Submit the questionnaire to begin Hazel/Vantage review.</p><div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button disabled={submitting || pendingSaves > 0} onClick={submitQuestionnaire}>{submitting ? 'Submitting…' : pendingSaves > 0 ? 'Saving responses…' : 'Submit Questionnaire'}</Button></div></section>}
    {error && <div className="alert danger">{error}</div>}
  </>
}

function ContactEditor({ initialContacts, onSave }) {
  const initialSignature = JSON.stringify(initialContacts || [])
  const [contacts, setContacts] = useState(() => normalizeInitialContacts(initialContacts))
  const [validationErrors, setValidationErrors] = useState([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setContacts(normalizeInitialContacts(initialContacts))
    setValidationErrors([])
  }, [initialSignature])

  function updateContact(index, field, value) {
    setContacts((current) => current.map((contact, contactIndex) => contactIndex === index ? { ...contact, [field]: value } : contact))
  }

  function addContact() {
    if (contacts.length >= 6) return
    setContacts((current) => [...current, { ...EMPTY_CONTACT }])
  }

  function removeContact(index) {
    if (contacts.length === 1) return
    setContacts((current) => current.filter((_, contactIndex) => contactIndex !== index))
  }

  async function save() {
    const errors = validateContacts(contacts)
    setValidationErrors(errors)
    if (errors.length) return
    setSaving(true)
    try {
      await onSave(contacts)
    } finally {
      setSaving(false)
    }
  }

  return <div className="risk-contact-editor">
    <p className="hint">Add between 1 and 6 contacts. Coverbase requires a name and either an email address or phone number for each contact.</p>
    {validationErrors.length > 0 && <div className="alert danger risk-contact-errors"><strong>Check the contact information.</strong><ul>{validationErrors.map((message) => <li key={message}>{message}</li>)}</ul></div>}
    <div className="risk-contact-list">{contacts.map((contact, index) => <fieldset className="risk-contact-card" key={index}>
      <legend>Contact {index + 1}</legend>
      <div className="risk-contact-grid">
        <label><span>Name <span className="required">*</span></span><input className="input" value={contact.name} onChange={(event) => updateContact(index, 'name', event.target.value)} autoComplete="name" /></label>
        <label><span>Title / Role</span><input className="input" value={contact.title} onChange={(event) => updateContact(index, 'title', event.target.value)} autoComplete="organization-title" /></label>
        <label><span>Email</span><input className="input" type="email" value={contact.email} onChange={(event) => updateContact(index, 'email', event.target.value)} autoComplete="email" /></label>
        <label><span>Phone number</span><input className="input" type="tel" value={contact.phone_number} onChange={(event) => updateContact(index, 'phone_number', event.target.value)} autoComplete="tel" /></label>
        <label className="span-2"><span>LinkedIn <span className="muted">(optional)</span></span><input className="input" type="url" placeholder="https://linkedin.com/in/name" value={contact.linkedin} onChange={(event) => updateContact(index, 'linkedin', event.target.value)} /></label>
      </div>
      {contacts.length > 1 && <Button type="button" variant="quiet" onClick={() => removeContact(index)}>Remove contact</Button>}
    </fieldset>)}</div>
    <div className="actions risk-contact-actions"><Button type="button" variant="secondary" disabled={contacts.length >= 6 || saving} onClick={addContact}>Add another contact</Button><span className="hint">{contacts.length} of 6 contacts</span><Button type="button" disabled={saving} onClick={save}>{saving ? 'Saving contacts…' : 'Save contacts'}</Button></div>
  </div>
}

function normalizeInitialContacts(initialContacts) {
  if (!Array.isArray(initialContacts) || initialContacts.length === 0) return [{ ...EMPTY_CONTACT }]
  return initialContacts.slice(0, 6).map((contact) => ({
    name: String(contact?.name || ''),
    title: String(contact?.title || ''),
    email: String(contact?.email || ''),
    phone_number: String(contact?.phone_number || ''),
    linkedin: String(contact?.linkedin || ''),
  }))
}

function validateContacts(contacts) {
  const errors = []
  if (!contacts.length || contacts.length > 6) return ['Add between 1 and 6 contacts.']
  contacts.forEach((contact, index) => {
    const label = `Contact ${index + 1}`
    if (!contact.name.trim()) errors.push(`${label}: name is required.`)
    if (!contact.email.trim() && !contact.phone_number.trim()) errors.push(`${label}: provide an email address or phone number.`)
    if (contact.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact.email.trim())) errors.push(`${label}: enter a valid email address.`)
    if (contact.phone_number.trim() && (!/^[0-9+\-\s()]+$/.test(contact.phone_number.trim()) || contact.phone_number.trim().length < 5 || contact.phone_number.trim().length > 20)) errors.push(`${label}: enter a valid phone number between 5 and 20 characters.`)
    if (contact.linkedin.trim() && !contact.linkedin.includes('linkedin.com/in')) errors.push(`${label}: LinkedIn URL must contain linkedin.com/in.`)
  })
  return errors
}
