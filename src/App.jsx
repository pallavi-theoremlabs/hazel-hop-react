import React, { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import LandingPage from './pages/public/LandingPage'
import SubmitInterestPage from './pages/public/SubmitInterestPage'
import { loadPortalTranslations } from './i18n'

const IntegrationHomePage = lazy(() =>
  Promise.all([import('./pages/portal/IntegrationHomePage'), loadPortalTranslations()]).then(([module]) => module)
)
const CaseApp = lazy(() =>
  Promise.all([import('./pages/portal/CaseApp'), loadPortalTranslations()]).then(([module]) => module)
)

function PortalFallback() {
  return <div className="center-state"><span className="spinner" /></div>
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/submit-interest" element={<SubmitInterestPage />} />
      <Route path="/portal" element={<Suspense fallback={<PortalFallback />}><IntegrationHomePage /></Suspense>} />
      <Route path="/case/:caseId/*" element={<Suspense fallback={<PortalFallback />}><CaseApp /></Suspense>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
