"use client";
/* eslint-disable @next/next/no-img-element */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { MessageCircle, BarChart2, CreditCard, FileText, Check, Send, Sparkles, TrendingUp, BellRing, ChevronDown } from "lucide-react";
import styles from "./page.module.css";

const FEATURES = [
  {
    icon: <MessageCircle size={20} strokeWidth={1.5} />,
    title: "Chatbot AI su Telegram",
    desc: "Invia spese via testo, foto scontrino o vocale. Nessuna app da aprire, nessun form da compilare.",
  },
  {
    icon: <BarChart2 size={20} strokeWidth={1.5} />,
    title: "Analytics & Dashboard",
    desc: "Grafici chiari su categorie, trend mensili e andamento del capitale. Sempre aggiornati.",
  },
  {
    icon: <CreditCard size={20} strokeWidth={1.5} />,
    title: "Abbonamenti automatici",
    desc: "Traccia Netflix, Spotify, palestra e tutti i ricorrenti. Ricevi notifiche prima di ogni addebito.",
  },
  {
    icon: <FileText size={20} strokeWidth={1.5} />,
    title: "Report mensili",
    desc: "Ogni fine mese un riepilogo completo arriva direttamente su Telegram. Niente da fare.",
  },
];

const HOW_STEPS = [
  {
    icon: <Send size={18} strokeWidth={1.5} />,
    title: "Invia la spesa.",
    desc: "Scrivila in chat, scatta una foto allo scontrino o manda un vocale. Expensum capisce tutto.",
  },
  {
    icon: <Sparkles size={18} strokeWidth={1.5} />,
    title: "L’AI la analizza.",
    desc: "Il modello AI categorizza e struttura i dati in automatico. Zero errori, zero sforzo.",
  },
  {
    icon: <TrendingUp size={18} strokeWidth={1.5} />,
    title: "Dashboard aggiornata.",
    desc: "Visualizza grafici, trend e budget in tempo reale dalla web app o direttamente su Telegram.",
  },
  {
    icon: <BellRing size={18} strokeWidth={1.5} />,
    title: "Report automatico.",
    desc: "Ogni mese ricevi un riepilogo completo con analisi delle spese e consigli personalizzati.",
  },
];

const FREE_FEATURES = [
  "Registrazione spese illimitata",
  "Categorie personalizzabili",
  "Report mensile via Telegram",
  "Sincronizzazione Notion",
];

const PREMIUM_FEATURES = [
  "Tutto del piano Free",
  "Analytics avanzati con grafici",
  "Previsioni e trend mensili",
  "Gestione abbonamenti automatica",
  "Storico 24 mesi",
  "Budget per categoria",
];

const FOR_WHO = [
  {
    title: "Studenti fuori sede",
    desc: "Affitto, spesa, uscite — tante voci, zero chiarezza. Expensum ti mostra dove finiscono i soldi.",
  },
  {
    title: "Giovani professionisti",
    desc: "Stipendio fisso ma fine mese sempre uguale? Scopri dove ottimizzare senza rinunciare a nulla.",
  },
  {
    title: "Chiunque voglia più controllo",
    desc: "Non serve essere un esperto di finanza. Basta parlare con Expensum come faresti con un amico.",
  },
];

