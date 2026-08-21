import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from './CaseApp'
import Button from '../../components/shared/Button'
import Card from '../../components/portal/Card'
import PageHeader from '../../components/portal/PageHeader'
import StatusBadge from '../../components/shared/StatusBadge'

const PACKAGE_KEYS = ['signatureCard', 'resolution', 'wireAgreement', 'terms', 'disclosures']

export default function AccountOpeningPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = (key) => t(`onboarding:accountOpening.${key}`)
  const navigate = useNavigate()
  const { caseId } = useParams()
  const { caseData } = useCaseContext()

  return <>
    <PageHeader eyebrow={copy('eyebrow')} title={copy('title')} description={copy('description')} action={<StatusBadge tone="warning">{copy('status')}</StatusBadge>} />
    <div className="account-opening-layout">
      <div>
        <Card title={copy('setupTitle')}>
          <div className="readonly-detail-grid">
            <Detail label={copy('institution')} value={caseData.legal_name || copy('institutionFallback')} />
            <Detail label={copy('nature')} value={copy('natureValue')} />
            <Detail label={copy('model')} value={copy('modelValue')} />
            <Detail label={copy('operations')} value={caseData.primary_applicant_email || copy('operationsValue')} />
          </div>
          <div className="alert warning"><strong>{copy('assumptionTitle')}</strong><br />{copy('assumption')}</div>
        </Card>
        <Card title={copy('packageTitle')} subtitle={copy('packageDescription')}>
          <div className="task-list">{PACKAGE_KEYS.map((key) => <div className="task" key={key}><span className="task-icon">○</span><div><strong>{copy(`packages.${key}`)}</strong><p>{copy('packageUnavailable')}</p></div><StatusBadge tone="warning">{copy('waiting')}</StatusBadge></div>)}</div>
        </Card>
      </div>
      <aside>
        <Card title={copy('strategyTitle')}><p className="sub">{copy('strategyDescription')}</p><div className="alert warning"><strong>{copy('integrationTitle')}</strong><br />{copy('integrationDescription')}</div></Card>
        <Card title={copy('signersTitle')}><div className="task"><span className="task-icon">1</span><div><strong>{copy('signerPending')}</strong><p>{copy('signerDescription')}</p></div></div></Card>
      </aside>
    </div>
    <div className="actions"><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button><Button disabled>{copy('action')}</Button></div>
  </>
}

function Detail({ label, value }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}
