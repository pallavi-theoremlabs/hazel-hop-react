import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import SubmitInterestPage from './pages/SubmitInterestPage'

// /case/:caseId/* is the member portal's
// and is deliberately absent here — those pages are not imported, so they are
// not in this bundle. The handoff to that app happens as a document navigation
// from SubmitInterestPage, not as a route.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/submit-interest" element={<SubmitInterestPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
