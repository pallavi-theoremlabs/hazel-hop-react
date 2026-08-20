import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { createDevCase, createDevClarification, resetDevCase } from '../services/api'
import Button from './Button'

const INITIAL_CASE = {
  case_id: 'HAZEL-TEST-002',
  legal_name: 'Blue Ridge Community Bank',
  fdic_certificate_number: '99999',
  website: 'https://example.com',
  institution_type: 'Bank',
  primary_applicant_email: 'tester@example.com',
}

const INITIAL_CLARIFICATION = {
  request_text: 'Please provide the Board approval page showing the current policy approval date and briefly confirm the annual review cadence.',
  due_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
  document_required: true,
  document_label: 'Replacement policy approval page',
}

export default function DeveloperTestControls({ caseData, refreshCase }) {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const [selectedCaseId, setSelectedCaseId] = useState(caseId)
  const [form, setForm] = useState(INITIAL_CASE)
  const [clarificationForm, setClarificationForm] = useState(INITIAL_CLARIFICATION)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => setSelectedCaseId(caseId), [caseId])

  const updateForm = (event) => {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
  }

  const openNda = () => {
    const nextCaseId = selectedCaseId.trim()
    if (!nextCaseId) return
    navigate(`/case/${nextCaseId}/nda`)
  }

  async function resetCurrentCase() {
    if (!window.confirm(`Reset ${caseId} to NDA Pending? Local responses and document metadata will be cleared.`)) return
    setBusy('reset'); setError(''); setMessage('')
    try {
      await resetDevCase(caseId)
      await refreshCase()
      setMessage('Case reset. No remote Coverbase record was deleted.')
      navigate(`/case/${caseId}/nda`)
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  async function createFreshCase(event) {
    event.preventDefault()
    setBusy('create'); setError(''); setMessage('')
    try {
      const created = await createDevCase(form)
      setSelectedCaseId(created.id)
      navigate(`/case/${created.id}/nda`)
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  async function createSyntheticClarification(event) {
    event.preventDefault()
    setBusy('clarification'); setError(''); setMessage('')
    try {
      const created = await createDevClarification(caseId, clarificationForm)
      await refreshCase()
      setMessage(`Synthetic clarification ${created.id} created locally.`)
      navigate(`/case/${caseId}/review`)
      window.dispatchEvent(new Event('hazel-review:refresh'))
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  return <section className="dev-controls" aria-label="Developer Test Controls">
    <div className="dev-controls-head">
      <div><span className="dev-label">Local development</span><strong>Developer Test Controls</strong></div>
      <Button type="button" variant="quiet" onClick={() => setOpen((current) => !current)}>{open ? 'Hide controls' : 'Show controls'}</Button>
    </div>
    <dl className="dev-debug-grid">
      <div><dt>Hazel case ID</dt><dd>{caseData.id}</dd></div>
      <div><dt>Current stage</dt><dd>{caseData.current_stage}</dd></div>
      <div><dt>Coverbase session ID</dt><dd>{caseData.coverbase_session_id || '—'}</dd></div>
      <div><dt>Coverbase status</dt><dd>{caseData.coverbase_status || '—'}</dd></div>
      <div><dt>Risk Questions submitted</dt><dd>{caseData.risk_questions_submitted_at || '—'}</dd></div>
      <div><dt>eSign eligible</dt><dd>{caseData.esign_eligible ? 'true' : 'false'}</dd></div>
    </dl>
    {open && <div className="dev-controls-body">
      <div className="dev-public-shortcut"><div><strong>Preferred realistic test flow</strong><p>Start with the public inquiry, then use the locally approved RAFA and invitation path.</p></div><Button type="button" variant="secondary" onClick={() => navigate('/submit-interest')}>Start with Submit Interest</Button></div>
      <div className="dev-case-picker">
        <label htmlFor="dev-case-id">Choose current test case</label>
        <input className="input" id="dev-case-id" value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)} />
        <Button type="button" variant="secondary" onClick={openNda}>Open NDA page</Button>
        <Button type="button" variant="quiet" disabled={busy === 'reset'} onClick={resetCurrentCase}>{busy === 'reset' ? 'Resetting…' : 'Reset current case'}</Button>
      </div>
      <form className="dev-create-form" onSubmit={createFreshCase}>
        <strong>Create fresh test case</strong>
        {Object.entries(form).map(([name, value]) => <label key={name}><span>{name.replaceAll('_', ' ')}</span><input className="input" name={name} value={value} onChange={updateForm} required /></label>)}
        <Button disabled={busy === 'create'}>{busy === 'create' ? 'Creating…' : 'Create and open NDA'}</Button>
      </form>
      {caseData.current_stage === 'HAZEL_REVIEW' && <form className="dev-create-form dev-clarification-form" onSubmit={createSyntheticClarification}>
        <strong>Create synthetic review clarification</strong>
        <label className="span-2"><span>Request text</span><textarea className="input" value={clarificationForm.request_text} onChange={(event) => setClarificationForm((current) => ({ ...current, request_text: event.target.value }))} required /></label>
        <label><span>Due date</span><input className="input" type="date" value={clarificationForm.due_at} onChange={(event) => setClarificationForm((current) => ({ ...current, due_at: event.target.value }))} required /></label>
        <label><span>Document label</span><input className="input" value={clarificationForm.document_label} onChange={(event) => setClarificationForm((current) => ({ ...current, document_label: event.target.value }))} disabled={!clarificationForm.document_required} required={clarificationForm.document_required} /></label>
        <label className="choice span-2"><input type="checkbox" checked={clarificationForm.document_required} onChange={(event) => setClarificationForm((current) => ({ ...current, document_required: event.target.checked }))} /><span>Require replacement/supporting evidence</span></label>
        <Button disabled={busy === 'clarification'}>{busy === 'clarification' ? 'Creating…' : 'Create Action Required request'}</Button>
      </form>}
      {message && <div className="alert success">{message}</div>}
      {error && <div className="alert danger">{error}</div>}
    </div>}
  </section>
}
