import React from "react";
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { stageIndex } from '../components/ProgressTracker'
import { acceptNda } from '../services/api'

const NDA_DOCUMENT = '/assets/vantage-hazel-mutual-nda.html'

export default function NdaPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = (key) => t(`onboarding:nda.${key}`)
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { caseData, refreshCase } = useCaseContext()
  const completed = stageIndex(caseData.current_stage) > 0 || Boolean(caseData.nda_accepted_at)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const acceptedAt = completed && caseData.nda_accepted_at ? new Date(caseData.nda_accepted_at).toLocaleString() : copy('notAccepted')

  async function submit() {
    setBusy(true); setError('')
    try {
      await acceptNda(caseId)
      await refreshCase()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <div className="nda-layout">
    <div className="nda-main-content">
      <PageHeader eyebrow={copy('eyebrow')} title={copy('title')} description={completed ? copy('descriptionComplete') : copy('descriptionPending')} action={<StatusBadge tone={completed ? 'success' : 'warning'}>{completed ? t('common:status.accepted') : copy('notAccepted')}</StatusBadge>} />
      <Card title={copy('agreement')}>
        <p className="sub">{copy('agreementDescription')}</p>
        <div className="nda-preview-card"><iframe className="nda-preview-frame" src={NDA_DOCUMENT} title="Mutual Non-Disclosure Agreement preview" /></div>
      </Card>
      <section className="nda-signer">
        <h3>{copy('representative')}</h3>
        <p><strong>{copy('authorizedApplicant')}</strong><br />{caseData.primary_applicant_email || 'Test applicant email unavailable'}</p>
        <p>{copy('representativeDescription')}</p>
      </section>
      <Card title={completed ? copy('recordedTitle') : copy('acceptTitle')}>
        {completed ? <div className="alert success"><strong>{copy('acceptedTitle')}</strong><br />{copy('acceptedDescription')}</div> : <p className="sub">{copy('pendingDescription')}</p>}
        <div className="nda-acceptance-details"><div><span>{copy('applicant')}</span><strong>{caseData.primary_applicant_email || copy('authorizedApplicant')}</strong></div><div><span>{copy('institution')}</span><strong>{caseData.legal_name || 'Synthetic test institution'}</strong></div><div><span>{completed ? copy('acceptedAt') : copy('date')}</span><strong>{completed ? acceptedAt : new Date().toLocaleDateString()}</strong></div></div>
        {!completed && <label className="choice nda-acknowledgement"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /><span>{copy('acknowledgement')}</span></label>}
        {error && <div className="alert danger">{error}</div>}
        <div className="actions">
          {completed ? <><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button><Button onClick={() => navigate(`/case/${caseId}/due-diligence`)}>{copy('next')}</Button></> : <><Button disabled={!accepted || busy} onClick={submit}>{busy ? copy('recording') : copy('accept')}</Button><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button></>}
        </div>
      </Card>
    </div>
    <aside className="nda-pdf-panel" aria-label="Read-only NDA preview">
      <h2>{copy('preview')}</h2>
      <div className="nda-pdf-toolbar"><span className="nda-pdf-page-indicator">1 / 7</span><div className="nda-pdf-tools" aria-hidden="true"><span className="nda-pdf-tool">−</span><span className="nda-pdf-tool nda-pdf-zoom">100%</span><span className="nda-pdf-tool">+</span><span className="nda-pdf-tool">⇩</span><span className="nda-pdf-tool">⎙</span></div></div>
      <div className="nda-pdf-viewport"><iframe className="nda-pdf-page" src={NDA_DOCUMENT} title="Read-only Mutual Non-Disclosure Agreement" /></div>
      <section className="nda-pdf-summary">
        <h3>{copy('summary')}</h3>
        <dl className="nda-pdf-audit"><dt>{copy('applicant')}</dt><dd>{caseData.primary_applicant_email || copy('authorizedApplicant')}</dd><dt>{copy('institution')}</dt><dd>{caseData.legal_name || 'Synthetic test institution'}</dd><dt>{copy('dateAccepted')}</dt><dd>{acceptedAt}</dd><dt>{copy('ipAddress')}</dt><dd>{completed ? '192.0.2.10' : copy('pendingAcceptance')}</dd><dt>{copy('documentVersion')}</dt><dd>NDA-2025.01</dd><dt>{copy('transactionId')}</dt><dd>{completed ? 'NDA-0000123456' : copy('pendingAcceptance')}</dd></dl>
        <div className="nda-pdf-acknowledgement"><strong>{copy('electronicAcknowledgement')}</strong>{completed ? copy('acknowledgementRecorded') : copy('acknowledgementPending')}</div>
      </section>
      <div className="nda-pdf-actions"><Button variant="secondary" onClick={() => window.open(NDA_DOCUMENT, '_blank')}>{copy('download')}</Button><Button variant="secondary" onClick={() => window.print()}>{copy('print')}</Button></div>
    </aside>
  </div>
}
