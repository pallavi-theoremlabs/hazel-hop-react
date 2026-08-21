import React from "react";
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import AppShell from './components/AppShell'
import { STAGES, stageIndex } from './components/ProgressTracker'
import DocumentsPage from './pages/DocumentsPage'
import HazelReviewPage from './pages/HazelReviewPage'
import InstitutionProfilePage from './pages/InstitutionProfilePage'
import NdaPage from './pages/NdaPage'
import RiskQuestionsPage from './pages/RiskQuestionsPage'
import OverviewPage from './pages/OverviewPage'
import CreateAccountPage from './pages/CreateAccountPage'
import SignInPage from './pages/SignInPage'
import EsignPage from './pages/EsignPage'
import AccountOpeningPage from './pages/AccountOpeningPage'
import { getCase } from './services/api'

const CaseContext = createContext(null)
export const useCaseContext = () => useContext(CaseContext)

function CaseApp() {
  const { t } = useTranslation('common')
  const { caseId } = useParams()
  const [caseData, setCaseData] = useState(null)
  const [error, setError] = useState('')
  const refreshCase = useCallback(() => {
    setError('')
    return getCase(caseId).then((data) => { setCaseData(data); return data })
  }, [caseId])

  useEffect(() => { refreshCase().catch((err) => setError(err.message)) }, [refreshCase])
  if (error) return <div className="center-state"><h1>{t('feedback.caseLoadErrorTitle')}</h1><p>{error}</p></div>
  if (!caseData) return <div className="center-state"><span className="spinner" /><p>{t('feedback.loadingCase')}</p></div>

  return (
    <CaseContext.Provider value={{ caseData, refreshCase }}>
      <AppShell caseData={caseData} refreshCase={refreshCase}>
        <Routes>
          <Route path="overview" element={<OverviewPage />} />
          <Route path="nda" element={<NdaPage />} />
          <Route path="institution-profile" element={<Navigate to="../due-diligence" replace />} />
          <Route path="due-diligence" element={<Guard stage="INSTITUTION_PROFILE"><InstitutionProfilePage /></Guard>} />
          <Route path="documents" element={<Guard stage="DOCUMENTS"><DocumentsPage /></Guard>} />
          <Route path="risk-questions" element={caseData.current_stage === 'HAZEL_REVIEW' ? <Navigate to="../review" replace /> : <Guard stage="RISK_QUESTIONS"><RiskQuestionsPage /></Guard>} />
          <Route path="review" element={<Guard stage="HAZEL_REVIEW"><HazelReviewPage /></Guard>} />
          <Route path="esign" element={<Guard stage="HAZEL_REVIEW"><EsignPage /></Guard>} />
          <Route path="account-opening" element={<Guard stage="HAZEL_REVIEW"><AccountOpeningPage /></Guard>} />
          <Route path="*" element={<Navigate to={`/case/${caseId}/overview`} replace />} />
        </Routes>
      </AppShell>
    </CaseContext.Provider>
  )
}

function Guard({ stage, children }) {
  const { caseData } = useCaseContext()
  if (stageIndex(caseData.current_stage) >= stageIndex(stage)) return children
  const fallback = STAGES[stageIndex(caseData.current_stage)][2]
  return <Navigate to={`../${fallback}`} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/sign-in" replace />} />
      <Route path="/create-account" element={<CreateAccountPage />} />
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/case/:caseId/*" element={<CaseApp />} />
      <Route path="*" element={<Navigate to="/sign-in" replace />} />
    </Routes>
  )
}
