import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import common from './locales/en/common.json'
import onboarding from './locales/en/onboarding.json'
import publicContent from './locales/en/public.json'

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: {
        common,
        onboarding,
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
