import React from "react";
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import PageHeader from '../components/PageHeader'
import { completeInstitutionProfile, getInstitutionProfileQuestions, saveInstitutionProfileResponses } from '../services/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'

function questionSections(schema) {
  return (schema?.sections || []).filter((section) => section.kind === 'questions')
}

function buildResponseState(schema, savedResponses) {
  return Object.fromEntries(questionSections(schema).flatMap((section) => section.questions || []).map((question) => {
    const saved = savedResponses?.[question.id]
    return [question.id, typeof saved === 'object' && saved !== null ? { choice: saved.choice || '', custom: saved.custom || '' } : { choice: '', custom: typeof saved === 'string' ? saved : '' }]
  }))
}

function ProfileQuestion({ question, response, supportingInformation, onChange }) {
  return <fieldset className="profile-question card">
    <legend>{question.label}</legend>
    <div className="profile-choice-row">{(question.options || []).map((option) => <label className="choice" key={option}><input type="radio" name={`profile-${question.id}`} value={option} checked={response.choice === option} onChange={(event) => onChange(question.id, { choice: event.target.value })} /><span>{option}</span></label>)}</div>
    <div className="field profile-supporting-information"><label htmlFor={`profile-${question.id}-custom`}>{supportingInformation?.label || 'Custom response'}</label><input className="input" id={`profile-${question.id}-custom`} value={response.custom} placeholder={supportingInformation?.placeholder || 'Or write a custom answer'} onChange={(event) => onChange(question.id, { custom: event.target.value })} /></div>
  </fieldset>
}

export default function InstitutionProfilePage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { refreshCase } = useCaseContext()
  const [schema, setSchema] = useState(null)
  const [responses, setResponses] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('Autosaved just now')

  useEffect(() => {
    getInstitutionProfileQuestions(caseId)
      .then((data) => { setSchema(data); setResponses(buildResponseState(data, data.responses)) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [caseId])

  const changeResponse = (questionId, patch) => { setResponses((current) => ({ ...current, [questionId]: { ...current[questionId], ...patch } })); setSaved('Unsaved changes') }

  async function submit(event) {
    event.preventDefault()
    const questions = questionSections(schema).flatMap((section) => section.questions || [])
    const unanswered = questions.find((question) => !responses[question.id]?.choice && !responses[question.id]?.custom.trim())
    if (unanswered) { setError('Answer each Relationship Details question before continuing.'); document.getElementById(`profile-${unanswered.id}-custom`)?.focus(); return }
    setSaving(true); setError('')
    try {
      await saveInstitutionProfileResponses(caseId, responses)
      await completeInstitutionProfile(caseId)
      await refreshCase()
      navigate(`/case/${caseId}/documents`)
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }

  if (loading) return <div className="loading-row"><span className="spinner" />Loading Institution Profile…</div>
  if (!schema) return <div className="alert danger">{error || 'Institution Profile is unavailable.'}</div>

  return <>
    <PageHeader eyebrow="Member onboarding" title={schema.title || 'Institution Profile'} description={schema.description || 'Provide additional details about your institution and intended use of the Hazel Network.'} action={<span className="autosave-line">{saved}</span>} />
    {DEV_MODE && <div className="dev-source-line">Institution Profile source: <code>{schema.source || 'fallback'}</code></div>}
    <form onSubmit={submit}>
      {(schema.sections || []).map((section) => section.kind === 'questions' ? <section className="stage-section" key={section.id}>
        <div className="stage-section-head"><div><h2>{section.title}</h2>{section.description && <p className="sub">{section.description}</p>}</div></div>
        <div className="document-list">{(section.questions || []).map((question) => <ProfileQuestion question={question} response={responses[question.id] || { choice: '', custom: '' }} supportingInformation={section.supporting_information} onChange={changeResponse} key={question.id} />)}</div>
      </section> : null)}
      {error && <div className="alert danger">{error}</div>}
      <div className="actions"><Button type="button" variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>Return to Overview</Button><Button disabled={saving}>{saving ? 'Saving…' : 'Continue to Documents'}</Button></div>
    </form>
  </>
}
