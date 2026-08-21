import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import AppShell from '../../components/portal/AppShell'
import { STAGES, stageIndex } from '../../components/portal/ProgressTracker'
import DocumentsPage from './DocumentsPage'
import HazelReviewPage from './HazelReviewPage'
import InstitutionProfilePage from './InstitutionProfilePage'
import NdaPage from './NdaPage'
import RiskQuestionsPage from './RiskQuestionsPage'
import OverviewPage from './OverviewPage'
import EsignPage from './EsignPage'
import AccountOpeningPage from './AccountOpeningPage'
import { getCase } from '../../services/portal/api'

const CaseContext = createContext(null)
export const useCaseContext = () => useContext(CaseContext)

function Guard({ stage, children }) {
  const { caseData } = useCaseContext()
  if (stageIndex(caseData.current_stage) >= stageIndex(stage)) return children
  const fallback = STAGES[stageIndex(caseData.current_stage)][2]
  return <Navigate to={`../${fallback}`} replace />
}

export default function CaseApp() {
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
