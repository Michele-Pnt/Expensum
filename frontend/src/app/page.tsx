"use client";
/* eslint-disable @next/next/no-img-element */

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Script from "next/script";
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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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
            const el = e.target as HTMLElement;
            const delay = el.dataset.delay ?? "0";
            setTimeout(() => el.classList.add("revealed"), Number(delay));
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.10 }
    );
    const selectors = ["[data-reveal]", "[data-reveal-left]", "[data-reveal-right]", "[data-reveal-scale]"];
    selectors.forEach((sel) =>
      document.querySelectorAll(sel).forEach((el) => io.observe(el))
    );
    return () => io.disconnect();
  }, []);

  const scrollToSection = (id: string) => {
    setMobileMenuOpen(false);
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
              Accedi su Telegram
            </a>
            {/* Hamburger — solo mobile */}
            <button
              className={styles.hamburger}
              onClick={() => setMobileMenuOpen((o) => !o)}
              aria-label="Menu"
            >
              <span className={`${styles.hamburgerLine} ${mobileMenuOpen ? styles.hamburgerLineOpen1 : ""}`} />
              <span className={`${styles.hamburgerLine} ${mobileMenuOpen ? styles.hamburgerLineOpen2 : ""}`} />
              <span className={`${styles.hamburgerLine} ${mobileMenuOpen ? styles.hamburgerLineOpen3 : ""}`} />
            </button>
          </div>
        </div>
        {/* Mobile dropdown — solo link di navigazione */}
        {mobileMenuOpen && (
          <div className={styles.mobileMenu}>
            <button className={styles.mobileMenuLink} onClick={() => scrollToSection("come-funziona")}>
              Come funziona
            </button>
            <button className={styles.mobileMenuLink} onClick={() => scrollToSection("prezzi")}>
              Prezzi
            </button>
          </div>
        )}
      </nav>

      <main>
        {/* ── Hero ── */}
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroLeft}>
              <p className={styles.heroPill}>Powered by AI</p>
              <h1 className={styles.heroHeadline}>
                Non chiederti dove sono finiti i tuoi soldi.<br />Inizia a dirgli dove andare.
              </h1>
              <p className={styles.heroSub}>
                Traccia le spese via Telegram. L’AI le analizza.<br />
                Tu capisci i tuoi soldi.
              </p>
              <div className={styles.heroActions}>
                {/* --- BOTTONI ORIGINALI (Nascosti) ---
                <a
                  href="https://t.me/ExspensumBot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.btnPrimary}
                >
                  Accedi su Telegram →
                </a>
                <button
                  className={styles.btnGhost}
                  onClick={() => scrollToSection("come-funziona")}
                >
                  Come funziona
                </button>
                ---------------------------------------- */}

                <div style={{ width: "100%", maxWidth: "450px", marginTop: "0.5rem" }}>
                  <iframe
                    data-tally-src="https://tally.so/embed/44pAAr?alignLeft=1&hideTitle=1&transparentBackground=1&dynamicHeight=1"
                    width="100%"
                    height="200"
                    title="Expensum Early Access"
                    style={{ border: "none", margin: 0, padding: 0 }}
                  ></iframe>
                  <Script src="https://tally.so/widgets/embed.js" strategy="lazyOnload" />
                </div>
              </div>
            </div>

            <div className={styles.heroRight} id="hero-right">
              <div className={styles.heroMascotWrap} id="hero-mascot">
                <img
                  src="/moneo/Moneo-base.png"
                  alt="Moneo, il tuo assistente finanziario"
                  className={styles.heroMascotImg}
                />
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
                <div
                  key={i}
                  className={styles.forWhoItem}
                  data-reveal-left=""
                  data-delay={i * 120}
                >
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
            <div className={styles.featureIllustration} data-reveal-scale="">
              <img
                src="/moneo/Moneo-AI-powered.png"
                alt="Moneo categorizza e analizza le tue spese con AI"
                className={styles.featureIllustrationImg}
              />
            </div>
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

            <div className={styles.useCaseVisual} data-reveal-scale="">
              <img
                src="/moneo/Expensum-use-case.png"
                alt="Fotografa lo scontrino, Expensum lo registra in automatico"
                className={styles.useCaseImg}
              />
            </div>

            <div className={styles.timeline}>
              <div className={styles.timelineLine} />
              {HOW_STEPS.map((step, i) => (
                <div
                  key={i}
                  className={`${styles.timelineRow} ${i % 2 === 1 ? styles.timelineRowRight : ""}`}
                  {...(i % 2 === 0 ? { "data-reveal-left": "" } : { "data-reveal-right": "" })}
                  data-delay={i * 100}
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

        {/* ── Trust strip ── */}
        <section className={styles.trustSection}>
          <div className={styles.sectionInner}>
            <div className={styles.trustGrid}>
              <div className={styles.trustCard} data-reveal-left="">
                <div className={styles.trustCardImgWrap}>
                  <img
                    src="/moneo/Moneo-money-helper.png"
                    alt="Analytics e portfolio growth"
                    className={styles.trustCardImg}
                  />
                </div>
                <div className={styles.trustCardText}>
                  <strong>Dashboard sempre aggiornata</strong>
                  <span>Grafici, trend e previsioni mensili. I tuoi dati finanziari in un colpo d&apos;occhio.</span>
                </div>
              </div>
              <div className={styles.trustCard} data-reveal-right="">
                <div className={styles.trustCardImgWrap}>
                  <img
                    src="/moneo/Moneo-secure.png"
                    alt="I tuoi dati sono al sicuro"
                    className={styles.trustCardImg}
                  />
                </div>
                <div className={styles.trustCardText}>
                  <strong>I tuoi dati al sicuro</strong>
                  <span>Sincronizzazione protetta su Notion. Nessun dato finanziario condiviso con terze parti.</span>
                </div>
              </div>
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
              <div className={styles.pricingCard} data-reveal>
                <p className={styles.pricingLabel}>Premium</p>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>€4.99</span>
                  <span className={styles.pricingPeriod}>/mese</span>
                </div>
                <a
                  href="https://t.me/ExspensumBot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.btnOutline}
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

              {/* Lifetime Founder */}
              <div className={`${styles.pricingCard} ${styles.pricingCardPremium}`} data-reveal>
                <div className={styles.pricingBadge}>Compila il form, Solo 90 posti!</div>
                <p className={styles.pricingLabel}>Lifetime Founder</p>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>€89</span>
                  <span className={styles.pricingPeriod}>/una tantum</span>
                </div>
                <button
                  onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                  className={styles.btnPrimary}
                >
                  Prenota il tuo posto
                </button>
                <ul className={styles.featureList}>
                  {PREMIUM_FEATURES.map((feat) => (
                    <li key={feat} className={styles.featureListItem}>
                      <Check size={14} className={styles.checkIcon} />
                      {feat}
                    </li>
                  ))}
                  <li className={styles.featureListItem}>
                    <Check size={14} className={styles.checkIcon} />
                    <strong>Accesso a vita, zero abbonamenti</strong>
                  </li>
                </ul>
                <p className={styles.pricingNote}>
                  Lancio a settembre. Entra nella lista d'attesa per bloccare l'offerta.
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
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="2" y="2" width="20" height="20" rx="5" /><circle cx="12" cy="12" r="5" /><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" /></svg>
            </a>
            <a href="https://t.me/ExspensumBot" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="Telegram">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path d="M21 5L2 12.5l7 1M21 5l-3 15-9-5.5M21 5L9 13.5m0 0V19l3-3" /></svg>
            </a>
            <a href="https://acesse.one/ite4lxk" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="Facebook">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z" /></svg>
            </a>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerSocialIcon} aria-label="Email">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m2 7 10 7 10-7" /></svg>
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
            <a href="https://t.me/ExspensumBot" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Accedi su Telegram</a>
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
