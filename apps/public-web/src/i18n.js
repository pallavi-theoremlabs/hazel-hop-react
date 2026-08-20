import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import common from './locales/en/common.json'
import publicContent from './locales/en/public.json'

// Only the two namespaces this app renders. onboarding.json stays with the
// member portal — nothing here reads it, and registering it would put 16 KB of
// member copy into the public bundle.
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

export default i18n
