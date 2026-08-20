import React from "react";
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from '../App'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import ProgressTracker, { STAGES, stageIndex } from '../components/ProgressTracker'
import StatusBadge from '../components/StatusBadge'

const NEXT_STEPS = {
  NDA_PENDING: ['ndaTitle', 'ndaDescription', 'nda', 'common:actions.continue'],
  NDA_ACCEPTED: ['ndaTitle', 'ndaDescription', 'nda', 'common:actions.continue'],
  INSTITUTION_PROFILE: ['dueDiligenceTitle', 'dueDiligenceDescription', 'due-diligence', 'common:actions.continue'],
  DOCUMENTS: ['documentsTitle', 'documentsDescription', 'documents', 'overview.documentsAction'],
  DUE_DILIGENCE: ['riskTitle', 'riskDescription', 'risk-questions', 'common:actions.continue'],
  RISK_QUESTIONS: ['riskTitle', 'riskDescription', 'risk-questions', 'common:actions.continue'],
  HAZEL_REVIEW: ['reviewTitle', 'reviewDescription', 'review', 'overview.viewStatus'],
}

export default function OverviewPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const navigate = useNavigate()
  const { caseId } = useParams()
  const { caseData } = useCaseContext()
  const current = stageIndex(caseData.current_stage)
  const [titleKey, copyKey, path, actionKey] = NEXT_STEPS[caseData.current_stage] || NEXT_STEPS.NDA_ACCEPTED
  const overviewText = (key, options) => t(`onboarding:overview.${key}`, options)
  const activity = [
    caseData.risk_questions_submitted_at && [overviewText('activity.riskSubmitted'), caseData.risk_questions_submitted_at],
    caseData.documents_completed_at && [overviewText('activity.documentsAccepted'), caseData.documents_completed_at],
    caseData.institution_profile_completed_at && [overviewText('activity.dueDiligenceCompleted'), caseData.institution_profile_completed_at],
    caseData.nda_accepted_at && [overviewText('activity.ndaAccepted'), caseData.nda_accepted_at],
  ].filter(Boolean)

  return <>
    <PageHeader eyebrow={overviewText('eyebrow')} title={overviewText('welcome', { institution: caseData.legal_name || 'test institution' })} description={overviewText('contact')} action={<StatusBadge tone={current === 4 ? 'info' : 'warning'}>{t(`onboarding:${STAGES[current]?.[1]}`)}</StatusBadge>} />
    <div className="overview-journey">
      <Card title={overviewText('journeyTitle')}>
        <ProgressTracker currentStage={caseData.current_stage} />
        <p className="sub">{overviewText('journeyDescription')}</p>
      </Card>
    </div>
    <div className="overview-grid">
      <div>
        <Card title={overviewText('nextStep')}>
          <div className="task next-task"><span className="task-icon">1</span><div><strong>{overviewText(titleKey)}</strong><p>{overviewText(copyKey)}</p></div><Button onClick={() => navigate(`/case/${caseId}/${path}`)}>{t(actionKey.includes(':') ? actionKey : `onboarding:${actionKey}`)}</Button></div>
        </Card>
      </div>
      <aside>
        <Card title={overviewText('institutionDetails')}>
          <ul className="summary-list"><li><strong>{overviewText('legalName')}</strong><br />{caseData.legal_name || 'Synthetic test institution'}</li><li><strong>{overviewText('caseId')}</strong><br />{caseId}</li></ul>
        </Card>
        <Card title={overviewText('recentActivity')}>
          {activity.length ? activity.slice(0, 5).map(([event, time]) => <div className="activity-event" key={event}><span>{new Date(time).toLocaleDateString()}</span><div>{event}</div></div>) : <p className="sub">{overviewText('ready')}</p>}
        </Card>
      </aside>
    </div>
  </>
}
