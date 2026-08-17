import React from "react";
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import ProgressTracker, { STAGES, stageIndex } from '../components/ProgressTracker'
import StatusBadge from '../components/StatusBadge'

const NEXT_STEPS = {
  NDA_PENDING: ['Accept the Mutual NDA', 'Review the agreement and record your electronic acknowledgement.', 'nda', 'Continue'],
  NDA_ACCEPTED: ['Accept the Mutual NDA', 'Review the agreement and record your electronic acknowledgement.', 'nda', 'Continue'],
  INSTITUTION_PROFILE: ['Complete Institution Profile', 'Confirm your institution information and intended relationship.', 'institution-profile', 'Continue'],
  DOCUMENTS: ['Upload the required policy', 'The board-approved BSA/AML/OFAC policy is required.', 'documents', 'Upload required document'],
  DUE_DILIGENCE: ['Complete Due Diligence', 'Review the source-labelled information and complete each section.', 'due-diligence', 'Continue'],
  RISK_QUESTIONS: ['Continue Risk Questions', 'Review and confirm the generated responses.', 'risk-questions', 'Continue'],
  HAZEL_REVIEW: ['Hazel is reviewing your information', 'No action is currently required unless Hazel contacts your institution.', 'review', 'View status'],
}

export default function OverviewPage() {
  const navigate = useNavigate()
  const { caseId } = useParams()
  const { caseData } = useCaseContext()
  const current = stageIndex(caseData.current_stage)
  const [title, copy, path, action] = NEXT_STEPS[caseData.current_stage] || NEXT_STEPS.NDA_ACCEPTED
  const activity = [
    caseData.risk_questions_submitted_at && ['Risk Questions submitted', caseData.risk_questions_submitted_at],
    caseData.due_diligence_completed_at && ['Due Diligence submitted', caseData.due_diligence_completed_at],
    caseData.documents_completed_at && ['Required documents accepted', caseData.documents_completed_at],
    caseData.institution_profile_completed_at && ['Institution Profile completed', caseData.institution_profile_completed_at],
    caseData.nda_accepted_at && ['NDA accepted', caseData.nda_accepted_at],
  ].filter(Boolean)

  return <>
    <PageHeader eyebrow="Member onboarding" title={`Welcome back, ${caseData.legal_name || 'test institution'}`} description="Hazel contact: Avery Morgan · onboarding@hazel.example" action={<StatusBadge tone={current === 5 ? 'info' : 'warning'}>{STAGES[current]?.[1]}</StatusBadge>} />
    <div className="overview-journey">
      <Card title="Your onboarding journey">
        <ProgressTracker currentStage={caseData.current_stage} />
        <p className="sub">Accept the NDA, complete Institution Profile, then continue through Documents, Due Diligence, and Risk Questions. Hazel approval unlocks eSign before Account Opening.</p>
      </Card>
    </div>
    <div className="overview-grid">
      <div>
        <Card title="Your next step">
          <div className="task next-task"><span className="task-icon">1</span><div><strong>{title}</strong><p>{copy}</p></div><Button onClick={() => navigate(`/case/${caseId}/${path}`)}>{action}</Button></div>
        </Card>
        <Card title="Stage access">
          <div className="task-list">
            {STAGES.map(([key, label], index) => {
              const state = index < current ? 'completed' : index === current ? 'current' : 'locked'
              return <div className={`task ${state === 'completed' ? 'complete' : ''}`} key={key}>
                <span className="task-icon">{state === 'completed' ? '✓' : state === 'current' ? '●' : '○'}</span>
                <div><strong>{label}</strong><p>{state === 'completed' ? 'Completed' : state === 'current' ? 'Available now' : 'Complete the prior stage to unlock.'}</p></div>
                <StatusBadge tone={state === 'completed' ? 'success' : state === 'current' ? 'info' : undefined}>{state === 'completed' ? 'Completed' : state === 'current' ? 'Current' : 'Locked'}</StatusBadge>
              </div>
            })}
          </div>
        </Card>
      </div>
      <aside>
        <Card title="Institution profile">
          <ul className="summary-list"><li><strong>Legal name</strong><br />{caseData.legal_name || 'Synthetic test institution'}</li><li><strong>Case ID</strong><br />{caseId}</li></ul>
        </Card>
        <Card title="Recent activity">
          {activity.length ? activity.slice(0, 5).map(([event, time]) => <div className="activity-event" key={event}><span>{new Date(time).toLocaleDateString()}</span><div>{event}</div></div>) : <p className="sub">Your onboarding case is ready to begin.</p>}
        </Card>
      </aside>
    </div>
  </>
}
