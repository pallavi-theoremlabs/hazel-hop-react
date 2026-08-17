import React from "react";

export const STAGES = [
  ['NDA_PENDING', 'NDA', 'nda'],
  ['INSTITUTION_PROFILE', 'Institution Profile', 'institution-profile'],
  ['DOCUMENTS', 'Documents', 'documents'],
  ['DUE_DILIGENCE', 'Due Diligence', 'due-diligence'],
  ['RISK_QUESTIONS', 'Risk Questions', 'risk-questions'],
  ['HAZEL_REVIEW', 'Hazel Review', 'review'],
]

const PROGRESS_STAGES = [
  ...STAGES,
  ['ESIGN', 'eSign', 'esign'],
  ['ACCOUNT_OPENING', 'Account Opening', 'account-opening'],
]

export const stageIndex = (stage) => {
  if (stage === 'NDA_ACCEPTED') return 0
  return Math.max(0, STAGES.findIndex(([key]) => key === stage))
}

export default function ProgressTracker({ currentStage }) {
  const current = stageIndex(currentStage)
  return (
    <div className="tracker" aria-label="Onboarding progress">
      {PROGRESS_STAGES.map(([key, label], index) => (
        <div key={key} className={`track ${index < current ? 'done' : index === current ? 'current' : ''}`}>
          <div className="track-bar" />
          <span>{label}</span>
        </div>
      ))}
    </div>
  )
}
