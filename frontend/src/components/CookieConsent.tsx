"use client";

import { useEffect } from "react";
import "vanilla-cookieconsent/dist/cookieconsent.css";

declare global {
  interface Window {
    // Letto da src/lib/analytics.ts per decidere quali vendor notificare
    // lato server (PostHog/Meta restano server-side; GA4 usa anche gtag.js,
    // vedi loadGoogleAnalytics sotto).
    __cookieConsentApi?: { acceptedCategory: (category: string) => boolean };
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

// Unico script di terze parti caricato nel browser, e solo dopo consenso
// "analytics": gtag.js serve a GA4 per calcolare sessioni/engagement/
// attribuzione sorgente traffico, impossibili da ricostruire lato server
// (Measurement Protocol da solo non basta, vedi analytics.py::track_ga4).
// Gli eventi custom di prodotto continuano ad arrivare a GA4 server-side
// come oggi; solo il page_view "grezzo" lo gestisce gtag.js in autonomia,
// per non contare due volte la stessa pageview.
let gaLoaded = false;
function loadGoogleAnalytics(): void {
  if (gaLoaded) return;
  const measurementId = process.env.NEXT_PUBLIC_GA4_MEASUREMENT_ID;
  if (!measurementId) return;
  gaLoaded = true;

  const script = document.createElement("script");
  script.src = `https://www.googletagmanager.com/gtag/js?id=${measurementId}`;
  script.async = true;
  document.head.appendChild(script);

  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag(...args: unknown[]) {
    window.dataLayer!.push(args);
  };
  // Consent Mode: gtag.js applica di default "negato" per utenti in area
  // UE finché non riceve questo segnale esplicito — anche se lo script
  // viene caricato SOLO dopo che il nostro banner ha già raccolto il
  // consenso "analytics" (quindi qui è sempre accurato dichiararlo concesso).
  // Senza questa chiamata lo script si carica ma non invia mai dati.
  window.gtag("consent", "default", {
    analytics_storage: "granted",
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
  });
  window.gtag("js", new Date());
  window.gtag("config", measurementId, { anonymize_ip: true });
}

export default function CookieConsentBanner(): null {
  useEffect(() => {
    let mounted = true;

    import("vanilla-cookieconsent").then((CC) => {
      if (!mounted) return;

      // PostHog/Meta restano server-side (vedi src/lib/analytics.ts +
      // /api/track): qui esponiamo lo stato di consenso, letto ad ogni
      // evento per decidere quali vendor notificare lato backend. GA4 in
      // più carica gtag.js nel browser quando la categoria "analytics" è
      // accettata (mai altrimenti).
      //
      // CC.run() è dietro un import() dinamico: __cookieConsentApi non esiste
      // ancora quando i componenti montati in root layout (es. PageViewTracker)
      // fanno la loro prima chiamata di tracking, che quindi viene scartata
      // fail-closed. L'evento "cc:consent-changed" permette a chi ha già
      // provato a tracciare di ritentare non appena il consenso è disponibile.
      const exposeConsentApi = () => {
        window.__cookieConsentApi = CC;
        if (CC.acceptedCategory("analytics")) loadGoogleAnalytics();
        window.dispatchEvent(new Event("cc:consent-changed"));
      };

      CC.run({
        // Bump da 1 a 2: il consenso "analitici" ora comporta anche il
        // caricamento di uno script di terze parti (gtag.js) nel browser,
        // non solo invio server-side — chi aveva già acconsentito sotto le
        // vecchie condizioni deve poterlo rivedere.
        revision: 2,
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
                      "Ci aiutano a capire come usi Expensum. PostHog riceve i dati dal nostro server, in forma aggregata e anonima. Google Analytics 4 carica invece uno script nel tuo browser (necessario per riconoscere sessioni e provenienza del traffico) e imposta i cookie _ga.",
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
