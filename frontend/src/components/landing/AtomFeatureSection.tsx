"use client";

import { useEffect, useRef, useState } from "react";

import { getAtomStep } from "@/lib/atomScroll";
import { isAtomNearViewport } from "@/lib/atomViewport";
import AtomScene from "./AtomScene";
import styles from "./AtomFeatureSection.module.css";

export type AtomFeature = {
  title: string;
  desc: string;
};

type AtomFeatureSectionProps = {
  eyebrow: string;
  title: string;
  intro: string;
  scrollHint: string;
  items: AtomFeature[];
};

export default function AtomFeatureSection({
  eyebrow,
  title,
  intro,
  scrollHint,
  items,
}: AtomFeatureSectionProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const [activeStep, setActiveStep] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [shouldLoadScene, setShouldLoadScene] = useState(false);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;
    const preloadMargin = 500;
    const observer = new IntersectionObserver(() => {
      const rect = section.getBoundingClientRect();
      if (isAtomNearViewport(rect.top, window.innerHeight, preloadMargin)) {
        setShouldLoadScene(true);
        observer.disconnect();
      }
    }, { rootMargin: `${preloadMargin}px 0px` });
    observer.observe(section);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(media.matches);
    updateMotion();
    media.addEventListener("change", updateMotion);
    return () => media.removeEventListener("change", updateMotion);
  }, []);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const section = sectionRef.current;
      if (!section) return;
      const rect = section.getBoundingClientRect();
      const scrollable = Math.max(1, rect.height - window.innerHeight);
      const progress = Math.min(1, Math.max(0, -rect.top / scrollable));
      setActiveStep(getAtomStep(progress, items.length));
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
  }, [items.length]);

  return (
    <section
      ref={sectionRef}
      id="features"
      className={styles.section}
      style={{ "--atom-steps": items.length } as React.CSSProperties}
    >
      <div className={styles.sticky}>
        <div className={styles.atmosphere} aria-hidden="true" />
        <div className={styles.scene} aria-hidden="true">
          {shouldLoadScene ? (
            <AtomScene activeStep={activeStep} reducedMotion={reducedMotion} />
          ) : (
            <div className={styles.scenePlaceholder} />
          )}
        </div>

        <div className={styles.content}>
          <div className={`${styles.introBlock} ${activeStep > 0 ? styles.introBlockCompact : ""}`}>
            <span className={styles.eyebrow}>{eyebrow}</span>
            <h2>{title}</h2>
            <p>{intro}</p>
          </div>

          <div className={styles.featureCopy} aria-live="polite">
            <span className={styles.counter}>
              {String(activeStep + 1).padStart(2, "0")} / {String(items.length).padStart(2, "0")}
            </span>
            {items.map((item, index) => (
              <article
                key={item.title}
                className={`${styles.copyItem} ${index === activeStep ? styles.copyItemActive : ""}`}
                aria-hidden={index !== activeStep}
              >
                <h3>{item.title}</h3>
                <p>{item.desc}</p>
              </article>
            ))}
          </div>

          <div
            className={styles.progress}
            role="progressbar"
            aria-label="Avanzamento funzionalità"
            aria-valuemin={1}
            aria-valuemax={items.length}
            aria-valuenow={activeStep + 1}
          >
            {items.map((item, index) => (
              <span
                key={item.title}
                className={`${styles.progressDot} ${index === activeStep ? styles.progressDotActive : ""}`}
              />
            ))}
          </div>

          <p className={styles.hint}>{scrollHint}</p>
        </div>
      </div>
    </section>
  );
}
