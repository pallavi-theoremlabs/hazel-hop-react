import React, { useEffect, useState } from "react";
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from './CaseApp'
import Button from '../../components/shared/Button'
import Card from '../../components/portal/Card'
import PageHeader from '../../components/portal/PageHeader'
import StatusBadge from '../../components/shared/StatusBadge'
import useCoverbaseReviewStatus from '../../hooks/useCoverbaseReviewStatus'
import { saveClarificationDraft, submitClarificationResponse, uploadClarificationDocument } from '../../services/portal/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'

const REVIEW_CONTENT = {
  under_review: { tone: 'info' },
  response_submitted: { tone: 'info' },
  approved: { tone: 'success' },
  rejected: { tone: 'warning' },
  partial: { tone: 'warning' },
}

export default function HazelReviewPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = (key, options) => t(`onboarding:hazelReview.${key}`, options)
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

  const contentKey = REVIEW_CONTENT[reviewState] ? reviewState : 'under_review'
  const content = {
    ...REVIEW_CONTENT[contentKey],
    label: copy(`states.${contentKey}.label`),
    description: copy(`states.${contentKey}.description`),
    expected: copy(`states.${contentKey}.expected`),
  }
  const esignEligible = data?.esign_eligible ?? caseData.esign_eligible ?? false
  const decisionReached = ['approved', 'rejected', 'partial'].includes(reviewState)
  const responseSubmitted = reviewState === 'response_submitted'

  return <>
    <PageHeader eyebrow={copy('title')} title={content.label} description={content.description} action={<StatusBadge tone={content.tone}>{content.label}</StatusBadge>} />
    <div className="hazel-review-layout">
      <Card title={copy('statusCard')}>
        <div className="case-facts"><div><span>{copy('status')}</span><strong>{content.label}</strong></div><div><span>{copy('submitted')}</span><strong>{caseData.risk_questions_submitted_at ? new Date(caseData.risk_questions_submitted_at).toLocaleString() : copy('pending')}</strong></div><div><span>{copy('lastUpdate')}</span><strong>{caseData.updated_at ? new Date(caseData.updated_at).toLocaleString() : copy('justNow')}</strong></div><div><span>{copy('esignEligibility')}</span><strong>{esignEligible ? copy('eligible') : copy('notEligible')}</strong></div><div><span>{copy('expectedNext')}</span><strong>{content.expected}</strong></div></div>
        {responseSubmitted && <div className="alert success"><strong>{copy('alerts.responseTitle')}</strong><br />{copy('alerts.responseDescription')}</div>}
        {reviewState === 'rejected' && <div className="alert warning"><strong>{copy('alerts.rejectedTitle')}</strong><br />{copy('alerts.rejectedDescription')}</div>}
        {reviewState === 'partial' && <div className="alert warning"><strong>{copy('alerts.partialTitle')}</strong><br />{copy('alerts.partialDescription')}</div>}
        {reviewState === 'approved' && <div className="alert success"><strong>{copy('alerts.approvedTitle')}</strong><br />{copy('alerts.approvedDescription')}</div>}
        {data?.coverbase_status_sync_error && <div className="alert warning">{data.coverbase_status_sync_error}</div>}
        {error && <div className="alert danger"><strong>{copy('refreshError')}</strong><br />{error}</div>}
        {DEV_MODE && <div className="alert"><strong>Local review debug</strong><br />Coverbase session: {data?.coverbase_session_id || caseData.coverbase_session_id || '—'} · Coverbase status: {coverbaseStatus} · Hazel review state: {reviewState} · Hazel stage: {data?.current_stage || caseData.current_stage} · Clarification sync: {data?.coverbase_sync_status || '—'} · eSign eligible: {String(esignEligible)}</div>}
        <div className="review-timeline" aria-label={copy('timelineLabel')}>
          <Timeline state="complete" title={copy('submissionReceived')} copy={copy('submissionReceivedDescription')} />
          {responseSubmitted && <Timeline state="complete" title={copy('responseSubmitted')} copy={copy('responseSubmittedDescription')} />}
          <Timeline state={decisionReached ? 'complete' : 'current'} title={responseSubmitted ? copy('reviewResumed') : copy('reviewInProgress')} copy={decisionReached ? copy('decisionRecorded') : content.description} />
          <Timeline state={decisionReached ? 'current' : ''} title={copy('decision')} copy={decisionReached ? content.expected : copy('decisionWaiting')} />
        </div>
        <div className="review-bottom-actions"><div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button><Button variant="secondary" disabled={isRefreshing} onClick={() => refresh().catch(() => {})}>{isRefreshing ? copy('refreshing') : copy('refresh')}</Button>{reviewState === 'approved' && <Button onClick={() => navigate(`/case/${caseId}/esign`)}>{copy('continueEsign')}</Button>}</div></div>
      </Card>
    </div>
  </>
}

