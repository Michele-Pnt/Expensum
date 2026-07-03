"use client";

import { useEffect } from "react";
import "vanilla-cookieconsent/dist/cookieconsent.css";

declare global {
  interface Window {
    // Letto da src/lib/analytics.ts per decidere quali vendor notificare
    // lato server (nessuno script di terze parti viene mai caricato qui).
    __cookieConsentApi?: { acceptedCategory: (category: string) => boolean };
  }
}

export default function CookieConsentBanner(): null {
  useEffect(() => {
    let mounted = true;

    import("vanilla-cookieconsent").then((CC) => {
      if (!mounted) return;

      // Nessuno script di terze parti viene caricato: PostHog/GA4/Meta
      // ricevono gli eventi server-side (vedi src/lib/analytics.ts +
      // /api/track). Qui esponiamo solo lo stato di consenso, letto ad
      // ogni evento per decidere quali vendor notificare lato backend.
      const exposeConsentApi = () => {
        window.__cookieConsentApi = CC;
      };

      CC.run({
        revision: 1,
        cookie: { expiresAfterDays: 182 },

        guiOptions: {
          consentModal: {
            layout: "box",
            position: "bottom right",
            equalWeightButtons: true,
            flipButtons: false,
          },
          preferencesModal: {
            layout: "box",
            equalWeightButtons: true,
            flipButtons: false,
          },
        },

        categories: {
          necessary: { enabled: true, readOnly: true },
          analytics: {},
          marketing: {},
        },

        onFirstConsent: exposeConsentApi,
        onConsent: exposeConsentApi,
        onChange: exposeConsentApi,

        language: {
          default: "it",
          translations: {
            it: {
              consentModal: {
                title: "Usiamo i cookie",
                description:
                  "Usiamo cookie tecnici (necessari) e, con il tuo consenso, cookie analitici e di marketing per migliorare il servizio. Puoi accettare tutto, rifiutare tutto o personalizzare le tue preferenze. Puoi cambiare idea in qualsiasi momento.",
                acceptAllBtn: "Accetta tutto",
                acceptNecessaryBtn: "Rifiuta tutto",
                showPreferencesBtn: "Gestisci preferenze",
                closeIconLabel: "Rifiuta tutto e chiudi",
                footer: `<a href="/privacy">Privacy Policy</a> · <a href="/cookies">Cookie Policy</a>`,
              },
              preferencesModal: {
                title: "Preferenze cookie",
                acceptAllBtn: "Accetta tutto",
                acceptNecessaryBtn: "Rifiuta tutto",
                savePreferencesBtn: "Salva preferenze",
                closeIconLabel: "Chiudi",
                sections: [
                  {
                    title: "Cookie tecnici",
                    description:
                      "Necessari per il funzionamento del sito. Non possono essere disattivati.",
                    linkedCategory: "necessary",
                  },
                  {
                    title: "Cookie analitici",
                    description:
                      "Ci aiutano a capire come usi Expensum (Google Analytics 4, PostHog). I dati sono aggregati e anonimi e vengono inviati dal nostro server, non dal browser.",
                    linkedCategory: "analytics",
                  },
                  {
                    title: "Cookie di marketing",
                    description:
                      "Permettono di mostrare annunci rilevanti su Meta (Facebook/Instagram) e misurare l'efficacia delle campagne. Gli eventi vengono inviati dal nostro server, non dal browser.",
                    linkedCategory: "marketing",
                  },
                  {
                    title: "Ulteriori informazioni",
                    description: `Per domande sulla nostra gestione dei cookie, <a href="mailto:expensum.finance@gmail.com">contattaci</a>.`,
                  },
                ],
              },
            },
          },
        },
      });

      // Copre il caso di consenso già salvato in una sessione precedente,
      // per cui onConsent potrebbe non rifirare in modo osservabile qui.
      exposeConsentApi();
    });

    return () => { mounted = false; };
  }, []);

  return null;
}
