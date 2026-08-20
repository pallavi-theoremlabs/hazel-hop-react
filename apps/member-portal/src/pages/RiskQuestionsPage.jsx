import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import QuestionnaireProgress from '../components/risk/QuestionnaireProgress'
import QuestionRenderer from '../components/risk/QuestionRenderer'
import { answerFromQuestion, draftAnswer, isAnswerValid, reviewStateFor } from '../components/risk/riskQuestionState'
import StatusBadge from '../components/StatusBadge'
import { completeDueDiligence, getRiskQuestions, saveRiskAnswer, submitRiskQuestions } from '../services/api'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'
const FILTERS = ['all', 'needs-input', 'review', 'confirmed', 'remaining']

export default function RiskQuestionsPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = useCallback((key, options) => t(`onboarding:riskQuestions.${key}`, options), [t])
  const { caseId } = useParams()
  const navigate = useNavigate()
  const { caseData, refreshCase } = useCaseContext()
  const [result, setResult] = useState(null)
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [currentSection, setCurrentSection] = useState(0)
  const [filter, setFilter] = useState('all')
  const [busy, setBusy] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitDialogOpen, setSubmitDialogOpen] = useState(false)
  const [pendingSaves, setPendingSaves] = useState(0)
  const [questionSaveStates, setQuestionSaveStates] = useState({})
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    // Compatibility migration for cases that stopped at the removed technical
    // Due Diligence stage before the consolidated workflow was introduced.
    if (caseData.current_stage === 'DUE_DILIGENCE') {
      await completeDueDiligence(caseId)
      await refreshCase()
    }
    const next = await getRiskQuestions(caseId)
    setResult(next)
    setQuestions(next.questions || [])
    setAnswers(Object.fromEntries((next.questions || []).map((question) => [String(question.question_id), answerFromQuestion(question)])))
  }, [caseData.current_stage, caseId, refreshCase])

  useEffect(() => { load().catch((err) => setError(err.message)) }, [load])

  const sections = useMemo(() => {
    const grouped = new Map()
    questions.forEach((question) => {
      const name = question.section_name || copy('section.fallback')
      const key = String(question.section_id || name)
      if (!grouped.has(key)) grouped.set(key, { key, name, questions: [] })
      grouped.get(key).questions.push(question)
    })
    return [...grouped.values()].map((section) => {
      const states = section.questions.map((question) => reviewStateFor(answers[String(question.question_id)]))
      return {
        ...section,
        confirmed: states.filter((state) => state === 'confirmed').length,
        needsInput: states.filter((state) => state === 'needs-input').length,
      }
    })
  }, [answers, copy, questions])

  useEffect(() => {
    if (sections.length && currentSection >= sections.length) setCurrentSection(sections.length - 1)
  }, [currentSection, sections.length])

  const counts = useMemo(() => {
    const states = questions.map((question) => reviewStateFor(answers[String(question.question_id)]))
    const confirmed = states.filter((state) => state === 'confirmed').length
    return {
      total: questions.length,
      'needs-input': states.filter((state) => state === 'needs-input').length,
      review: states.filter((state) => state === 'review').length,
      confirmed,
      remaining: questions.length - confirmed,
    }
  }, [answers, questions])

  const activeSection = sections[currentSection]
  const visibleQuestions = useMemo(() => (activeSection?.questions || []).filter((question) => {
    const state = reviewStateFor(answers[String(question.question_id)])
    if (filter === 'all') return true
    if (filter === 'remaining') return state !== 'confirmed'
    return state === filter
  }), [activeSection, answers, filter])

  function requestFor(answer, reviewed) {
    const payload = { response: answer.response ?? '', selected_option_ids: answer.selected_option_ids ?? null, comment: answer.comment ?? null, reviewed }
    if (answer.response_data !== undefined) payload.response_data = answer.response_data
    return payload
  }

  async function update(questionId, patch, { persist = true, reviewed } = {}) {
    const previous = answers[questionId] || {}
    const next = draftAnswer(previous, patch)
    setAnswers((current) => ({ ...current, [questionId]: next }))
    if (!persist) {
      return null
    }
    if (typeof reviewed !== 'boolean') {
      throw new Error('Risk Question saves must explicitly include review intent.')
    }
    if (!isAnswerValid(next)) {
      return null
    }
    setError('')
    setQuestionSaveStates((current) => ({ ...current, [questionId]: { status: 'saving', error: '' } }))
    setPendingSaves((count) => count + 1)
    try {
      const saved = await saveRiskAnswer(caseId, questionId, requestFor(next, reviewed))
      setQuestions((current) => current.map((question) => String(question.question_id) === questionId ? saved.question : question))
      setAnswers((current) => ({ ...current, [questionId]: answerFromQuestion(saved.question) }))
      setQuestionSaveStates((current) => ({ ...current, [questionId]: { status: 'saved', error: '' } }))
      return saved
    } catch (err) {
      // Keep the institution's draft visible, but never present a failed save as
      // reviewed. The same payload can be retried from the question card.
      setAnswers((current) => ({ ...current, [questionId]: draftAnswer(current[questionId] || next) }))
      setQuestionSaveStates((current) => ({ ...current, [questionId]: { status: 'error', error: err.message } }))
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
    const saved = await update(questionId, { response, response_data: { type: 'contacts', contacts: normalized } }, { reviewed: true })
    if (!saved) return false
    await load()
    return true
  }

  async function confirmAllAnswered() {
    if (pendingSaves > 0) {
      setError(copy('submit.pendingSave'))
      return
    }
    setBusy(true)
    setError('')
    try {
      let allSaved = true
      for (const question of questions) {
        const id = String(question.question_id)
        const answer = answers[id]
        if (!answer?.reviewed && isAnswerValid(answer)) {
          const saved = await update(id, {}, { reviewed: true })
          if (!saved) {
            allSaved = false
            break
          }
        }
      }
      if (allSaved) await load()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function submitQuestionnaire() {
    if (pendingSaves > 0) { setError(copy('submit.pendingSave')); return }
    setSubmitting(true)
    setError('')
    try {
      await submitRiskQuestions(caseId)
      await refreshCase()
      navigate(`/case/${caseId}/review`)
    } catch (err) { setError(err.message); setSubmitDialogOpen(false) } finally { setSubmitting(false) }
  }

  if (!result && !error) return <QuestionnaireState title={copy('loadingTitle')} description={copy('loadingDescription')} badge={t('common:status.loading')} />
  if (result?.status === 'processing') return <QuestionnaireState title={copy('preparingTitle')} description={copy('preparingDescription')} badge={t('common:status.processing')} error={error} debug={DEV_MODE ? result.debug : null} actions={<><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button><Button disabled={busy} onClick={async () => { setBusy(true); try { await load() } finally { setBusy(false) } }}>{busy ? copy('checking') : copy('checkAgain')}</Button></>} />
  if (error && !result) return <QuestionnaireState title={copy('unavailableTitle')} description={copy('unavailableDescription')} badge={t('common:status.actionNeeded')} error={error} actions={<><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button><Button onClick={() => load().catch((err) => setError(err.message))}>{t('common:actions.retry')}</Button></>} />

  return <>
    <PageHeader eyebrow={copy('eyebrow')} title={copy('title')} description={copy('description')} action={<span className="autosave-line">{copy('autosave')}</span>} />
    {DEV_MODE && <div className="alert"><strong>Coverbase debug</strong><br />Session: {result.debug?.coverbase_session_id} · Responses: {result.debug?.questionnaire_response_count} · Processing: {String(result.debug?.is_processing_questions)} · Reviewed: {result.debug?.reviewed_count} · AI generated: {result.debug?.ai_generated_count} · Needs input: {result.debug?.needs_input_count} · Needs review: {result.debug?.needs_review_count}</div>}
    <div className="risk-filter-grid" role="group" aria-label="Filter questions by review status">
      {FILTERS.map((key) => <button className="risk-filter" type="button" aria-pressed={filter === key} onClick={() => setFilter(key)} key={key}><strong>{key === 'all' ? counts.total : counts[key]}</strong><span>{copy(`filters.${key === 'needs-input' ? 'needsInput' : key}`)}</span></button>)}
    </div>
    <div className="risk-bulk-actions"><p><strong>{copy('progress.questionnaire')}</strong><br /><span className="sub">{copy('reviewHelp')}</span></p><Button variant="secondary" disabled={busy || pendingSaves > 0 || !questions.length} onClick={confirmAllAnswered}>{busy ? copy('confirming') : copy('confirmAll')}</Button></div>
    {!questions.length ? <Card title={copy('empty.title')}><p className="sub">{copy('empty.description')}</p></Card> : <div className="questionnaire-layout">
      <QuestionnaireProgress counts={counts} sections={sections} currentSection={currentSection} onSelectSection={setCurrentSection} />
      <main className="questionnaire-section-content">
        <header className="questionnaire-section-header"><div><p className="eyebrow">{copy('section.position', { current: currentSection + 1, total: sections.length })}</p><h2>{activeSection?.name}</h2><p className="sub">{copy('section.description')}</p></div><StatusBadge tone={activeSection?.confirmed === activeSection?.questions.length ? 'success' : 'info'}>{activeSection?.confirmed} / {activeSection?.questions.length}</StatusBadge></header>
        {visibleQuestions.length ? <div className="risk-question-list">{visibleQuestions.map((question) => {
          const id = String(question.question_id)
          return <QuestionRenderer key={id} question={question} answer={answers[id] || {}} state={reviewStateFor(answers[id])} position={questions.indexOf(question) + 1} total={questions.length} saveState={questionSaveStates[id]} onUpdate={update} onSaveContacts={saveContacts} onRetry={() => update(id, {}, { reviewed: true })} />
        })}</div> : <div className="questionnaire-filter-empty"><p>{copy('empty.filtered')}</p><Button variant="quiet" onClick={() => setFilter('all')}>{t('common:actions.clearFilter')}</Button></div>}
        <div className="questionnaire-section-actions">
          <Button variant="secondary" disabled={currentSection === 0} onClick={() => setCurrentSection((index) => Math.max(0, index - 1))}>{copy('section.previous')}</Button>
          {currentSection < sections.length - 1 ? <Button onClick={() => setCurrentSection((index) => Math.min(sections.length - 1, index + 1))}>{copy('section.next')}</Button> : <Button disabled={counts.remaining > 0 || submitting || pendingSaves > 0} onClick={() => setSubmitDialogOpen(true)}>{pendingSaves > 0 ? copy('submit.saving') : copy('submit.action')}</Button>}
        </div>
        {currentSection === sections.length - 1 && <section className={`risk-submit-summary ${counts.remaining === 0 ? 'ready' : ''}`}><h2>{counts.remaining === 0 ? copy('submit.title') : copy('progress.questionnaire')}</h2><p>{counts.remaining === 0 ? copy('submit.description', { count: counts.confirmed }) : copy('progress.remaining', { count: counts.remaining })}</p></section>}
      </main>
    </div>}
    {error && <div className="alert danger">{error}</div>}
    {submitDialogOpen && <div className="modal-backdrop" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="risk-submit-title">
      <h2 id="risk-submit-title">{copy('submit.confirmTitle')}</h2>
      <p>{copy('submit.confirmDescription')}</p>
      <p className="sub">{copy('submit.confirmNext')}</p>
      {submitting ? <div className="loading-row"><span className="spinner" aria-hidden="true" /><strong>{copy('submit.submitting')}</strong></div> : <div className="actions"><Button variant="secondary" onClick={() => setSubmitDialogOpen(false)}>{t('common:actions.back')}</Button><Button onClick={submitQuestionnaire}>{copy('submit.confirmAction')}</Button></div>}
    </section></div>}
  </>
}

function QuestionnaireState({ title, description, badge, error, debug, actions }) {
  const { t } = useTranslation('onboarding')
  return <><PageHeader eyebrow={t('riskQuestions.eyebrow')} title={title} description={description} action={<StatusBadge tone="warning">{badge}</StatusBadge>} /><Card title={title} className="processing-card"><p className="lead">{description}</p>{debug && <p className="sub">Session: {debug.coverbase_session_id} · Responses: {debug.questionnaire_response_count ?? 0} · Processing: {String(debug.is_processing_questions)}</p>}{error && <div className="alert danger">{error}</div>}{actions && <div className="actions">{actions}</div>}</Card></>
}
