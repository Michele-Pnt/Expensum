"use client";

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getCsrfToken } from "@/lib/csrf";
import TelegramLinkStep from "@/components/TelegramLinkStep";
import { trackTourCompleted, trackTourSkipped, trackTourStarted, trackTourStepViewed } from "@/lib/analytics";

export interface TourStep {
  id: string;
  page: string;
  selector: string;
  title: string;
  description: React.ReactNode;
  position: "top" | "bottom" | "left" | "right" | "center";
  /** Eseguita prima di cercare il target (es. click su una tab per renderizzare il contenuto) */
  setup?: () => void;
}

interface TourContextValue {
  isActive: boolean;
  currentStep: number;
  steps: TourStep[];
  startTour: () => void;
  nextStep: () => void;
  prevStep: () => void;
  skipTour: () => void;
}

const TOUR_PENDING_KEY = "expensum_tour_pending";
const TOUR_DONE_KEY = "expensum_tour_done";
const TOUR_STEP_KEY = "expensum_tour_step";
const TOUR_DEMO_KEY = "expensum_demo_active";

export const TOUR_STEPS: TourStep[] = [
  {
    id: "home-summary",
    page: "/home",
    selector: '[data-tour="home-summary"]',
    title: "Home",
    description:
      "Ogni volta che apri Expensum parti da qui: quanto ti resta da spendere questo mese e i tuoi ultimi movimenti.",
    position: "bottom",
  },
  {
    id: "quick-capture",
    page: "/home",
    selector: '[data-tour="quick-capture-button"]',
    title: "Registra",
    description:
      "Da qualsiasi pagina, tocca Registra per aggiungere una spesa o un'entrata: scrivila, dettala a voce o fotografa lo scontrino. Expensum la riconosce e te la fa sempre confermare prima di salvarla.",
    position: "bottom",
  },
  {
    id: "analytics-tabs",
    page: "/analytics",
    selector: '[data-tour="analytics-tabs"]',
    title: "Analytics",
    description: (
      <>
        <strong>Oggi</strong> mostra quanto ti resta e la salute finanziaria, <strong>Esplora</strong>{" "}
        i grafici per categoria, entrata o conto, <strong>Pianifica</strong> i tuoi budget. Con il
        piano <span style={{ color: "#5FC4CB", fontWeight: 700 }}>Pro</span> analizzi fino a 24 mesi
        di storico.
      </>
    ),
    position: "bottom",
  },
  {
    id: "spazio-conti",
    page: "/spazio",
    selector: '[data-tour="spazio-conti"]',
    title: "Gestisci: Conti",
    description:
      "Qui gestisci tutto. Inizia aggiungendo i tuoi conti correnti, carte e contanti: Expensum terrà traccia del saldo reale per ciascuno.",
    position: "bottom",
    setup: () => {
      const tabs = document.querySelectorAll('[data-tour="spazio-tabs"] [role="tab"]');
      (tabs[0] as HTMLElement | undefined)?.click();
    },
  },
  {
    id: "spazio-categorie",
    page: "/spazio",
    selector: '[data-tour="spazio-categorie"]',
    title: "Gestisci: Categorie",
    description:
      "Personalizza le categorie di spesa e imposta un budget mensile per ciascuna: riceverai un avviso quando stai per sforarlo. Una breve descrizione aiuta l'assistente a riconoscere anche le spese più ambigue.",
    position: "bottom",
    setup: () => {
      // Clicca la tab Categorie (indice 1) per renderizzare il contenuto
      const tabs = document.querySelectorAll('[data-tour="spazio-tabs"] [role="tab"]');
      (tabs[1] as HTMLElement | undefined)?.click();
    },
  },
  {
    id: "primary-navigation",
    page: "/spazio",
    selector: '[data-tour="primary-navigation"]',
    title: "Navigazione",
    description:
      "Home, Analytics, Registra e Gestisci sono sempre a portata di mano: dalla barra laterale su computer, "
      + "dalla barra in basso su telefono. Sotto \"Altro\" trovi anche Obiettivi di risparmio, Report automatici e il resto.",
    position: "bottom",
  },
  {
    id: "connect-telegram",
    page: "/home",
    selector: '[data-tour="tour-final"]',
    title: "📲 Collega Telegram",
    description: <TelegramLinkStep />,
    position: "center",
  },
  {
    id: "tour-complete",
    page: "/home",
    selector: '[data-tour="tour-final"]',
    title: "🎉 Ora sai come funziona!",
    description: (
      <>
        Quello che hai visto erano <strong>dati di esempio</strong>: li cancelliamo adesso e il tuo spazio è
        pronto per iniziare davvero. Tocca <strong>Fine</strong> e parte!
      </>
    ),
    position: "center",
  },
];

const TourContext = createContext<TourContextValue | null>(null);

