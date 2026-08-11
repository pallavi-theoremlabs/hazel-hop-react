import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import useCoverbaseReviewStatus from '../hooks/useCoverbaseReviewStatus'
import { saveClarificationDraft, submitClarificationResponse, uploadClarificationDocument } from '../services/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'

const REVIEW_CONTENT = {
  under_review: {
    label: 'Under Hazel/Vantage review',
    tone: 'info',
    description: 'Your certified submission is with the Hazel/Vantage review team.',
    expected: 'Hazel will notify your institution when the review decision is available.',
  },
  response_submitted: {
    label: 'Under Hazel/Vantage review',
    tone: 'info',
    description: 'Your additional information response was submitted in Hazel and review has resumed.',
    expected: 'No further action is currently required unless the Hazel Review Team contacts you.',
  },
  approved: {
    label: 'Review Complete',
    tone: 'success',
    description: 'Hazel has approved your institution to continue to eSign.',
    expected: 'Continue to eSign.',
  },
  rejected: {
    label: 'Rejected',
    tone: 'warning',
    description: 'The review did not approve this onboarding intake.',
    expected: 'Onboarding has not advanced, and eSign is not available.',
  },
  partial: {
    label: 'Needs explicit handling',
    tone: 'warning',
    description: 'Coverbase returned a partial decision that Hazel does not treat as approval.',
    expected: 'The case remains unresolved and will not advance automatically.',
  },
}

export default function HazelReviewPage() {
  const { caseData, refreshCase } = useCaseContext()
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { data, error, isRefreshing, refresh } = useCoverbaseReviewStatus(caseId, refreshCase)
  const coverbaseStatus = data?.coverbase_status || caseData.coverbase_status || 'unknown'
  const reviewState = data?.review_state || caseData.hazel_review_status || 'under_review'
  const clarification = data?.current_clarification

  if (reviewState === 'action_required' && clarification) {
    return <ClarificationRequest
      caseId={caseId}
      clarification={clarification}
      historyEvents={data?.history_events || []}
      integrationError={data?.coverbase_status_sync_error}
      loadError={error}
      refresh={refresh}
      refreshCase={refreshCase}
    />
  }

  const content = REVIEW_CONTENT[reviewState] || REVIEW_CONTENT.under_review
  const esignEligible = data?.esign_eligible ?? caseData.esign_eligible ?? false
  const decisionReached = ['approved', 'rejected', 'partial'].includes(reviewState)
  const responseSubmitted = reviewState === 'response_submitted'

  return <>
    <PageHeader eyebrow="Hazel Review" title={content.label} description={content.description} action={<StatusBadge tone={content.tone}>{content.label}</StatusBadge>} />
    <div className="hazel-review-layout">
      <Card title="Status and next step">
        <div className="case-facts"><div><span>Status</span><strong>{content.label}</strong></div><div><span>Submitted</span><strong>{caseData.risk_questions_submitted_at ? new Date(caseData.risk_questions_submitted_at).toLocaleString() : 'Pending'}</strong></div><div><span>Last update</span><strong>{caseData.updated_at ? new Date(caseData.updated_at).toLocaleString() : 'Just now'}</strong></div><div><span>eSign eligibility</span><strong>{esignEligible ? 'Eligible' : 'Not eligible'}</strong></div><div><span>Expected next step</span><strong>{content.expected}</strong></div></div>
        {responseSubmitted && <div className="alert success"><strong>Response submitted.</strong><br />Your response is stored in Hazel. Coverbase response synchronization is pending a supported integration.</div>}
        {reviewState === 'rejected' && <div className="alert warning"><strong>Onboarding did not advance.</strong><br />This case is not eligible for eSign.</div>}
        {reviewState === 'partial' && <div className="alert warning"><strong>Explicit Hazel handling is required.</strong><br />A partial Coverbase decision does not count as approval.</div>}
        {reviewState === 'approved' && <div className="alert success"><strong>Review Complete.</strong><br />Hazel has approved your institution to continue to eSign.</div>}
        {data?.coverbase_status_sync_error && <div className="alert warning">{data.coverbase_status_sync_error}</div>}
        {error && <div className="alert danger"><strong>Status refresh failed.</strong><br />{error}</div>}
        {DEV_MODE && <div className="alert"><strong>Local review debug</strong><br />Coverbase session: {data?.coverbase_session_id || caseData.coverbase_session_id || '—'} · Coverbase status: {coverbaseStatus} · Hazel review state: {reviewState} · Hazel stage: {data?.current_stage || caseData.current_stage} · Clarification sync: {data?.coverbase_sync_status || '—'} · eSign eligible: {String(esignEligible)}</div>}
        <div className="review-timeline" aria-label="Hazel Review timeline">
          <Timeline state="complete" title="Certified submission received" copy="Your reviewed Risk Questions were submitted to Coverbase." />
          {responseSubmitted && <Timeline state="complete" title="Response submitted" copy="Your additional information response was saved in Hazel." />}
          <Timeline state={decisionReached ? 'complete' : 'current'} title={responseSubmitted ? 'Review resumed' : 'Hazel/Vantage review'} copy={decisionReached ? 'The internal Coverbase decision has been recorded.' : content.description} />
          <Timeline state={decisionReached ? 'current' : ''} title="Review decision" copy={decisionReached ? content.expected : 'Waiting for Vantage to approve or reject the intake in Coverbase.'} />
        </div>
        <div className="review-bottom-actions"><div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button variant="secondary" disabled={isRefreshing} onClick={() => refresh().catch(() => {})}>{isRefreshing ? 'Refreshing…' : 'Refresh status'}</Button>{reviewState === 'approved' && <Button onClick={() => window.alert('Your institution is eligible for eSign. The eSign integration is not enabled in this local environment.')}>Continue to eSign</Button>}</div></div>
      </Card>
    </div>
  </>
}

