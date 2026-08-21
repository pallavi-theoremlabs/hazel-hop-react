import React from "react";
import { useTranslation } from 'react-i18next'
import { NavLink, useLocation, useParams } from 'react-router-dom'
import { stageIndex } from './ProgressTracker'

const NAV_ITEMS = [
  { key: 'NDA_PENDING', labelKey: 'stages.nda', path: 'nda', substepsKey: 'navigation.ndaSubsteps' },
  { key: 'INSTITUTION_PROFILE', labelKey: 'stages.dueDiligence', path: 'due-diligence' },
  { key: 'DOCUMENTS', labelKey: 'stages.documents', path: 'documents', substepsKey: 'navigation.documentSubsteps' },
  { key: 'RISK_QUESTIONS', labelKey: 'stages.riskQuestions', path: 'risk-questions', substepsKey: 'navigation.riskSubsteps' },
  { key: 'HAZEL_REVIEW', labelKey: 'stages.hazelReview', path: 'review' },
]

const FUTURE_ITEMS = [
  { labelKey: 'stages.esign', path: 'esign' },
  { labelKey: 'stages.accountOpening', path: 'account-opening' },
]

export default function AppShell({ caseData, refreshCase, children }) {
  const { t } = useTranslation(['onboarding', 'common'])
  const { caseId } = useParams()
  const { pathname } = useLocation()
  const current = stageIndex(caseData.current_stage)
  const activePath = pathname.split('/').filter(Boolean).at(-1)

  const navState = (index) => index < current ? 'completed' : index === current ? 'current' : 'locked'

  return (
    <div className="shell">
      <header className="topbar">
        <NavLink className="brand" to={`/case/${caseId}/overview`} aria-label="Hazel Network home">
          <img className="brand-logo" src="/assets/hazel-network-logo.svg" alt="Hazel Network" />
        </NavLink>
        <span className="top-spacer" />
        <span className="bank-chip">{caseData.legal_name || 'Synthetic test institution'}</span>
        <span className="avatar" aria-label="Test applicant">{(caseData.primary_applicant_email || 'TT').slice(0, 2).toUpperCase()}</span>
      </header>
      <aside className="sidebar">
        <p className="side-label">{t('common:navigation.onboarding')}</p>
        <NavLink className={({ isActive }) => `nav nav-state-available ${isActive ? 'active' : ''}`} to={`/case/${caseId}/overview`}>
          <i className="nav-state-icon" aria-hidden="true" />
          <span>{t('common:navigation.overview')}</span>
        </NavLink>
        {NAV_ITEMS.map((item, index) => {
          const state = navState(index)
          const active = activePath === item.path
          const marker = state === 'completed' ? '✓' : state === 'current' ? '●' : '▣'
          const label = t(`onboarding:${item.labelKey}`)
          const substeps = item.substepsKey ? t(`onboarding:${item.substepsKey}`, { returnObjects: true }) : null
          return <div className="stage-nav-group" key={item.key}>
            {state === 'locked' ? (
              <span className={`nav nav-state-${state}`} aria-disabled="true">
                <i className="nav-state-icon" aria-hidden="true">{marker}</i><span>{label}</span><small>{t('common:status.locked')}</small>
              </span>
            ) : (
              <NavLink className={`nav nav-state-${state} ${active ? 'active' : ''}`} to={`/case/${caseId}/${item.path}`}>
                <i className="nav-state-icon" aria-hidden="true">{marker}</i><span>{label}</span>{substeps && active && <small>⌃</small>}
              </NavLink>
            )}
            {active && substeps && <div className="stage-nav-substeps">
              {substeps.map((step) => <span className="stage-nav-substep" key={step}>{step}</span>)}
            </div>}
          </div>
        })}
        {FUTURE_ITEMS.map((item) => {
          const active = activePath === item.path
          const available = item.path === 'esign' && Boolean(caseData.esign_eligible)
          if (active || available) return <NavLink className={`nav nav-state-${active ? 'current' : 'available'} ${active ? 'active' : ''}`} to={`/case/${caseId}/${item.path}`} key={item.labelKey}>
            <i className="nav-state-icon" aria-hidden="true">{active ? '●' : ''}</i><span>{t(`onboarding:${item.labelKey}`)}</span><small>{active ? t('common:status.current') : t('common:status.available')}</small>
          </NavLink>
          return <span className="nav nav-state-locked" aria-disabled="true" key={item.labelKey}>
            <i className="nav-state-icon" aria-hidden="true">▣</i><span>{t(`onboarding:${item.labelKey}`)}</span><small>{t('common:status.locked')}</small>
          </span>
        })}
        <div className="side-foot">{t('common:navigation.prototypeFooter')}<br />{t('common:navigation.syntheticData')}</div>
      </aside>
      <main className="page" id="main-content">
        {children}
      </main>
    </div>
  )
}