export function useTour(): TourContextValue {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used inside TourProvider");
  return ctx;
}

export function TourProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [isActive, setIsActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const isNavigating = useRef(false);

  const endTour = useCallback((done: boolean) => {
    if (done) {
      trackTourCompleted();
    } else {
      const step = TOUR_STEPS[currentStep];
      if (step) trackTourSkipped(step.id, currentStep);
    }
    setIsActive(false);
    setCurrentStep(0);
    try {
      const demoActive = localStorage.getItem(TOUR_DEMO_KEY) === "true";
      localStorage.removeItem(TOUR_PENDING_KEY);
      localStorage.removeItem(TOUR_STEP_KEY);
      localStorage.removeItem(TOUR_DEMO_KEY);
      if (done) {
        localStorage.setItem(TOUR_DONE_KEY, "true");
        if (demoActive) {
          // Pulizia demo data fire-and-forget
          getCsrfToken().then((csrfToken) => {
            fetch("/api/demo/clear", {
              method: "POST",
              headers: { "X-CSRFToken": csrfToken },
              credentials: "same-origin",
            }).catch(() => {});
          }).catch(() => {});
        }
      }
    } catch {
      // localStorage non disponibile (SSR o privacy mode)
    }
  }, [currentStep]);

  const startTour = useCallback(() => {
    trackTourStarted();
    setCurrentStep(0);
    setIsActive(true);
  }, []);

  const skipTour = useCallback(() => endTour(false), [endTour]);

  const navigateToStep = useCallback(
    (step: TourStep) => {
      if (typeof window === "undefined") return;
      const currentPath = window.location.pathname;
      if (currentPath !== step.page && !isNavigating.current) {
        isNavigating.current = true;
        router.push(step.page);
        // reset flag dopo la navigazione
        setTimeout(() => {
          isNavigating.current = false;
        }, 800);
      }
    },
    [router]
  );

  const nextStep = useCallback(() => {
    const next = currentStep + 1;
    if (next >= TOUR_STEPS.length) {
      endTour(true);
      return;
    }
    try { localStorage.setItem(TOUR_STEP_KEY, String(next)); } catch { /* ignore */ }
    setCurrentStep(next);
    navigateToStep(TOUR_STEPS[next]);
    trackTourStepViewed(TOUR_STEPS[next].id, next);
  }, [currentStep, endTour, navigateToStep]);

  const prevStep = useCallback(() => {
    const next = Math.max(0, currentStep - 1);
    try { localStorage.setItem(TOUR_STEP_KEY, String(next)); } catch { /* ignore */ }
    setCurrentStep(next);
    navigateToStep(TOUR_STEPS[next]);
    trackTourStepViewed(TOUR_STEPS[next].id, next);
  }, [currentStep, navigateToStep]);

  // Controlla il flag localStorage al mount (solo client).
  // Ogni pagina ha il proprio TourProvider, quindi persiste lo step corrente
  // in localStorage per riprendere dal punto giusto dopo la navigazione.
  // Supporta anche ?tour=1&demo=1 come query param (percorso Bot Mini App).
  useEffect(() => {
    let restoreTimer: number | undefined;
    try {
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        if (params.get("tour") === "1") localStorage.setItem(TOUR_PENDING_KEY, "true");
        if (params.get("demo") === "1") localStorage.setItem(TOUR_DEMO_KEY, "true");
      }
      const pending = localStorage.getItem(TOUR_PENDING_KEY);
      const done = localStorage.getItem(TOUR_DONE_KEY);
      if (pending === "true" && done !== "true") {
        const savedStep = parseInt(localStorage.getItem(TOUR_STEP_KEY) ?? "0", 10);
        const safeStep = isNaN(savedStep) ? 0 : Math.min(savedStep, TOUR_STEPS.length - 1);
        // Rimanda il ripristino dopo il mount: evita un aggiornamento sincrono
        // nell'effetto e mantiene invariato il ripristino del tour al reload.
        restoreTimer = window.setTimeout(() => {
          setCurrentStep(safeStep);
          setIsActive(true);
          // Il tour riprende da dove era rimasto, ma la pagina di atterraggio
          // (oggi la Home) può non essere quella dello step: senza questa
          // navigazione l'overlay cercherebbe all'infinito un selettore che su
          // questa pagina non esiste, e il tour resterebbe invisibile.
          const step = TOUR_STEPS[safeStep];
          if (step && window.location.pathname !== step.page) {
            router.push(step.page);
          }
        }, 0);
      }
    } catch {
      // silently ignore
    }
    return () => {
      if (restoreTimer !== undefined) window.clearTimeout(restoreTimer);
    };
  }, [router]);

  return (
    <TourContext.Provider value={{ isActive, currentStep, steps: TOUR_STEPS, startTour, nextStep, prevStep, skipTour }}>
      {children}
    </TourContext.Provider>
  );
}
