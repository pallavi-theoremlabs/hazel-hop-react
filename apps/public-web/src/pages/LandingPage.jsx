import React from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

const MEMBER_PORTAL_URL = (import.meta.env.VITE_MEMBER_PORTAL_URL ?? '').replace(/\/$/, '')

export default function LandingPage() {
  const { t } = useTranslation('public')
  const benefits = t('landing.benefits', { returnObjects: true })
  const signInUrl = `${MEMBER_PORTAL_URL}/sign-in`

  return <div className="public-landing">
    <header className="public-head">
      <Link className="public-brand" to="/" aria-label={t('landing.homeLabel')}><img src="/assets/hazel-network-logo.svg" alt={t('landing.brand')} /></Link>
      <nav aria-label={t('landing.navigationLabel')}><a href="#how-hazel-works">{t('landing.howItWorks')}</a><a href={signInUrl}>{t('landing.signIn')}</a></nav>
    </header>
    <main id="main">
      <section className="public-hero">
        <div><p className="eyebrow">{t('landing.eyebrow')}</p><h1>{t('landing.title')}</h1>
          <div className="landing-decision"><p><strong>{t('landing.newTitle')}</strong> {t('landing.newDescription')}</p><Link className="btn primary" to="/submit-interest">{t('landing.action')}</Link></div>
        </div>
        <div className="hero-art" aria-hidden="true"><span /><span /><span /></div>
      </section>
      <section className="landing-benefits" id="how-hazel-works"><p className="eyebrow">{t('landing.benefitsEyebrow')}</p><h2>{t('landing.benefitsTitle')}</h2><div className="benefit-grid">{benefits.map((benefit) => <article className="card" key={benefit.title}><h3>{benefit.title}</h3><p className="sub">{benefit.description}</p></article>)}</div></section>
    </main>
  </div>
}
