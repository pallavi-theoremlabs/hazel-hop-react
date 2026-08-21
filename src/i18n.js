import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import common from './locales/en/common.json'
import publicContent from './locales/en/public.json'

// Only the two namespaces the public routes render, loaded eagerly so a
// visitor who never leaves the public site never pays for portal copy.
// portal.json and onboarding.json are added at runtime by
// loadPortalTranslations(), called from the lazy portal/case route chunk in
// App.jsx, so they ship in that chunk's bundle instead of this one.
i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: {
        common,
        public: publicContent,
      },
    },
    lng: 'en',
    fallbackLng: 'en',
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    returnEmptyString: false,
  })

export async function loadPortalTranslations() {
  if (i18n.hasResourceBundle('en', 'portal')) return
  const [{ default: portal }, { default: onboarding }] = await Promise.all([
    import('./locales/en/portal.json'),
    import('./locales/en/onboarding.json'),
  ])
  i18n.addResourceBundle('en', 'portal', portal)
  i18n.addResourceBundle('en', 'onboarding', onboarding)
}

export default i18n
