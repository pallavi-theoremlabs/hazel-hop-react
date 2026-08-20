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
  ...STAGES,
  ['ESIGN', 'stages.esign', 'esign'],
  ['ACCOUNT_OPENING', 'stages.accountOpening', 'account-opening'],
]

export const stageIndex = (stage) => {
  if (stage === 'NDA_ACCEPTED') return 0
  if (stage === 'DUE_DILIGENCE') return STAGES.findIndex(([key]) => key === 'RISK_QUESTIONS')
  return Math.max(0, STAGES.findIndex(([key]) => key === stage))
}

export default function ProgressTracker({ currentStage }) {
  const { t } = useTranslation('onboarding')
  const current = stageIndex(currentStage)
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
