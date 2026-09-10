"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { getAtomStep } from "@/lib/atomScroll";
import { getHowScreenType, type HowScreenType } from "./howItWorksScreens";
import styles from "./HowItWorksSection.module.css";

export type HowStep = {
  title: string;
  desc: string;
};

type HowItWorksSectionProps = {
  titleLine1: string;
  titleLine2: string;
  scrollHint: string;
  steps: HowStep[];
};

function ProductScreen({ type }: { type: HowScreenType }) {
  if (type === "chat") {
    return (
      <div className={styles.productScreen}>
        <div className={styles.screenTopbar}><span>Expensum</span><i /></div>
        <div className={styles.chatLabel}>NUOVA SPESA</div>
        <div className={`${styles.chatBubble} ${styles.chatBubbleUser}`}>
          Spesa supermercato 42,80€
        </div>
        <div className={styles.chatBubble}>
          <span className={styles.aiDot} /> Registrata e categorizzata
          <strong>Alimentari · Conto personale</strong>
        </div>
        <div className={styles.chatComposer}>Scrivi una spesa… <b>↑</b></div>
      </div>
    );
  }

  if (type === "analysis") {
    return (
      <div className={styles.productScreen}>
        <div className={styles.screenTopbar}><span>Analisi AI</span><em>in corso</em></div>
        <div className={styles.analysisReceipt}>
          <span className={styles.receiptLineLong} /><span className={styles.receiptLineShort} />
          <strong>42,80 €</strong>
        </div>
        <div className={styles.analysisRows}>
          <div><span>Importo</span><b>42,80 €</b></div>
          <div><span>Categoria</span><b>Alimentari</b></div>
          <div><span>Conto</span><b>Personale</b></div>
        </div>
        <div className={styles.analysisStatus}><span className={styles.aiDot} /> Dati strutturati automaticamente</div>
      </div>
    );
  }

  if (type === "dashboard") {
    return (
      <div className={styles.productScreen}>
        <div className={styles.screenTopbar}><span>Panoramica</span><em>Questo mese</em></div>
        <div className={styles.dashboardMetric}><span>Spese totali</span><strong>1.248,30 €</strong><small>↓ 8,4% rispetto al mese scorso</small></div>
        <div className={styles.chart} aria-hidden="true">
          <span /><span /><span /><span /><span /><span /><span />
        </div>
        <div className={styles.dashboardFooter}><span>Budget utilizzato</span><b>68%</b></div>
        <div className={styles.progress}><i /></div>
      </div>
    );
  }

  return (
    <div className={styles.productScreen}>
      <div className={styles.screenTopbar}><span>Report mensile</span><em>Giugno 2026</em></div>
      <div className={styles.reportHeadline}><span>Il tuo mese in sintesi</span><strong>Stabile</strong></div>
      <div className={styles.reportStats}><div><b>1.248 €</b><span>Spese</span></div><div><b>+320 €</b><span>Risparmio</span></div></div>
      <div className={styles.reportInsight}><span className={styles.aiDot} /> Hai speso meno in ristoranti questo mese.</div>
      <div className={styles.reportBars}><i /><i /><i /><i /><i /></div>
    </div>
  );
}

export default function HowItWorksSection({
  titleLine1,
  titleLine2,
  scrollHint,
  steps,
}: HowItWorksSectionProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const section = sectionRef.current;
      if (!section) return;
      const rect = section.getBoundingClientRect();
      const scrollable = Math.max(1, rect.height - window.innerHeight);
      const progress = Math.min(1, Math.max(0, -rect.top / scrollable));
      setActiveStep(getAtomStep(progress, steps.length));
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [steps.length]);

  const activeScreen = getHowScreenType(activeStep);

  return (
    <section
      ref={sectionRef}
      id="come-funziona"
      className={styles.section}
      style={{ "--how-steps": steps.length } as React.CSSProperties}
    >
      <div className={styles.sticky}>
        <div className={styles.backdrop} aria-hidden="true" />

        <div className={styles.content}>
          <h2>{titleLine1}<br />{titleLine2}</h2>

          <div className={styles.stage}>
            <span className={styles.stepNumber}>{activeStep + 1}</span>
            <div className={styles.copyStack} aria-live="polite">
              {steps.map((step, index) => (
                <article
                  key={step.title}
                  className={`${styles.stepCopy} ${index === activeStep ? styles.stepCopyActive : ""}`}
                  aria-hidden={index !== activeStep}
                >
                  <h3>{step.title}</h3>
                  <p>{step.desc}</p>
                </article>
              ))}
            </div>
            <div className={styles.screenCard} aria-hidden="true">
              <ProductScreen type={activeScreen} />
            </div>
          </div>

          <div
            className={styles.dots}
            role="progressbar"
            aria-label="Avanzamento guida"
            aria-valuemin={1}
            aria-valuemax={steps.length}
            aria-valuenow={activeStep + 1}
          >
            {steps.map((step, index) => (
              <span
                key={step.title}
                className={`${styles.dot} ${index === activeStep ? styles.dotActive : ""}`}
              />
            ))}
          </div>

          <p className={styles.hint}>
            <ChevronDown size={16} strokeWidth={1.5} aria-hidden="true" />
            {scrollHint}
          </p>
        </div>
      </div>
    </section>
  );
}
