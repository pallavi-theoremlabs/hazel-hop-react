import React from "react";
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { stageIndex } from '../components/ProgressTracker'
import { completeDocuments, deleteDocument, getDocuments, retryDocumentCoverbaseSync, uploadDocument } from '../services/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'

export default function DocumentsPage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { caseData, refreshCase } = useCaseContext()
  const [documents, setDocuments] = useState([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const completed = stageIndex(caseData.current_stage) > 2
  const load = () => getDocuments(caseId).then(setDocuments).catch((err) => setError(err.message))

  useEffect(() => { load() }, [caseId])
  async function upload(type, file) { if (!file) return; setBusy(type); setError(''); try { const result = await uploadDocument(caseId, file, type); if (result.integration_warning) setError(result.integration_warning); await load() } catch (err) { setError(err.message) } finally { setBusy('') } }
  async function retrySync(id) { setBusy(`sync-${id}`); setError(''); try { const result = await retryDocumentCoverbaseSync(caseId, id); if (result.integration_warning) setError(result.integration_warning); await load() } catch (err) { setError(err.message) } finally { setBusy('') } }
  async function remove(id) { setBusy(String(id)); try { await deleteDocument(caseId, id); await load() } catch (err) { setError(err.message) } finally { setBusy('') } }
  async function continueFlow() { setBusy('complete'); setError(''); try { if (!completed) await completeDocuments(caseId); await refreshCase(); navigate(`/case/${caseId}/due-diligence`) } catch (err) { setError(err.message) } finally { setBusy('') } }

  const policies = documents.filter((doc) => doc.document_type === 'bsa_policy')
  const wolfsberg = documents.filter((doc) => doc.document_type === 'wolfsberg_cbdq')
  const supporting = documents.filter((doc) => doc.document_type === 'supporting')
  const hasRequired = policies.length > 0
  const hasRequiredSynced = policies[0]?.coverbase_sync_status === 'synced'
  const statusLabel = completed ? 'Accepted' : hasRequired ? 'Stored securely in Hazel' : 'Required'

  return <>
    <PageHeader eyebrow="Onboarding" title="Documents" description="Upload the compliance documents available to your institution." action={<span className="autosave-line">Autosaved just now</span>} />
    <section className="stage-section" id="documents-required">
      <div className="stage-section-head"><div><h2>Required document</h2></div></div>
      <article className="document-item required">
        <div className="document-item-head"><div><h3>Current Board-approved BSA/AML/OFAC policy <span className="required">*</span></h3><p className="sub">Include Board-approval evidence · reviewed within the last 12 months</p></div><StatusBadge tone={completed ? 'success' : hasRequired ? 'info' : 'warning'}>{statusLabel}</StatusBadge></div>
        {hasRequired ? <>
          <div className="upload-progress"><div className="progress"><span style={{ width: completed ? '100%' : '68%' }} /></div><p className="hint">{completed ? 'Accepted by Hazel · 100%' : 'Stored securely in Hazel · 68%'}</p></div>
          <div className="document-meta-row"><span>Version {policies.length}</span><span>Last updated {new Date(policies[0].created_at).toLocaleDateString()}</span><details><summary className="text-action">View history</summary><ul className="version-list">{policies.map((doc, index) => <li key={doc.id}>Version {policies.length - index}: {doc.original_name}</li>)}</ul></details></div>
          <label className="upload-drop-zone compact-upload"><strong>{busy === 'bsa_policy' ? 'Uploading…' : 'Upload a replacement version'}</strong><span>PDF, Word, or Excel · up to 25 MB</span><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('bsa_policy', event.target.files?.[0])} /></label>
        </> : <label className="upload-drop-zone"><strong>{busy === 'bsa_policy' ? 'Uploading…' : 'Choose the required policy to upload'}</strong><span>PDF, Word, or Excel · up to 25 MB</span><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('bsa_policy', event.target.files?.[0])} /></label>}
      </article>
    </section>
    <section className="stage-section" id="documents-supporting">
      <div className="stage-section-head"><div><h2>Supporting documents</h2><p className="sub">If your institution has a completed Wolfsberg CBDDQ or other documents that may support Hazel’s review, you can upload them here.</p></div></div>
      <div className="supporting-grid">
        <article className="document-item"><div className="document-item-head"><div><h3>Wolfsberg CBDDQ</h3><p className="sub">Optional · upload your current completed questionnaire if applicable.</p></div><StatusBadge tone={wolfsberg.length ? 'success' : 'info'}>{wolfsberg.length ? 'Uploaded' : 'Optional'}</StatusBadge></div><label className="upload-drop-zone compact-upload"><strong>{busy === 'wolfsberg_cbdq' ? 'Uploading…' : wolfsberg.length ? 'Add a newer version' : 'Add Wolfsberg CBDDQ'}</strong><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('wolfsberg_cbdq', event.target.files?.[0])} /></label></article>
        <article className="document-item"><div className="document-item-head"><div><h3>Other supporting documents</h3><p className="sub">Optional evidence or context for Hazel’s review.</p></div><StatusBadge tone={supporting.length ? 'success' : 'info'}>{supporting.length ? `${supporting.length} uploaded` : 'Optional'}</StatusBadge></div><label className="upload-drop-zone compact-upload"><strong>{busy === 'supporting' ? 'Uploading…' : 'Add supporting document'}</strong><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('supporting', event.target.files?.[0])} /></label></article>
      </div>
    </section>
    <section className="stage-section document-repository" id="documents-repository">
      <div className="stage-section-head"><div><p className="eyebrow">Repository</p><h2>Document repository</h2><p className="sub">Documents and acknowledgement records collected during onboarding appear here.</p></div></div>
      <div className="repository-list">
        <article className="document-item"><div className="document-item-head"><div><h3>Mutual Non-Disclosure Agreement</h3><p className="sub">Digitally acknowledged during onboarding</p></div><StatusBadge tone="success">Accepted</StatusBadge></div><div className="document-meta-row">Accepted {caseData.nda_accepted_at ? new Date(caseData.nda_accepted_at).toLocaleString() : 'in Hazel'}</div></article>
        {documents.map((doc) => <article className="document-item" key={doc.id}><div className="document-item-head"><div><h3>{doc.original_name}</h3><p className="sub">{doc.document_type === 'bsa_policy' ? 'Required policy' : doc.document_type === 'wolfsberg_cbdq' ? 'Wolfsberg CBDDQ · supporting' : 'Supporting document'}</p></div><StatusBadge tone={doc.document_type === 'bsa_policy' && completed ? 'success' : 'info'}>{doc.document_type === 'bsa_policy' && completed ? 'Accepted' : 'Uploaded to Hazel'}</StatusBadge></div><div className="document-meta-row"><span>{Math.max(1, Math.round(doc.size_bytes / 1024))} KB</span><span>{new Date(doc.created_at).toLocaleDateString()}</span>{doc.coverbase_sync_status === 'synced' && <span>Coverbase synced</span>}{['not_started', 'not_configured'].includes(doc.coverbase_sync_status) && <span>Coverbase sync pending</span>}{doc.coverbase_sync_status === 'failed' && <><span>Coverbase sync failed</span><Button variant="quiet" disabled={busy === `sync-${doc.id}`} onClick={() => retrySync(doc.id)}>{busy === `sync-${doc.id}` ? 'Retrying…' : 'Retry Coverbase sync'}</Button></>}<Button variant="quiet" disabled={busy === String(doc.id)} onClick={() => remove(doc.id)}>Remove</Button></div>{DEV_MODE && <p className="hint">Hazel document ID: {doc.id} · Coverbase document ID: {doc.coverbase_document_id || 'none'} · Sync: {doc.coverbase_sync_status} · In session: {String(doc.coverbase_in_session)}</p>}</article>)}
      </div>
    </section>
    {error && <div className="alert danger">{error}</div>}
    <div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button disabled={(!completed && !hasRequiredSynced) || Boolean(busy)} onClick={continueFlow}>{busy === 'complete' ? 'Completing…' : 'Continue to Due Diligence'}</Button></div>
  </>
}