function ClarificationRequest({ caseId, clarification, historyEvents, integrationError, loadError, refresh, refreshCase }) {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = (key, options) => t(`onboarding:hazelReview.clarification.${key}`, options)
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
      setMessage(copy('draftSaved'))
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
      setMessage(result.document.integration_warning || copy('documentUploaded'))
      await reload()
    } catch (err) { setError(err.message) } finally { setBusy(''); event.target.value = '' }
  }

  const uploaded = clarification.uploaded_document
  const dueDate = formatDate(clarification.due_at)
  const canSubmit = response.trim() && (!clarification.document_required || uploaded)

  return <>
    <PageHeader eyebrow={t('onboarding:hazelReview.title')} title={copy('title')} description={copy('respondBy', { date: dueDate })} action={<StatusBadge tone="warning">{copy('actionRequired')}</StatusBadge>} />
    <div className="hazel-clarification-layout">
      <Card title={copy('requestTitle')}>
        <div className="case-facts"><div><span>{copy('requestedBy')}</span><strong>{clarification.requested_by}</strong></div><div><span>{copy('dueDate')}</span><strong>{dueDate}</strong></div></div>
        <div className="alert warning"><strong>{copy('additionalInformation')}</strong><br />{clarification.request_text}</div>
        <div className="field"><label htmlFor="clarification-response">{copy('response')}</label><textarea id="clarification-response" className="input" placeholder={copy('responsePlaceholder')} value={response} onChange={(event) => setResponse(event.target.value)} /><p className="hint">{copy('draftHint')}</p></div>
        {clarification.document_required && <div className="doc-card clarification-document"><div className="doc-head"><div><h3>{clarification.document_label || copy('requestedDocument')}</h3><p className="sub">{copy('documentHint')}</p></div><StatusBadge tone={uploaded ? 'info' : 'warning'}>{uploaded ? copy('uploaded') : copy('resubmission')}</StatusBadge></div>{uploaded && <div className="clarification-file"><strong>{uploaded.original_name}</strong><span>{Math.max(1, Math.round(uploaded.size_bytes / 1024))} KB · {copy('stored')}</span></div>}<div className="actions"><label className={`btn secondary clarification-upload-button ${busy ? 'disabled' : ''}`}>{busy === 'document' ? copy('uploading') : uploaded ? copy('replace') : copy('upload')}<input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={uploadDocument} /></label></div></div>}
        {message && <div className="alert success">{message}</div>}
        {(error || loadError) && <div className="alert danger">{error || loadError}</div>}
        {integrationError && <div className="alert warning">{integrationError}</div>}
        {DEV_MODE && <p className="hint">Clarification ID: {clarification.id} · Source: {clarification.source} · Coverbase clarification sync: {clarification.coverbase_sync_status}</p>}
        <div className="actions"><Button variant="quiet" disabled={Boolean(busy)} onClick={saveDraft}>{busy === 'draft' ? t('common:save.saving') : copy('saveDraft')}</Button><Button disabled={Boolean(busy) || !canSubmit} onClick={submitResponse}>{busy === 'submit' ? copy('submitting') : copy('submitResponse')}</Button></div>
      </Card>
      <aside><Card title={copy('history')}><div className="clarification-history">{historyEvents.map((event, index) => <div className="activity-event" key={`${event.type}-${index}`}><span>{formatDate(event.occurred_at, true)}</span><div><strong>{event.label}</strong>{event.type === 'request_received' && <><br /><span>{clarification.requested_by}</span></>}</div></div>)}</div></Card></aside>
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
