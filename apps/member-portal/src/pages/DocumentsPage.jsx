import React from "react";
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import PageHeader from '../components/PageHeader'
import StatusBadge from '../components/StatusBadge'
import { stageIndex } from '../components/ProgressTracker'
import { completeDocuments, completeDueDiligence, deleteDocument, getDocuments, retryDocumentCoverbaseSync, uploadDocument } from '../services/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'

export default function DocumentsPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = (key, options) => t(`onboarding:documents.${key}`, options)
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
  async function continueFlow() { setBusy('complete'); setError(''); try { if (!completed) await completeDocuments(caseId); else if (caseData.current_stage === 'DUE_DILIGENCE') await completeDueDiligence(caseId); await refreshCase(); navigate(`/case/${caseId}/risk-questions`) } catch (err) { setError(err.message) } finally { setBusy('') } }

  const policies = documents.filter((doc) => doc.document_type === 'bsa_policy')
  const wolfsberg = documents.filter((doc) => doc.document_type === 'wolfsberg_cbdq')
  const supporting = documents.filter((doc) => doc.document_type === 'supporting')
  const hasRequired = policies.length > 0
  const hasRequiredSynced = policies[0]?.coverbase_sync_status === 'synced'
  const statusLabel = completed ? t('common:status.accepted') : hasRequired ? copy('stored') : t('common:status.required')

  return <>
    <PageHeader eyebrow={t('common:navigation.onboarding')} title={copy('title')} description={copy('description')} action={<span className="autosave-line">{t('common:save.autosaved')}</span>} />
    <section className="stage-section" id="documents-required">
      <div className="stage-section-head"><div><h2>{copy('requiredTitle')}</h2></div></div>
      <article className="document-item required">
        <div className="document-item-head"><div><h3>{copy('policyTitle')} <span className="required">*</span></h3><p className="sub">{copy('policyHint')}</p></div><StatusBadge tone={completed ? 'success' : hasRequired ? 'info' : 'warning'}>{statusLabel}</StatusBadge></div>
        {hasRequired ? <>
          <div className="upload-progress"><div className="progress"><span style={{ width: completed ? '100%' : '68%' }} /></div><p className="hint">{completed ? 'Accepted by Hazel · 100%' : 'Stored securely in Hazel · 68%'}</p></div>
          <div className="document-meta-row"><span>{copy('version', { number: policies.length })}</span><span>{copy('lastUpdated', { date: new Date(policies[0].created_at).toLocaleDateString() })}</span><details><summary className="text-action">{copy('viewHistory')}</summary><ul className="version-list">{policies.map((doc, index) => <li key={doc.id}>{copy('version', { number: policies.length - index })}: {doc.original_name}</li>)}</ul></details></div>
          <label className="upload-drop-zone compact-upload"><strong>{busy === 'bsa_policy' ? copy('uploading') : copy('replacePolicy')}</strong><span>{copy('fileHint')}</span><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('bsa_policy', event.target.files?.[0])} /></label>
        </> : <label className="upload-drop-zone"><strong>{busy === 'bsa_policy' ? copy('uploading') : copy('uploadPolicy')}</strong><span>{copy('fileHint')}</span><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('bsa_policy', event.target.files?.[0])} /></label>}
      </article>
    </section>
    <section className="stage-section" id="documents-supporting">
      <div className="stage-section-head"><div><h2>{copy('supportingTitle')}</h2><p className="sub">{copy('supportingDescription')}</p></div></div>
      <div className="supporting-grid">
        <article className="document-item"><div className="document-item-head"><div><h3>{copy('wolfsberg')}</h3><p className="sub">{copy('wolfsbergHint')}</p></div><StatusBadge tone={wolfsberg.length ? 'success' : 'info'}>{wolfsberg.length ? copy('uploaded') : t('common:status.optional')}</StatusBadge></div><label className="upload-drop-zone compact-upload"><strong>{busy === 'wolfsberg_cbdq' ? copy('uploading') : wolfsberg.length ? copy('newerVersion') : copy('addWolfsberg')}</strong><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('wolfsberg_cbdq', event.target.files?.[0])} /></label></article>
        <article className="document-item"><div className="document-item-head"><div><h3>{copy('other')}</h3><p className="sub">{copy('otherHint')}</p></div><StatusBadge tone={supporting.length ? 'success' : 'info'}>{supporting.length ? copy('uploadedCount', { count: supporting.length }) : t('common:status.optional')}</StatusBadge></div><label className="upload-drop-zone compact-upload"><strong>{busy === 'supporting' ? copy('uploading') : copy('addSupporting')}</strong><input type="file" accept=".pdf,.doc,.docx,.xls,.xlsx" disabled={Boolean(busy)} onChange={(event) => upload('supporting', event.target.files?.[0])} /></label></article>
      </div>
    </section>
    <section className="stage-section document-repository" id="documents-repository">
      <div className="stage-section-head"><div><p className="eyebrow">{copy('repository')}</p><h2>{copy('repositoryTitle')}</h2><p className="sub">{copy('repositoryDescription')}</p></div></div>
      <div className="repository-list">
        <article className="document-item"><div className="document-item-head"><div><h3>{copy('ndaDocument')}</h3><p className="sub">{copy('ndaDocumentHint')}</p></div><StatusBadge tone="success">{t('common:status.accepted')}</StatusBadge></div><div className="document-meta-row">{copy('acceptedInHazel', { date: caseData.nda_accepted_at ? new Date(caseData.nda_accepted_at).toLocaleString() : 'in Hazel' })}</div></article>
        {documents.map((doc) => <article className="document-item" key={doc.id}><div className="document-item-head"><div><h3>{doc.original_name}</h3><p className="sub">{doc.document_type === 'bsa_policy' ? copy('requiredPolicy') : doc.document_type === 'wolfsberg_cbdq' ? copy('wolfsbergSupporting') : copy('supportingDocument')}</p></div><StatusBadge tone={doc.document_type === 'bsa_policy' && completed ? 'success' : 'info'}>{doc.document_type === 'bsa_policy' && completed ? t('common:status.accepted') : copy('uploadedToHazel')}</StatusBadge></div><div className="document-meta-row"><span>{Math.max(1, Math.round(doc.size_bytes / 1024))} KB</span><span>{new Date(doc.created_at).toLocaleDateString()}</span>{doc.coverbase_sync_status === 'synced' && <span>{copy('coverbaseSynced')}</span>}{['not_started', 'not_configured'].includes(doc.coverbase_sync_status) && <span>{copy('coverbasePending')}</span>}{doc.coverbase_sync_status === 'failed' && <><span>{copy('coverbaseFailed')}</span><Button variant="quiet" disabled={busy === `sync-${doc.id}`} onClick={() => retrySync(doc.id)}>{busy === `sync-${doc.id}` ? copy('retrying') : copy('retrySync')}</Button></>}<Button variant="quiet" disabled={busy === String(doc.id)} onClick={() => remove(doc.id)}>{t('common:actions.remove')}</Button></div>{DEV_MODE && <p className="hint">Hazel document ID: {doc.id} · Coverbase document ID: {doc.coverbase_document_id || 'none'} · Sync: {doc.coverbase_sync_status} · In session: {String(doc.coverbase_in_session)}</p>}</article>)}
      </div>
    </section>
    {error && <div className="alert danger">{error}</div>}
    <div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button><Button disabled={(!completed && !hasRequiredSynced) || Boolean(busy)} onClick={continueFlow}>{busy === 'complete' ? copy('completing') : copy('next')}</Button></div>
  </>
}
