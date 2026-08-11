import React from "react";
import { useState } from 'react'
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
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { caseData, refreshCase } = useCaseContext()
  const completed = stageIndex(caseData.current_stage) > 0 || Boolean(caseData.nda_accepted_at)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const acceptedAt = completed && caseData.nda_accepted_at ? new Date(caseData.nda_accepted_at).toLocaleString() : 'Not yet accepted'

  async function submit() {
    setBusy(true); setError('')
    try {
      await acceptNda(caseId)
      await refreshCase()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return <div className="nda-layout">
    <div className="nda-main-content">
      <PageHeader eyebrow="Confidentiality" title="Mutual Non-Disclosure Agreement" description={completed ? 'The NDA has been accepted. Continue to Institution Profile when ready.' : 'Review and accept the Vantage Bank Texas agreement before continuing to Institution Profile.'} action={<StatusBadge tone={completed ? 'success' : 'warning'}>{completed ? 'Accepted' : 'Not accepted'}</StatusBadge>} />
      <Card title="Agreement">
        <p className="sub">The complete seven-page agreement provided by Vantage Bank Texas is available below without changes to its legal language.</p>
        <div className="nda-preview-card"><iframe className="nda-preview-frame" src={NDA_DOCUMENT} title="Mutual Non-Disclosure Agreement preview" /></div>
      </Card>
      <section className="nda-signer">
        <h3>Authorized representative</h3>
        <p><strong>Authorized applicant</strong><br />{caseData.primary_applicant_email || 'Test applicant email unavailable'}</p>
        <p>The representative must be authorized to accept agreements on behalf of the institution.</p>
      </section>
      <Card title={completed ? 'Acceptance recorded' : 'Accept Agreement'}>
        {completed ? <div className="alert success"><strong>NDA accepted</strong><br />Your Mutual Non-Disclosure Agreement has been accepted. Institution Profile is now available.</div> : <p className="sub">Review the agreement and acknowledge your acceptance of the Mutual Non-Disclosure Agreement.</p>}
        <div className="nda-acceptance-details"><div><span>Applicant</span><strong>{caseData.primary_applicant_email || 'Authorized applicant'}</strong></div><div><span>Institution</span><strong>{caseData.legal_name || 'Synthetic test institution'}</strong></div><div><span>{completed ? 'Acceptance date and time' : 'Date'}</span><strong>{completed ? acceptedAt : new Date().toLocaleDateString()}</strong></div></div>
        {!completed && <label className="choice nda-acknowledgement"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /><span>I have reviewed and agree to the Hazel Network Mutual Non-Disclosure Agreement and confirm that I am authorized to accept it on behalf of my institution.</span></label>}
        {error && <div className="alert danger">{error}</div>}
        <div className="actions">
          {completed ? <><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button onClick={() => navigate(`/case/${caseId}/institution-profile`)}>Next Step: Institution Profile</Button></> : <><Button disabled={!accepted || busy} onClick={submit}>{busy ? 'Recording acceptance…' : 'Accept Mutual NDA'}</Button><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button></>}
        </div>
      </Card>
    </div>
    <aside className="nda-pdf-panel" aria-label="Read-only NDA preview">
      <h2>PDF Preview (Read-Only)</h2>
      <div className="nda-pdf-toolbar"><span className="nda-pdf-page-indicator">1 / 7</span><div className="nda-pdf-tools" aria-hidden="true"><span className="nda-pdf-tool">−</span><span className="nda-pdf-tool nda-pdf-zoom">100%</span><span className="nda-pdf-tool">+</span><span className="nda-pdf-tool">⇩</span><span className="nda-pdf-tool">⎙</span></div></div>
      <div className="nda-pdf-viewport"><iframe className="nda-pdf-page" src={NDA_DOCUMENT} title="Read-only Mutual Non-Disclosure Agreement" /></div>
      <section className="nda-pdf-summary">
        <h3>Execution Summary</h3>
        <dl className="nda-pdf-audit"><dt>Applicant</dt><dd>{caseData.primary_applicant_email || 'Authorized applicant'}</dd><dt>Institution</dt><dd>{caseData.legal_name || 'Synthetic test institution'}</dd><dt>Date accepted</dt><dd>{acceptedAt}</dd><dt>IP address</dt><dd>{completed ? '192.0.2.10' : 'Pending acceptance'}</dd><dt>Document version</dt><dd>NDA-2025.01</dd><dt>Transaction ID</dt><dd>{completed ? 'NDA-0000123456' : 'Pending acceptance'}</dd></dl>
        <div className="nda-pdf-acknowledgement"><strong>Electronic acknowledgement</strong>{completed ? 'The authorized representative acknowledged that they reviewed and agreed to the Mutual Non-Disclosure Agreement.' : 'No electronic acknowledgement has been recorded yet.'}</div>
      </section>
      <div className="nda-pdf-actions"><Button variant="secondary" onClick={() => window.open(NDA_DOCUMENT, '_blank')}>Download PDF</Button><Button variant="secondary" onClick={() => window.print()}>Print</Button></div>
    </aside>
  </div>
}
