"use client";

import { useEffect } from "react";
import "vanilla-cookieconsent/dist/cookieconsent.css";

declare global {
  interface Window {
    dataLayer: unknown[];
    gtag: (...args: unknown[]) => void;
    fbq: ((...args: unknown[]) => void) & { callMethod?: (...args: unknown[]) => void; queue: unknown[][]; push: (...args: unknown[]) => void; loaded: boolean; version: string };
    _fbq?: Window["fbq"];
    posthog: { init: (key: string, opts: Record<string, unknown>) => void; opt_in_capturing: () => void; opt_out_capturing: () => void };
  }
}

function loadScript(src: string, id?: string): void {
  if (id && document.getElementById(id)) return;
  const s = document.createElement("script");
  s.src = src;
  s.async = true;
  if (id) s.id = id;
  document.head.appendChild(s);
}

function initGA4(): void {
  const gaId = process.env.NEXT_PUBLIC_GA_ID;
  if (!gaId) return;
  loadScript(`https://www.googletagmanager.com/gtag/js?id=${gaId}`, "gtag-loader");
  window.dataLayer = window.dataLayer || [];
  window.gtag = function (...args: unknown[]) { window.dataLayer.push(args); };
  window.gtag("js", new Date());
  window.gtag("config", gaId);
}

function initMetaPixel(): void {
  const pixelId = process.env.NEXT_PUBLIC_META_PIXEL_ID;
  if (!pixelId || typeof window.fbq !== "undefined") return;
  const n = function (...args: unknown[]) {
    n.callMethod ? n.callMethod(...args) : n.queue.push(args);
  } as Window["fbq"];
  n.push = n;
  n.loaded = true;
  n.version = "2.0";
  n.queue = [];
  window.fbq = n;
  if (!window._fbq) window._fbq = n;
  const s = document.createElement("script") as HTMLScriptElement;
  s.async = true;
  s.src = "https://connect.facebook.net/en_US/fbevents.js";
  document.head.appendChild(s);
  window.fbq("init", pixelId);
  window.fbq("track", "PageView");
}

function initPostHog(): void {
  const phKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  const phHost = process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com";
  if (!phKey) return;
  if (typeof window.posthog !== "undefined") {
    window.posthog.opt_in_capturing();
    return;
  }
  loadScript(`${phHost}/static/array.js`, "posthog-loader");
}

export default function CookieConsentBanner(): null {
  useEffect(() => {
    let mounted = true;

    import("vanilla-cookieconsent").then((CC) => {
      if (!mounted) return;

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
          analytics: {
            autoClear: {
              cookies: [{ name: /^(_ga|_gid|ph_|posthog)/ }],
            },
          },
          marketing: {
            autoClear: {
              cookies: [{ name: /^(_fbp|_fbc)/ }],
            },
          },
        },

        onFirstConsent: () => {
          if (CC.acceptedCategory("analytics")) {
            initGA4();
            initPostHog();
          }
          if (CC.acceptedCategory("marketing")) {
            initMetaPixel();
          }
        },

        onConsent: () => {
          if (CC.acceptedCategory("analytics")) {
            initGA4();
            initPostHog();
          }
          if (CC.acceptedCategory("marketing")) {
            initMetaPixel();
          }
        },

        onChange: () => {
          if (CC.acceptedCategory("analytics")) {
            initGA4();
            initPostHog();
          } else if (typeof window.posthog !== "undefined") {
            window.posthog.opt_out_capturing();
          }
          if (CC.acceptedCategory("marketing")) {
            initMetaPixel();
          }
        },

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
                      "Ci aiutano a capire come usi Expensum (Google Analytics 4, PostHog). I dati sono aggregati e anonimi.",
                    linkedCategory: "analytics",
                    cookieTable: {
                      headers: { name: "Cookie", domain: "Dominio", desc: "Descrizione" },
                      body: [
                        { name: "_ga, _gid", domain: "expensum.it", desc: "Google Analytics — identifica sessioni utente (anonimo)" },
                        { name: "ph_*", domain: "expensum.it", desc: "PostHog — analytics prodotto (anonimo)" },
                      ],
                    },
                  },
                  {
                    title: "Cookie di marketing",
                    description:
                      "Permettono di mostrare annunci rilevanti su Meta (Facebook/Instagram) e misurare l'efficacia delle campagne.",
                    linkedCategory: "marketing",
                    cookieTable: {
                      headers: { name: "Cookie", domain: "Dominio", desc: "Descrizione" },
                      body: [
                        { name: "_fbp, _fbc", domain: "expensum.it", desc: "Meta Pixel — tracciamento conversioni" },
                      ],
                    },
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
    });

    return () => { mounted = false; };
  }, []);

  return null;
}
