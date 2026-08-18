import React from 'react'
import { useTranslation } from 'react-i18next'

export default function QuestionnaireProgress({ counts, sections, currentSection, onSelectSection }) {
  const { t } = useTranslation('onboarding')
  return <aside className="questionnaire-progress" aria-label={t('riskQuestions.progress.sections')}>
    <div className="questionnaire-progress-summary">
      <span>{t('riskQuestions.progress.questionnaire')}</span>
      <strong>{t('riskQuestions.progress.reviewed', { reviewed: counts.confirmed, total: counts.total })}</strong>
      <div className="progress" aria-hidden="true"><span style={{ width: `${counts.total ? Math.round((counts.confirmed / counts.total) * 100) : 0}%` }} /></div>
      <small>{t('riskQuestions.progress.remaining', { count: counts.remaining })}</small>
    </div>
    <nav className="questionnaire-section-nav">
      <h2>{t('riskQuestions.progress.sections')}</h2>
      {sections.map((section, index) => {
        const complete = section.confirmed === section.questions.length && section.questions.length > 0
        const started = section.confirmed > 0 || section.needsInput < section.questions.length
        const state = complete ? 'complete' : started ? 'in-progress' : 'not-started'
        return <button type="button" className={`questionnaire-section-link ${currentSection === index ? 'active' : ''}`} aria-current={currentSection === index ? 'step' : undefined} onClick={() => onSelectSection(index)} key={section.key}>
          <span className={`questionnaire-section-marker ${state}`}>{complete ? '✓' : index + 1}</span>
          <span><strong>{section.name}</strong><small>{section.confirmed} / {section.questions.length} · {t(`riskQuestions.progress.section${complete ? 'Complete' : started ? 'InProgress' : 'NotStarted'}`)}</small></span>
        </button>
      })}
    </nav>
  </aside>
}
