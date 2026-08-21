import React from "react";
import { useTranslation } from 'react-i18next'

export const STAGES = [
  ['NDA_PENDING', 'stages.nda', 'nda'],
  ['INSTITUTION_PROFILE', 'stages.dueDiligence', 'due-diligence'],
  ['DOCUMENTS', 'stages.documents', 'documents'],
  ['RISK_QUESTIONS', 'stages.riskQuestions', 'risk-questions'],
  ['HAZEL_REVIEW', 'stages.hazelReview', 'review'],
]

const PROGRESS_STAGES = [
  ['ELIGIBILITY', 'stages.eligibility'],
  ['REGISTRATION', 'stages.registration'],
  ['NDA', 'stages.nda'],
  ['DOCUMENTS', 'stages.documents'],
  ['RISK_QUESTIONS', 'stages.riskQuestions'],
  ['HAZEL_REVIEW', 'stages.hazelReview'],
  ['ESIGN', 'stages.esign'],
  ['ACCOUNT_OPENING', 'stages.accountOpening'],
]

export const stageIndex = (stage) => {
  if (stage === 'NDA_ACCEPTED') return 0
  if (stage === 'DUE_DILIGENCE') return STAGES.findIndex(([key]) => key === 'RISK_QUESTIONS')
  return Math.max(0, STAGES.findIndex(([key]) => key === stage))
}

export default function ProgressTracker({ currentStage }) {
  const { t } = useTranslation('onboarding')
  const current = progressIndex(currentStage)
  return (
    <div className="tracker" aria-label="Onboarding progress">
      {PROGRESS_STAGES.map(([key, labelKey], index) => (
        <div key={key} className={`track ${index < current ? 'done' : index === current ? 'current' : ''}`}>
          <div className="track-bar" />
          <span>{t(labelKey)}</span>
        </div>
      ))}
    </div>
  )
}

function progressIndex(stage) {
  if (stage === 'NDA_PENDING') return 2
  if (['NDA_ACCEPTED', 'INSTITUTION_PROFILE', 'DOCUMENTS'].includes(stage)) return 3
  if (['DUE_DILIGENCE', 'RISK_QUESTIONS'].includes(stage)) return 4
  if (stage === 'HAZEL_REVIEW') return 5
  if (stage === 'ESIGN') return 6
  if (stage === 'ACCOUNT_OPENING') return 7
  return 2
}
