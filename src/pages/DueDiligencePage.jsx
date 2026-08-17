import React from "react";
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import FormField from '../components/FormField'
import PageHeader from '../components/PageHeader'
import { completeDueDiligence, getDueDiligence, saveDueDiligence } from '../services/api'

const SECTIONS = [
  { title: 'Institution Details', fields: [
    { id: 'institutionWebsite', label: 'Institution website', type: 'url', source: 'public-record' },
    { id: 'headquarters', label: 'Headquarters', source: 'public-record' },
    { id: 'charterType', label: 'Charter type', type: 'select', options: ['National', 'State member', 'State nonmember', 'Other'], source: 'institution' },
    { id: 'primaryRegulator', label: 'Primary federal regulator', type: 'select', options: ['OCC', 'FDIC', 'Federal Reserve', 'NCUA', 'Other'], source: 'institution' },
    { id: 'useCaseSummary', label: 'Intended use of the Hazel Network', type: 'textarea', source: 'suggested' },
    { id: 'activityGeography', label: 'Expected activity', type: 'select', options: ['Domestic only', 'International activity expected', 'Unsure'], source: 'suggested' },
    { id: 'estimatedMonthlyVolume', label: 'Estimated monthly network volume', source: 'institution' },
    { id: 'materialFindings', label: 'Any open material BSA/AML or OFAC findings?', type: 'select', options: ['Yes', 'No', 'Unsure'], source: 'institution' },
    { id: 'additionalContext', label: 'Additional context', type: 'textarea', source: 'institution' },
  ]},
  { title: 'Primary Contacts', fields: [
    { id: 'bsaOfficerName', label: 'BSA Officer name', source: 'institution' },
    { id: 'bsaOfficerTitle', label: 'BSA Officer title', source: 'institution' },
    { id: 'bsaOfficerEmail', label: 'BSA Officer email', type: 'email', source: 'institution' },
    { id: 'bsaOfficerPhone', label: 'BSA Officer phone', type: 'tel', source: 'institution' },
    { id: 'lastIndependentTest', label: 'Most recent independent BSA/AML test date', type: 'date', source: 'suggested' },
    { id: 'complianceContactEmail', label: 'Compliance team email', type: 'email', source: 'institution' },
    { id: 'executiveSponsor', label: 'Executive sponsor', source: 'institution' },
  ]},
]

const SOURCE_LABELS = { 'public-record': 'Public record', institution: 'Institution provided', suggested: 'Suggested' }

export default function DueDiligencePage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { refreshCase } = useCaseContext()
  const [data, setData] = useState({})
  const [open, setOpen] = useState(-1)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('Autosaved just now')

  useEffect(() => { getDueDiligence(caseId).then((result) => setData(result.data)).catch((err) => setError(err.message)) }, [caseId])
  const total = useMemo(() => SECTIONS.flatMap((section) => section.fields).length, [])
  const answered = Object.values(data).filter((value) => String(value || '').trim()).length
  const change = (event) => { setData((current) => ({ ...current, [event.target.name]: event.target.value })); setSaved('Unsaved changes') }
  async function save() { setBusy(true); setError(''); try { await saveDueDiligence(caseId, data); setSaved('Saved just now') } catch (err) { setError(err.message) } finally { setBusy(false) } }
  async function submit() { setBusy(true); setError(''); try { await saveDueDiligence(caseId, data); await completeDueDiligence(caseId); await refreshCase(); navigate(`/case/${caseId}/risk-questions`) } catch (err) { setError(err.message) } finally { setBusy(false) } }

  return <>
    <PageHeader eyebrow="Due Diligence" title="Due Diligence" description="Review source-labeled information and complete each logical section before submission." action={<span className="autosave-line">{saved}</span>} />
    <div className="due-diligence-layout">
      <Card title="Due Diligence questionnaire">
        <p className="sub">{answered} / {total} completed</p>
        <div className="alert"><strong>Review the source before confirming an answer.</strong><br />Public-record fields are review-only. Hazel-generated values are marked Suggested until your institution confirms or edits them.</div>
        {SECTIONS.map((section, sectionIndex) => {
          const count = section.fields.filter((field) => String(data[field.id] || '').trim()).length
          const percent = Math.round((count / section.fields.length) * 100)
          const isOpen = open === sectionIndex
          return <section className={`dd-section ${isOpen ? 'open' : ''}`} key={section.title}>
            <button className="dd-section-summary" type="button" onClick={() => setOpen(isOpen ? -1 : sectionIndex)} aria-expanded={isOpen}>
              <span><strong className="dd-section-title">{section.title}</strong><small className="dd-section-progress">{count} / {section.fields.length} completed</small></span><span className="dd-section-toggle">{isOpen ? '−' : '+'}</span><span className="progress"><span style={{ width: `${percent}%` }} /></span>
            </button>
            {isOpen && <div className="dd-section-body"><div className="form-grid">{section.fields.map((field) => <div key={field.id}>
              <FormField id={field.id} name={field.id} label={field.label} as={field.type === 'textarea' ? 'textarea' : field.type === 'select' ? 'select' : 'input'} type={field.type && !['textarea', 'select'].includes(field.type) ? field.type : undefined} options={field.options} value={data[field.id] || ''} onChange={change} readOnly={field.source === 'public-record'} />
              <div className="source-row"><span className={`source-chip ${field.source}`}>{SOURCE_LABELS[field.source]}</span>{field.source === 'suggested' && <span className="source-chip suggested">Needs review</span>}</div>
            </div>)}</div></div>}
          </section>
        })}
        <label className="choice"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirm this Due Diligence information is complete and ready for Hazel review.</span></label>
        {error && <div className="alert danger">{error}</div>}
        <div className="actions"><Button variant="secondary" type="button" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button variant="quiet" type="button" disabled={busy} onClick={save}>Save draft</Button><Button type="button" disabled={!confirmed || busy} onClick={submit}>{busy ? 'Saving…' : 'Submit Due Diligence'}</Button></div>
      </Card>
      <aside><Card title="Information Sources" subtitle="Source labels explain whether information came from public records, your institution, or a Hazel-generated suggestion.">
        <div className="task-list"><div className="task"><span className="task-icon">P</span><div><strong>Public records</strong><p>Review-only institution identifiers.</p></div></div><div className="task"><span className="task-icon">I</span><div><strong>Institution provided</strong><p>Editable information supplied by your team.</p></div></div><div className="task"><span className="task-icon">S</span><div><strong>Suggested</strong><p>Hazel-generated information that still needs review.</p></div></div></div>
        <Button variant="secondary" type="button">Invite teammate</Button>
      </Card></aside>
    </div>
  </>
}
