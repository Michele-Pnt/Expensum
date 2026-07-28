"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Typography, Button, IconButton } from "@mui/material";
import { X as CloseIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { useTour } from "@/context/TourContext";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** True se `el` o un suo antenato ha `position: fixed` (es. un Dialog MUI). */
function isInsideFixedContainer(el: HTMLElement): boolean {
  let node: HTMLElement | null = el;
  while (node) {
    if (window.getComputedStyle(node).position === "fixed") return true;
    node = node.parentElement;
  }
  return false;
}

const PADDING = 8;
const TOOLTIP_WIDTH = 320;
const TOOLTIP_HEIGHT_FALLBACK = 240; // stima usata solo prima della prima misurazione reale
const BOTTOM_PAD = 80;      // spazio libero dal basso per input bar e altri elementi fissi
const TRANSITION = "all 0.35s cubic-bezier(0.4, 0, 0.2, 1)";

function getTooltipPosition(
  rect: Rect,
  position: string,
  vh: number,
  vw: number,
  tooltipHeight: number,
  tooltipWidth: number
): { top: number; left: number } {
  const spotTop = rect.top - PADDING;
  const spotBottom = rect.top + rect.height + PADDING;
  const spotLeft = rect.left - PADDING;
  const spotRight = rect.left + rect.width + PADDING;
  const centerX = rect.left + rect.width / 2;

  let top = 0;
  let left = 0;

  if (position === "bottom" || (position !== "top" && spotBottom + tooltipHeight + 16 < vh)) {
    top = spotBottom + 12;
  } else if (position === "top" || spotTop - tooltipHeight - 16 > 0) {
    top = spotTop - tooltipHeight - 12;
  } else {
    top = spotBottom + 12;
  }

  if (position === "right") {
    left = spotRight + 12;
    top = rect.top + rect.height / 2 - tooltipHeight / 2;
  } else if (position === "left") {
    left = spotLeft - tooltipWidth - 12;
    top = rect.top + rect.height / 2 - tooltipHeight / 2;
  } else {
    left = Math.max(12, Math.min(centerX - tooltipWidth / 2, vw - tooltipWidth - 12));
  }

  // Clamp dentro viewport, tenendo conto di elementi fissi in basso (input bar, ecc.)
  top = Math.max(12, Math.min(top, vh - tooltipHeight - BOTTOM_PAD));
  left = Math.max(12, Math.min(left, vw - tooltipWidth - 12));

  return { top, left };
}

export default function TourOverlay() {
  const { isActive, currentStep, steps, nextStep, prevStep, skipTour } = useTour();
  const [targetRect, setTargetRect] = useState<Rect | null>(null);
  const [visible, setVisible] = useState(false);
  const [tooltipHeight, setTooltipHeight] = useState(TOOLTIP_HEIGHT_FALLBACK);
  const observerRef = useRef<ResizeObserver | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const tooltipObserverRef = useRef<ResizeObserver | null>(null);
  const step = steps[currentStep];

  // Misura l'altezza reale del tooltip (il contenuto varia per step, es. TelegramLinkStep
  // è molto più alto della stima di default) per posizionarlo correttamente nel viewport.
  const tooltipRefCallback = useCallback((node: HTMLDivElement | null) => {
    tooltipRef.current = node;
    if (tooltipObserverRef.current) {
      tooltipObserverRef.current.disconnect();
      tooltipObserverRef.current = null;
    }
    if (!node) return;
    setTooltipHeight(node.getBoundingClientRect().height);
    tooltipObserverRef.current = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height;
      if (h) setTooltipHeight(h);
    });
    tooltipObserverRef.current.observe(node);
  }, []);

  const measureTarget = useCallback(() => {
    if (!step) return;
    // Cerca il primo match on-screen con dimensioni reali (evita duplicati hidden o in animazione)
    const candidates = Array.from(document.querySelectorAll(step.selector)) as HTMLElement[];
    const el = candidates.find((c) => {
      const r = c.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.left >= -1 && r.top >= -1;
    }) ?? null;

    if (!el) {
      // Elemento assente o ancora in animazione (es. drawer mobile) — riprova
      if (retryRef.current) clearTimeout(retryRef.current);
      retryRef.current = setTimeout(measureTarget, 120);
      return;
    }

    const r = el.getBoundingClientRect();
    setTargetRect({
      top: r.top + window.scrollY,
      left: r.left + window.scrollX,
      width: r.width,
      height: r.height,
    });
    setVisible(true);

    // Porta l'elemento in foreground (sotto il tooltip)
    el.style.position = el.style.position || "relative";
    el.style.zIndex = "9999";
    el.style.borderRadius = "8px";
    el.style.outline = "2px solid var(--color-primary, #6C5CE7)";
    el.style.outlineOffset = "2px";

    // Osserva resize
    if (observerRef.current) observerRef.current.disconnect();
    observerRef.current = new ResizeObserver(() => {
      const updated = el.getBoundingClientRect();
      setTargetRect({
        top: updated.top + window.scrollY,
        left: updated.left + window.scrollX,
        width: updated.width,
        height: updated.height,
      });
    });
    observerRef.current.observe(el);
  }, [step]);

  // Pulizia stile sull'elemento precedente
  const cleanupPrevElement = useCallback(() => {
    document.querySelectorAll("[data-tour]").forEach((el) => {
      const h = el as HTMLElement;
      h.style.zIndex = "";
      h.style.outline = "";
      h.style.outlineOffset = "";
      h.style.position = "";
    });
  }, []);

  useEffect(() => {
    if (!isActive) {
      cleanupPrevElement();
      setVisible(false);
      setTargetRect(null);
      if (observerRef.current) observerRef.current.disconnect();
      if (tooltipObserverRef.current) tooltipObserverRef.current.disconnect();
      if (retryRef.current) clearTimeout(retryRef.current);
      return;
    }
    cleanupPrevElement();
    setVisible(false);
    setTooltipHeight(TOOLTIP_HEIGHT_FALLBACK);
    // Esegue setup (es. click su tab) poi attende il render prima di misurare
    step.setup?.();
    const t = setTimeout(measureTarget, 200);
    return () => {
      clearTimeout(t);
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [isActive, currentStep, measureTarget, cleanupPrevElement]);

  // Scroll per portare l'elemento nello schermo. Salta gli elementi dentro un
  // contenitore position:fixed (es. un Dialog MUI, centrato nel viewport e
  // indipendente dallo scroll della pagina): scrollIntoView su un elemento del
  // genere sposta comunque lo scroll della pagina sottostante, disallineando
  // spotlight e tooltip (calcolati con lo scrollY misurato in precedenza) dalla
  // posizione reale, sempre ferma, del target.
  useEffect(() => {
    if (!targetRect) return;
    const el = document.querySelector(step?.selector ?? "") as HTMLElement | null;
    if (el && !isInsideFixedContainer(el)) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [targetRect, step]);

  if (!isActive || !step) return null;

  const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;
  const tooltipWidth = Math.min(TOOLTIP_WIDTH, vw - 24);
  // Spazio verticale disponibile per il tooltip: se il contenuto non ci sta, scrolla al suo interno
  // invece di sporgere fuori dallo schermo (importante su telefono, specie in orizzontale).
  const tooltipMaxHeight = vh - BOTTOM_PAD - 24;

  const rect = targetRect ?? { top: vh / 2 - 60, left: vw / 2 - 100, width: 200, height: 120 };
  const scrollTop = typeof window !== "undefined" ? window.scrollY : 0;

  // Coordinate relative al viewport per i pannelli
  const vTop = rect.top - scrollTop;
  const vLeft = rect.left;
  const vRight = vLeft + rect.width;
  const vBottom = vTop + rect.height;

  const spoTop = Math.max(0, vTop - PADDING);
  const spoLeft = Math.max(0, vLeft - PADDING);
  const spoRight = Math.min(vw, vRight + PADDING);
  const spoBottom = Math.min(vh, vBottom + PADDING);

  const tooltipPos = getTooltipPosition(
    { top: spoTop, left: spoLeft, width: spoRight - spoLeft, height: spoBottom - spoTop },
    step.position,
    vh,
    vw,
    Math.min(tooltipHeight, tooltipMaxHeight),
    tooltipWidth
  );

  const isFirst = currentStep === 0;
  const isLast = currentStep === steps.length - 1;
  const stepLabel = `${currentStep + 1} di ${steps.length}`;

  const panelSx = {
    position: "fixed" as const,
    bgcolor: "rgba(0,0,0,0.62)",
    backdropFilter: "blur(1px)",
    zIndex: 9998,
    transition: TRANSITION,
    pointerEvents: "auto" as const,
  };

  return (
    <>
      {/* ── 4 pannelli spotlight — solo quando l'elemento è stato trovato ── */}
      {visible && (
        <>
          {/* Top */}
          <Box sx={{ ...panelSx, top: 0, left: 0, right: 0, height: spoTop }} />

          {/* Bottom */}
          <Box sx={{ ...panelSx, top: spoBottom, left: 0, right: 0, bottom: 0 }} />

          {/* Left */}
          <Box sx={{ ...panelSx, top: spoTop, left: 0, width: spoLeft, height: spoBottom - spoTop }} />

          {/* Right */}
          <Box sx={{ ...panelSx, top: spoTop, left: spoRight, right: 0, height: spoBottom - spoTop }} />
        </>
      )}

      {/* ── Tooltip card ───────────────────────────────────────────────────── */}
      <Box
        ref={tooltipRefCallback}
        sx={{
          position: "fixed",
          zIndex: 10001,
          top: tooltipPos.top,
          left: tooltipPos.left,
          width: tooltipWidth,
          maxHeight: tooltipMaxHeight,
          overflowY: "auto",
          bgcolor: "background.paper",
          borderRadius: "14px",
          boxShadow: "0 8px 40px rgba(0,0,0,0.28), 0 2px 8px rgba(0,0,0,0.12)",
          p: 2.5,
          opacity: 1,
          transform: "translateY(0)",
          transition: TRANSITION,
          border: "1px solid var(--color-border, rgba(255,255,255,0.08))",
          pointerEvents: "auto",
        }}
      >
        {/* Header: step counter + close */}
        <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
          <Typography variant="caption" sx={{ color: "text.secondary", fontWeight: 600, letterSpacing: 0.5 }}>
            {stepLabel}
          </Typography>
          <IconButton size="small" onClick={skipTour} sx={{ p: 0.25, color: "text.secondary" }}>
            <CloseIcon size={16} />
          </IconButton>
        </Box>

        {/* Progress bar */}
        <Box sx={{ width: "100%", height: 3, bgcolor: "divider", borderRadius: 2, mb: 1.5, overflow: "hidden" }}>
          <Box
            sx={{
              height: "100%",
              width: `${((currentStep + 1) / steps.length) * 100}%`,
              background: "linear-gradient(90deg, var(--color-primary, #6C5CE7), #a78bfa)",
              borderRadius: 2,
              transition: TRANSITION,
            }}
          />
        </Box>

        {/* Titolo */}
        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.75, lineHeight: 1.3 }}>
          {step.title}
        </Typography>

        {/* Descrizione — component="div" perché alcuni step (es. connect-telegram)
            annidano elementi block-level (Box, Button); un <p> non può contenerli. */}
        <Typography component="div" variant="body2" color="text.secondary" sx={{ lineHeight: 1.55, mb: 2 }}>
          {step.description}
        </Typography>

        {/* Bottoni navigazione */}
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Button
            size="small"
            variant="text"
            onClick={skipTour}
            sx={{ color: "text.disabled", fontSize: "0.72rem", px: 0.5, minWidth: 0, "&:hover": { color: "text.secondary" } }}
          >
            Salta tour
          </Button>

          <Box sx={{ display: "flex", gap: 1 }}>
            {!isFirst && (
              <Button
                size="small"
                variant="outlined"
                onClick={prevStep}
                startIcon={<ChevronLeft size={14} />}
                sx={{ fontSize: "0.78rem", borderRadius: "8px", px: 1.5, py: 0.5 }}
              >
                Indietro
              </Button>
            )}
            <Button
              size="small"
              variant="contained"
              onClick={nextStep}
              endIcon={isLast ? undefined : <ChevronRight size={14} />}
              sx={{
                fontSize: "0.78rem",
                borderRadius: "8px",
                px: 1.5,
                py: 0.5,
                background: "linear-gradient(135deg, var(--color-primary, #6C5CE7), #8b5cf6)",
                "&:hover": { background: "linear-gradient(135deg, #5a4ad1, #7c3aed)" },
              }}
            >
              {isLast ? "Fatto!" : "Avanti"}
            </Button>
          </Box>
        </Box>
      </Box>
    </>
  );
}
