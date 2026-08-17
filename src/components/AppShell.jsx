import React from "react";
import { NavLink, useLocation, useParams } from 'react-router-dom'
import DeveloperTestControls from './DeveloperTestControls'
import { stageIndex } from './ProgressTracker'

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true'

const NAV_ITEMS = [
  { key: 'NDA_PENDING', label: 'NDA', path: 'nda', substeps: ['Agreement', 'Acceptance status'] },
  { key: 'INSTITUTION_PROFILE', label: 'Institution Profile', path: 'institution-profile' },
  { key: 'DOCUMENTS', label: 'Documents', path: 'documents', substeps: ['Required document', 'Supporting documents', 'Document repository'] },
  { key: 'DUE_DILIGENCE', label: 'Due Diligence', path: 'due-diligence', substeps: ['Institution Details', 'Primary Contacts'] },
  { key: 'RISK_QUESTIONS', label: 'Risk Questions', path: 'risk-questions', substeps: ['Question sections', 'Review & certification'] },
  { key: 'HAZEL_REVIEW', label: 'Hazel Review', path: 'review' },
]

const FUTURE_ITEMS = [
  { label: 'eSign' },
  { label: 'Account Opening' },
]

export default function AppShell({ caseData, refreshCase, children }) {
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
        <p className="side-label">Onboarding</p>
        <NavLink className={({ isActive }) => `nav nav-state-available ${isActive ? 'active' : ''}`} to={`/case/${caseId}/overview`}>
          <i className="nav-state-icon" aria-hidden="true" />
          <span>Overview</span>
        </NavLink>
        {NAV_ITEMS.map((item, index) => {
          const state = navState(index)
          const active = activePath === item.path
          const marker = state === 'completed' ? '✓' : state === 'current' ? '●' : '▣'
          return <div className="stage-nav-group" key={item.key}>
            {state === 'locked' ? (
              <span className={`nav nav-state-${state}`} aria-disabled="true">
                <i className="nav-state-icon" aria-hidden="true">{marker}</i><span>{item.label}</span><small>Locked</small>
              </span>
            ) : (
              <NavLink className={`nav nav-state-${state} ${active ? 'active' : ''}`} to={`/case/${caseId}/${item.path}`}>
                <i className="nav-state-icon" aria-hidden="true">{marker}</i><span>{item.label}</span>{item.substeps && active && <small>⌃</small>}
              </NavLink>
            )}
            {active && item.substeps && <div className="stage-nav-substeps">
              {item.substeps.map((step) => <span className="stage-nav-substep" key={step}>{step}</span>)}
            </div>}
          </div>
        })}
        {FUTURE_ITEMS.map((item) => <span className="nav nav-state-locked" aria-disabled="true" key={item.label}>
          <i className="nav-state-icon" aria-hidden="true">▣</i><span>{item.label}</span><small>Locked</small>
        </span>)}
        <div className="side-foot">Stakeholder prototype<br />Synthetic data only</div>
      </aside>
      <main className="page" id="main-content">
        {DEV_MODE && <DeveloperTestControls caseData={caseData} refreshCase={refreshCase} />}
        {children}
      </main>
    </div>
  )
}
