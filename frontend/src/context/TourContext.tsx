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
    id: "chat-input",
    page: "/chat",
    selector: '[data-tour="chat-input"]',
    title: "Chat con Expensum",
    description:
      "Scrivi una spesa in linguaggio naturale, carica la foto di uno scontrino oppure registra un messaggio vocale. Expensum capisce tutto.",
    position: "top",
  },
  {
    id: "chat-messages",
    page: "/chat",
    selector: '[data-tour="chat-messages"]',
    title: "Storico conversazioni",
    description:
      "Ogni spesa viene confermata prima di essere salvata. Se hai sbagliato importo o categoria, puoi annullare con un click.",
    position: "top",
  },
  {
    id: "analytics-period",
    page: "/analytics",
    selector: '[data-tour="analytics-period"]',
    title: "Intervallo temporale",
    description: (
      <>
        Scegli quanti mesi di storico analizzare. Con il piano{" "}
        <span style={{ color: "#C5A059", fontWeight: 700 }}>Pro</span> puoi guardare fino a 24 mesi
        di dati per scoprire trend di lungo periodo.
      </>
    ),
    position: "bottom",
  },
  {
    id: "analytics-tabs",
    page: "/analytics",
    selector: '[data-tour="analytics-tabs"]',
    title: "Analytics",
    description:
      "Cinque tab con grafici interattivi: panoramica del capitale, analisi spese, entrate, lista transazioni e monitoraggio budget.",
    position: "bottom",
  },
  {
    id: "goals-header",
    page: "/goals",
    selector: '[data-tour="goals-header"]',
    title: "🎯 Obiettivi di risparmio",
    description: (
      <>
        Fissa un obiettivo — risparmio netto, saldo di un conto, capitale totale o riduzione di
        una spesa — ed Expensum ne traccia l&apos;avanzamento automaticamente, stimando anche
        quando lo raggiungerai. Disponibile con il piano{" "}
        <span style={{ color: "#C5A059", fontWeight: 700 }}>Pro</span>.
      </>
    ),
    position: "bottom",
  },
  {
    id: "reports-list",
    page: "/reports",
    selector: '[data-tour="reports-list"]',
    title: "Report automatici",
    description:
      "Expensum genera ogni settimana e ogni mese un report completo delle tue finanze. Puoi condividerlo o consultarlo in qualsiasi momento.",
    position: "center",
  },
  {
    id: "spazio-conti",
    page: "/spazio",
    selector: '[data-tour="spazio-conti"]',
    title: "Il tuo spazio — Conti",
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
    title: "Categorie & Budget",
    description:
      "Personalizza le categorie di spesa e imposta un budget mensile per ciascuna. Riceverai un avviso quando stai per sforarlo.",
    position: "bottom",
    setup: () => {
      // Clicca la tab Categorie (indice 1) per renderizzare il contenuto
      const tabs = document.querySelectorAll('[data-tour="spazio-tabs"] [role="tab"]');
      (tabs[1] as HTMLElement | undefined)?.click();
    },
  },
  {
    id: "spazio-categoria-dettaglio",
    page: "/spazio",
    selector: '[data-tour="entity-dialog"]',
    title: "La scheda di una categoria",
    description: (
      <>
        <strong>Nome</strong> e <strong>budget mensile</strong> li conosci già. La{" "}
        <strong>descrizione</strong> è facoltativa ma preziosa: spiega con parole tue quando usare
        questa categoria (es. &quot;spese per uscire fuori a cena o pranzo&quot;) e aiuta
        l&apos;assistente a categorizzare correttamente anche le spese più ambigue.
      </>
    ),
    position: "right",
    setup: () => {
      // Riapre la tab Categorie (per sicurezza se si torna indietro nel tour) e
      // apre la scheda della prima categoria per mostrare il form con il campo descrizione.
      const tabs = document.querySelectorAll('[data-tour="spazio-tabs"] [role="tab"]');
      (tabs[1] as HTMLElement | undefined)?.click();
      window.setTimeout(() => {
        const editBtn = document.querySelector('[data-tour="category-edit-button"]') as HTMLElement | null;
        editBtn?.click();
      }, 50);
    },
  },
  {
    id: "sidebar-nav",
    page: "/spazio",
    selector: '[data-tour="sidebar-nav"]',
    title: "Navigazione",
    description:
      "Puoi tornare in qualsiasi sezione in qualsiasi momento dalla barra laterale.",
    position: "bottom",
    setup: () => {
      // Chiude la scheda categoria aperta dallo step precedente, se ancora aperta.
      const closeBtn = document.querySelector('[data-tour="entity-dialog-close"]') as HTMLElement | null;
      closeBtn?.click();

      // Su mobile il drawer è chiuso: lo apriamo prima di cercare il target
      const nav = document.querySelector('[data-tour="sidebar-nav"]') as HTMLElement | null;
      const isHidden = !nav || nav.getBoundingClientRect().width === 0;
      if (isHidden) {
        const btn = document.querySelector('[data-action="sidebar-open"]') as HTMLElement | null;
        btn?.click();
      }
    },
  },
  {
    id: "connect-telegram",
    page: "/chat",
    selector: '[data-tour="tour-final"]',
    title: "📲 Collega Telegram",
    description: <TelegramLinkStep />,
    position: "center",
  },
  {
    id: "tour-complete",
    page: "/chat",
    selector: '[data-tour="tour-final"]',
    title: "🎉 Ora sai come funziona!",
    description: (
      <>
        Quello che hai visto erano <strong>dati di esempio</strong> — li cancelliamo adesso e il tuo spazio è
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
        setCurrentStep(safeStep);
        setIsActive(true);
      }
    } catch {
      // silently ignore
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <TourContext.Provider value={{ isActive, currentStep, steps: TOUR_STEPS, startTour, nextStep, prevStep, skipTour }}>
      {children}
    </TourContext.Provider>
  );
}
