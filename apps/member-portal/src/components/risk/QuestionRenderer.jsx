import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Button from '../Button'
import StatusBadge from '../StatusBadge'
import { canAcceptSuggestedAnswer, commentChanged, isAnswerEmpty, isMemberEdited, suggestedAnswerFor, textResponseChanged } from './riskQuestionState'

const EMPTY_CONTACT = { name: '', title: '', email: '', phone_number: '', linkedin: '' }

export default function QuestionRenderer({ question, answer, state, position, total, saveState, onUpdate, onSaveContacts, onRetry }) {
  const { t } = useTranslation('onboarding')
  const id = String(question.question_id)
  const type = question.response_type
  const empty = isAnswerEmpty(answer)
  const badge = state === 'confirmed' ? 'question.confirmed' : state === 'needs-input' ? 'question.answerNeeded' : 'question.reviewRequired'
  const tone = state === 'confirmed' ? 'success' : state === 'needs-input' ? 'warning' : 'info'
  const memberEdited = isMemberEdited(question, answer)
  const saving = saveState?.status === 'saving'
  const sourceLabels = suggestionSourceLabels(question, t)

  function selectOne(option) {
    onUpdate(id, { response: option.label, selected_option_ids: [option.id] }, { reviewed: true })
  }

  function selectMultiple(option, checked) {
    const selected = new Set(answer.selected_option_ids || [])
    if (checked) selected.add(option.id)
    else selected.delete(option.id)
    const selectedIds = (question.options || []).map((item) => item.id).filter((optionId) => selected.has(optionId))
    const response = (question.options || []).filter((item) => selected.has(item.id)).map((item) => item.label).join(', ')
    onUpdate(id, { response, selected_option_ids: selectedIds }, { reviewed: true })
  }

  return <article className={`risk-question-card ${state === 'confirmed' ? 'confirmed' : 'attention'}`}>
    <div className="question-meta">
      <span className="question-number">{t('riskQuestions.question.position', { current: position, total })}</span>
    </div>
    <h2>{question.question_text}</h2>
    <div className="question-state-row"><StatusBadge tone={tone}>{t(`riskQuestions.${badge}`)}</StatusBadge></div>
    <div className="question-hierarchy">
      <div className="question-detail risk-suggested-answer">
        <span className="question-detail-label">{t('riskQuestions.question.suggestedAnswer')}</span>
        <p>{suggestedAnswerFor(question) || t('riskQuestions.question.noSuggestion')}</p>
        {sourceLabels.length > 0 && <div className="question-source-list">{sourceLabels.map((label) => <span className="source-chip suggested" key={label}>{label}</span>)}</div>}
      </div>
      <details className="reasoning"><summary>{t('riskQuestions.question.whySuggested')}</summary><p>{question.detailed_reasoning || question.reasoning || t('riskQuestions.question.noReasoning')}</p>{(question.ai_confidence || question.confidence) && <p className="sub">{t('riskQuestions.question.confidence', { confidence: question.ai_confidence || question.confidence })}</p>}</details>
      <div className="field risk-inline-editor">
        <div className="risk-institution-answer-heading"><label htmlFor={`risk-answer-${id}`}>{t('riskQuestions.question.institutionAnswer')}</label>{memberEdited && <span className="source-chip institution">{t('riskQuestions.question.memberEdited')}</span>}</div>
        {(type === 'select_one' || type === 'single_select') && (question.options || []).map((option) => <label className="choice" key={option.id}><input type="radio" name={`risk-answer-${id}`} checked={(answer.selected_option_ids || []).includes(option.id)} onChange={() => selectOne(option)} /><span>{option.label}</span></label>)}
        {(type === 'select_multiple' || type === 'multi_select') && (question.options || []).map((option) => <label className="choice" key={option.id}><input type="checkbox" checked={(answer.selected_option_ids || []).includes(option.id)} onChange={(event) => selectMultiple(option, event.target.checked)} /><span>{option.label}</span></label>)}
        {type === 'contacts' && <ContactEditor initialContacts={answer.response_data?.type === 'contacts' ? answer.response_data.contacts : []} onSave={(contacts) => onSaveContacts(id, contacts)} />}
        {!['select_one', 'single_select', 'select_multiple', 'multi_select', 'contacts'].includes(type) && <textarea id={`risk-answer-${id}`} className="input" value={answer.response || ''} onChange={(event) => onUpdate(id, { response: event.target.value }, { persist: false })} onBlur={() => { if (textResponseChanged(question, answer)) onUpdate(id, { response: answer.response ?? '' }, { reviewed: true }) }} />}
      </div>
      <div className="field question-comment-field"><label htmlFor={`risk-comment-${id}`}>{t('riskQuestions.question.comment')} <span className="muted">{t('riskQuestions.question.optional')}</span></label><textarea id={`risk-comment-${id}`} className="input" placeholder={t('riskQuestions.question.commentPlaceholder')} value={answer.comment || ''} onChange={(event) => onUpdate(id, { comment: event.target.value }, { persist: false })} onBlur={() => { if (commentChanged(question, answer)) onUpdate(id, { comment: answer.comment ?? '' }, { reviewed: true }) }} /></div>
      {saveState?.status === 'error' && <div className="alert danger risk-question-save-error" role="alert"><span>{t('riskQuestions.question.saveError', { message: saveState.error })}</span><Button type="button" variant="secondary" onClick={onRetry}>{t('riskQuestions.question.retrySave')}</Button></div>}
      {canAcceptSuggestedAnswer(question, answer) && saveState?.status !== 'error' && type !== 'contacts' && <div className="risk-question-confirm"><Button type="button" variant="secondary" disabled={empty || saving} onClick={() => onUpdate(id, {}, { reviewed: true })}>{saving ? t('riskQuestions.question.saving') : t('riskQuestions.question.acceptSuggested')}</Button></div>}
    </div>
    <p className="provenance">{state === 'confirmed' ? t('riskQuestions.question.provenanceReviewed') : t('riskQuestions.question.provenancePending')}{saveState?.status === 'saved' ? ` · ${t('riskQuestions.question.saved')}` : ''}</p>
  </article>
}

