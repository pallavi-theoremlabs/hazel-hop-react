import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useCaseContext } from './CaseApp'
import Button from '../../components/shared/Button'
import Card from '../../components/portal/Card'
import PageHeader from '../../components/portal/PageHeader'
import StatusBadge from '../../components/shared/StatusBadge'

export default function EsignPage() {
  const { t } = useTranslation(['onboarding', 'common'])
  const copy = (key) => t(`onboarding:esign.${key}`)
  const navigate = useNavigate()
  const { caseId } = useParams()
  const { caseData } = useCaseContext()

  return <>
    <PageHeader eyebrow={copy('eyebrow')} title={copy('title')} description={copy('description')} action={<StatusBadge tone="warning">{copy('status')}</StatusBadge>} />
    <div className="prototype-placeholder-layout">
      <Card title={copy('agreementTitle')}>
        <div className="document-item-head"><p className="sub">{copy('agreementDescription')}</p><StatusBadge tone="warning">{copy('status')}</StatusBadge></div>
        <div className="alert warning"><strong>{copy('noticeTitle')}</strong><br />{copy('notice')}</div>
        <section className="nda-signer"><h3>{copy('signerTitle')}</h3><p><strong>{caseData.primary_applicant_email || copy('signerFallback')}</strong><br />{caseData.legal_name || copy('institutionFallback')}</p><p>{copy('signerHelp')}</p></section>
        <div className="signing-steps" aria-label={copy('stepsLabel')}>
          {[copy('review'), copy('acknowledge'), copy('sign')].map((label, index) => <div className="task" key={label}><span className="task-icon">{index + 1}</span><div><strong>{label}</strong><p>{copy('stepUnavailable')}</p></div></div>)}
        </div>
        <div className="actions"><Button disabled>{copy('action')}</Button><Button variant="secondary" onClick={() => navigate(`/case/${caseId}/overview`)}>{t('common:actions.returnToOverview')}</Button></div>
      </Card>
    </div>
  </>
}