export default function LandingPage() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            (e.target as HTMLElement).classList.add("revealed");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  const scrollToSection = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <>
      {/* ── Navbar ── */}
      <nav className={`${styles.nav} ${scrolled ? styles.navScrolled : ""}`}>
        <div className={styles.navInner}>
          <div className={styles.navLogo}>
            <img src="/logo-expensum-icon.png" alt="Expensum" className={styles.navLogoIcon} />
            <img src="/scritta_expensum.png" alt="Expensum" className={styles.navLogoText} />
          </div>
          <div className={styles.navLinks}>
            <button className={styles.navLink} onClick={() => scrollToSection("come-funziona")}>
              Come funziona
            </button>
            <button className={styles.navLink} onClick={() => scrollToSection("prezzi")}>
              Prezzi
            </button>
          </div>
          <div className={styles.navActions}>
            <Link href="/login" className={styles.btnGhost}>
              Accedi alla web app
            </Link>
            <a
              href="https://t.me/ExspensumBot"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.btnPrimary}
            >
              Apri su Telegram
            </a>
          </div>
        </div>
      </nav>

      <main>
        {/* ── Hero ── */}
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroLeft}>
              <p className={styles.heroPill}>Powered by AI</p>
              <h1 className={styles.heroHeadline}>
                Il tuo compagno<br />del risparmio.
              </h1>
              <p className={styles.heroSub}>
                Traccia le spese via Telegram. L’AI le analizza.<br />
                Tu capisci i tuoi soldi.
              </p>
              <div className={styles.heroActions}>
                <a
                  href="https://t.me/ExspensumBot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.btnPrimary}
                >
                  Apri su Telegram →
                </a>
                <button
                  className={styles.btnGhost}
                  onClick={() => scrollToSection("come-funziona")}
                >
                  Come funziona
                </button>
              </div>
            </div>

            <div className={styles.heroRight}>
              <div className={styles.deviceFrame}>
                <div className={styles.deviceBar}>
                  <span className={styles.deviceDot} />
                  <span className={styles.deviceDot} />
                  <span className={styles.deviceDot} />
                  <span className={styles.deviceUrl}>expensum.it/analytics</span>
                </div>
                <div className={styles.deviceScreen}>
                  {/* Dashboard preview mockup */}
                  <div className={styles.mockHeader}>
                    <span className={styles.mockGreeting}>Buongiorno, Michele</span>
                    <span className={styles.mockBadge}>Premium</span>
                  </div>
                  <div className={styles.mockStats}>
                    <div className={styles.mockStat}>
                      <span className={styles.mockStatLabel}>Spese questo mese</span>
                      <span className={styles.mockStatValue}>€ 1.240</span>
                    </div>
                    <div className={styles.mockStat}>
                      <span className={styles.mockStatLabel}>Risparmio</span>
                      <span className={styles.mockStatValueGold}>+ € 380</span>
                    </div>
                  </div>
                  <div className={styles.mockChart}>
                    {[65, 80, 45, 90, 60, 75, 50].map((h, i) => (
                      <div key={i} className={styles.mockBar} style={{ height: `${h}%` }} />
                    ))}
                  </div>
                  <div className={styles.mockCategories}>
                    {["Spesa", "Ristoranti", "Trasporti", "Svago"].map((c, i) => (
                      <div key={i} className={styles.mockCategoryRow}>
                        <span className={styles.mockCategoryName}>{c}</span>
                        <div className={styles.mockCategoryBar}>
                          <div
                            className={styles.mockCategoryFill}
                            style={{ width: `${[70, 45, 30, 20][i]}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <button
            className={styles.heroScroll}
            onClick={() => scrollToSection("per-chi")}
            aria-label="Scorri in basso"
          >
            <ChevronDown size={20} strokeWidth={1.5} />
          </button>
        </section>

        {/* ── Per chi è pensato ── */}
        <section id="per-chi" className={styles.section}>
          <div className={styles.sectionInner}>
            <div className={styles.sectionHeadLeft}>
              <h2 className={styles.sectionH2} data-reveal>
                Per chi è pensato<br />Expensum.
              </h2>
            </div>
            <div className={styles.forWhoList}>
              {FOR_WHO.map((item, i) => (
                <div key={i} className={styles.forWhoItem} data-reveal>
                  <span className={styles.forWhoNum}>0{i + 1}</span>
                  <div>
                    <strong className={styles.forWhoTitle}>{item.title}</strong>
                    <span className={styles.forWhoDesc}> {item.desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Features ── */}
        <section id="features" className={styles.sectionAlt}>
          <div className={styles.sectionInner}>
            <h2 className={styles.sectionH2Full} data-reveal>
              Cosa fa Expensum.{" "}
              <span className={styles.h2Muted}>Tutto il necessario,</span>
              <br />
              <span className={styles.h2Muted}>niente di superfluo.</span>
            </h2>
            <div className={styles.featureGrid} data-reveal>
              {FEATURES.map((f, i) => (
                <div key={i} className={styles.featureCard}>
                  <div className={styles.featureIcon}>{f.icon}</div>
                  <h3 className={styles.featureTitle}>{f.title}</h3>
                  <p className={styles.featureDesc}>{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className={styles.dividerLine} />

        {/* ── Come funziona (Timeline) ── */}
        <section id="come-funziona" className={styles.section}>
          <div className={styles.sectionInner}>
            <h2 className={styles.sectionH2Center} data-reveal>
              Come funziona.<br />Semplice e veloce.
            </h2>

            <div className={styles.timeline}>
              <div className={styles.timelineLine} />
              {HOW_STEPS.map((step, i) => (
                <div
                  key={i}
                  className={`${styles.timelineRow} ${i % 2 === 1 ? styles.timelineRowRight : ""}`}
                  data-reveal
                >
                  <div className={styles.timelineCard}>
                    <div className={styles.timelineStep}>{i + 1}</div>
                    <div className={styles.timelineIcon}>{step.icon}</div>
                    <div>
                      <strong className={styles.timelineTitle}>{step.title}</strong>
                      <span className={styles.timelineDesc}> {step.desc}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Pricing ── */}
        <section id="prezzi" className={styles.sectionAlt}>
          <div className={styles.sectionInner}>
            <h2 className={styles.sectionH2Full} data-reveal>
              Scegli il tuo piano.
            </h2>

            <div className={styles.pricingGrid}>
              {/* Free */}
              <div className={styles.pricingCard} data-reveal>
                <p className={styles.pricingLabel}>Free</p>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>€0</span>
                  <span className={styles.pricingPeriod}>/mese</span>
                </div>
                <a
                  href="https://t.me/ExspensumBot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.btnOutline}
                >
                  Inizia gratis
                </a>
                <ul className={styles.featureList}>
                  {FREE_FEATURES.map((feat) => (
                    <li key={feat} className={styles.featureListItem}>
                      <Check size={14} className={styles.checkIcon} />
                      {feat}
                    </li>
                  ))}
                </ul>
                <p className={styles.pricingNote}>
                  Per chi vuole iniziare a tenere traccia senza impegno.
                </p>
              </div>

              {/* Premium */}
              <div className={`${styles.pricingCard} ${styles.pricingCardPremium}`} data-reveal>
                <div className={styles.pricingBadge}>Più popolare</div>
                <p className={styles.pricingLabel}>Premium</p>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>€4.99</span>
                  <span className={styles.pricingPeriod}>/mese</span>
                </div>
                <a
                  href="https://t.me/ExspensumBot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.btnPrimary}
                >
                  Passa a Premium
                </a>
                <ul className={styles.featureList}>
                  {PREMIUM_FEATURES.map((feat) => (
                    <li key={feat} className={styles.featureListItem}>
                      <Check size={14} className={styles.checkIcon} />
                      {feat}
                    </li>
                  ))}
                </ul>
                <p className={styles.pricingNote}>
                  Per chi vuole il massimo: grafici, budget, previsioni e storico completo.
                </p>
              </div>
            </div>

            <div className={styles.pricingCta} data-reveal>
              <p>Hai domande sul piano giusto per te?</p>
              <a href="mailto:expensum.finance@gmail.com" className={styles.ctaLink}>
                Contattaci →
              </a>
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ── */}
      <footer className={styles.footer}>
        {/* Top bar: logo + social */}
        <div className={styles.footerTopBar}>
          <div className={styles.footerLogoCombo}>
            <img src="/logo-expensum-icon.png" alt="" className={styles.footerLogoIcon} />
            <img src="/scritta_expensum.png" alt="Expensum" className={styles.footerLogoText} />
          </div>
          <div className={styles.footerSocials}>
            <a href="https://instagram.com/expensum.finance" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="Instagram">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="5"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>
            </a>
            <a href="https://t.me/ExspensumBot" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="Telegram">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path d="M21 5L2 12.5l7 1M21 5l-3 15-9-5.5M21 5L9 13.5m0 0V19l3-3"/></svg>
            </a>
            <a href="https://acesse.one/ite4lxk" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="Facebook">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>
            </a>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerSocialIcon} aria-label="Email">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 7 10 7 10-7"/></svg>
            </a>
          </div>
        </div>

        {/* Link grid */}
        <div className={styles.footerGrid}>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>Prodotto</p>
            <a href="#come-funziona" className={styles.footerGridLink}>Come funziona</a>
            <a href="#features" className={styles.footerGridLink}>Analytics</a>
            <a href="#features" className={styles.footerGridLink}>Abbonamenti automatici</a>
            <a href="#features" className={styles.footerGridLink}>Report mensili</a>
            <a href="#prezzi" className={styles.footerGridLink}>Prezzi</a>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>Per iniziare</p>
            <a href="https://t.me/ExspensumBot" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Apri su Telegram</a>
            <a href="#prezzi" className={styles.footerGridLink}>Piano Free</a>
            <a href="#prezzi" className={styles.footerGridLink}>Piano Premium</a>
            <a href="/login" className={styles.footerGridLink}>Accedi alla web app</a>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>Azienda</p>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerGridLink}>Chi siamo</a>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerGridLink}>Contatti</a>
            <a href="#" className={styles.footerGridLink}>Privacy Policy</a>
            <a href="#" className={styles.footerGridLink}>Termini di servizio</a>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>Seguici</p>
            <a href="https://instagram.com/expensum.finance" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Instagram</a>
            <a href="https://t.me/ExspensumBot" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Telegram</a>
            <a href="https://acesse.one/ite4lxk" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Facebook</a>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerGridLink}>Email</a>
          </div>
        </div>

        <div className={styles.footerBottom}>
          <p className={styles.footerCopy}>© {new Date().getFullYear()} Expensum — Il tuo compagno del risparmio.</p>
        </div>
      </footer>
    </>
  );
}