function suggestionSourceLabels(question, t) {
  const labels = []
  if (question.is_ai_generated || question.original_ai_response != null || Array.isArray(question.original_ai_selected_option_ids)) {
    labels.push(t('riskQuestions.question.generated'))
  }
  const providerLabels = [question.source_label, question.source]
    .filter((value) => typeof value === 'string' && value.trim())
    .map((value) => value.trim())
  labels.push(...providerLabels)
  if (Array.isArray(question.supporting_document_ids) && question.supporting_document_ids.length > 0) {
    labels.push(t('riskQuestions.question.documentEvidence'))
  }
  return [...new Set(labels)]
}

function ContactEditor({ initialContacts, onSave }) {
  const { t } = useTranslation('onboarding')
  const signature = JSON.stringify(initialContacts || [])
  const [contacts, setContacts] = useState(() => normalizeContacts(initialContacts))
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)

  useEffect(() => { setContacts(normalizeContacts(initialContacts)); setErrors([]) }, [signature])
  const update = (index, field, value) => setContacts((current) => current.map((contact, contactIndex) => contactIndex === index ? { ...contact, [field]: value } : contact))

  async function save() {
    const nextErrors = validateContacts(contacts, t)
    setErrors(nextErrors)
    if (nextErrors.length) return
    setSaving(true)
    try { await onSave(contacts) } finally { setSaving(false) }
  }

  return <div className="risk-contact-editor">
    <p className="hint">{t('riskQuestions.contacts.help')}</p>
    {errors.length > 0 && <div className="alert danger risk-contact-errors"><strong>{t('riskQuestions.contacts.validationTitle')}</strong><ul>{errors.map((message) => <li key={message}>{message}</li>)}</ul></div>}
    <div className="risk-contact-list">{contacts.map((contact, index) => <fieldset className="risk-contact-card" key={index}>
      <legend>{t('riskQuestions.contacts.contact', { number: index + 1 })}</legend>
      <div className="risk-contact-grid">
        <ContactField label={t('riskQuestions.contacts.name')} required value={contact.name} onChange={(value) => update(index, 'name', value)} autoComplete="name" />
        <ContactField label={t('riskQuestions.contacts.title')} value={contact.title} onChange={(value) => update(index, 'title', value)} autoComplete="organization-title" />
        <ContactField label={t('riskQuestions.contacts.email')} type="email" value={contact.email} onChange={(value) => update(index, 'email', value)} autoComplete="email" />
        <ContactField label={t('riskQuestions.contacts.phone')} type="tel" value={contact.phone_number} onChange={(value) => update(index, 'phone_number', value)} autoComplete="tel" />
        <ContactField className="span-2" label={t('riskQuestions.contacts.linkedin')} type="url" value={contact.linkedin} onChange={(value) => update(index, 'linkedin', value)} placeholder={t('riskQuestions.contacts.linkedinPlaceholder')} />
      </div>
      {contacts.length > 1 && <Button type="button" variant="quiet" onClick={() => setContacts((current) => current.filter((_, itemIndex) => itemIndex !== index))}>{t('riskQuestions.contacts.remove')}</Button>}
    </fieldset>)}</div>
    <div className="actions risk-contact-actions"><Button type="button" variant="secondary" disabled={contacts.length >= 6 || saving} onClick={() => setContacts((current) => [...current, { ...EMPTY_CONTACT }])}>{t('riskQuestions.contacts.add')}</Button><span className="hint">{t('riskQuestions.contacts.count', { count: contacts.length })}</span><Button type="button" disabled={saving} onClick={save}>{saving ? t('riskQuestions.contacts.saving') : t('riskQuestions.contacts.save')}</Button></div>
  </div>
}

function ContactField({ label, required, onChange, className = '', ...props }) {
  return <label className={className}><span>{label}{required && <span className="required"> *</span>}</span><input className="input" onChange={(event) => onChange(event.target.value)} {...props} /></label>
}

function normalizeContacts(contacts) {
  if (!Array.isArray(contacts) || contacts.length === 0) return [{ ...EMPTY_CONTACT }]
  return contacts.slice(0, 6).map((contact) => ({ name: String(contact?.name || ''), title: String(contact?.title || ''), email: String(contact?.email || ''), phone_number: String(contact?.phone_number || ''), linkedin: String(contact?.linkedin || '') }))
}

function validateContacts(contacts, t) {
  if (!contacts.length || contacts.length > 6) return [t('riskQuestions.contacts.rangeError')]
  const errors = []
  contacts.forEach((contact, index) => {
    const number = index + 1
    if (!contact.name.trim()) errors.push(t('riskQuestions.contacts.nameError', { number }))
    if (!contact.email.trim() && !contact.phone_number.trim()) errors.push(t('riskQuestions.contacts.methodError', { number }))
    if (contact.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact.email.trim())) errors.push(t('riskQuestions.contacts.emailError', { number }))
    if (contact.phone_number.trim() && (!/^[0-9+\-\s()]+$/.test(contact.phone_number.trim()) || contact.phone_number.trim().length < 5 || contact.phone_number.trim().length > 20)) errors.push(t('riskQuestions.contacts.phoneError', { number }))
    if (contact.linkedin.trim() && !contact.linkedin.includes('linkedin.com/in')) errors.push(t('riskQuestions.contacts.linkedinError', { number }))
  })
  return errors
}