function ClarificationRequest({ caseId, clarification, historyEvents, integrationError, loadError, refresh, refreshCase }) {
  const [response, setResponse] = useState(clarification.member_response || '')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setResponse(clarification.member_response || '')
  }, [clarification.id, clarification.updated_at])

  async function reload() {
    await refresh()
    await refreshCase()
  }

  async function saveDraft() {
    setBusy('draft'); setError(''); setMessage('')
    try {
      await saveClarificationDraft(caseId, clarification.id, response)
      setMessage('Draft saved in Hazel. It has not been submitted.')
      await reload()
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  async function submitResponse() {
    setBusy('submit'); setError(''); setMessage('')
    try {
      await saveClarificationDraft(caseId, clarification.id, response)
      await submitClarificationResponse(caseId, clarification.id)
      await reload()
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  async function uploadDocument(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy('document'); setError(''); setMessage('')
    try {
      const result = await uploadClarificationDocument(caseId, clarification.id, file)
      setMessage(result.document.integration_warning || 'Replacement document uploaded to Hazel.')
      await reload()
    } catch (err) { setError(err.message) } finally { setBusy(''); event.target.value = '' }
  }

  const uploaded = clarification.uploaded_document
  const dueDate = formatDate(clarification.due_at)
  const canSubmit = response.trim() && (!clarification.document_required || uploaded)

  return <>
    <PageHeader eyebrow="Hazel Review" title="Action required — additional information requested" description={`Respond inside Hazel by ${dueDate}.`} action={<StatusBadge tone="warning">Action required</StatusBadge>} />
    <div className="hazel-clarification-layout">
      <Card title="Request from the Hazel Review Team">
        <div className="case-facts"><div><span>Requested by</span><strong>{clarification.requested_by}</strong></div><div><span>Due date</span><strong>{dueDate}</strong></div></div>
        <div className="alert warning"><strong>Additional information requested</strong><br />{clarification.request_text}</div>
        <div className="field"><label htmlFor="clarification-response">Your response</label><textarea id="clarification-response" className="input" placeholder="Add an external-safe response for the Hazel Review Team" value={response} onChange={(event) => setResponse(event.target.value)} /><p className="hint">Drafts are saved in Hazel and are not submitted until you choose Submit response.</p></div>
        {clarification.document_required && <div className="doc-card clarification-document"><div className="doc-head"><div><h3>{clarification.document_label || 'Requested supporting document'}</h3><p className="sub">Upload the requested evidence through Hazel. Do not include examination materials.</p></div><StatusBadge tone={uploaded ? 'info' : 'warning'}>{uploaded ? 'Uploaded' : 'Resubmission required'}</StatusBadge></div>{uploaded && <div className="clarification-file"><strong>{uploaded.original_name}</strong><span>{Math.max(1, Math.round(uploaded.size_bytes / 1024))} KB · Stored in Hazel</span></div>}<div className="actions"><label className={`btn secondary clarification-upload-button ${busy ? 'disabled' : ''}`}>{busy === 'document' ? 'Uploading…' : uploaded ? 'Replace document' : 'Upload replacement'}<input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={uploadDocument} /></label></div></div>}
        {message && <div className="alert success">{message}</div>}
        {(error || loadError) && <div className="alert danger">{error || loadError}</div>}
        {integrationError && <div className="alert warning">{integrationError}</div>}
        {DEV_MODE && <p className="hint">Clarification ID: {clarification.id} · Source: {clarification.source} · Coverbase clarification sync: {clarification.coverbase_sync_status}</p>}
        <div className="actions"><Button variant="quiet" disabled={Boolean(busy)} onClick={saveDraft}>{busy === 'draft' ? 'Saving…' : 'Save draft'}</Button><Button disabled={Boolean(busy) || !canSubmit} onClick={submitResponse}>{busy === 'submit' ? 'Submitting…' : 'Submit response'}</Button></div>
      </Card>
      <aside><Card title="Request history"><div className="clarification-history">{historyEvents.map((event, index) => <div className="activity-event" key={`${event.type}-${index}`}><span>{formatDate(event.occurred_at, true)}</span><div><strong>{event.label}</strong>{event.type === 'request_received' && <><br /><span>{clarification.requested_by}</span></>}</div></div>)}</div></Card></aside>
    </div>
  </>
}

function formatDate(value, short = false) {
  if (!value) return 'Not specified'
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00` : value
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, short ? { month: 'short', day: 'numeric' } : { month: 'long', day: 'numeric', year: 'numeric' })
}

function Timeline({ state, title, copy }) {
  return <div className={`review-timeline-item ${state}`}><span className="review-timeline-icon">{state === 'complete' ? '✓' : state === 'current' ? '●' : '○'}</span><div><strong>{title}</strong><p>{copy}</p></div></div>
}
