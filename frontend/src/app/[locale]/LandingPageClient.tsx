"use client";

import React, { useEffect, useState } from "react";
import Script from "next/script";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { MessageCircle, BarChart2, CreditCard, FileText, Check, Send, Sparkles, TrendingUp, BellRing, ChevronDown } from "lucide-react";
import { Link } from "@/i18n/navigation";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import styles from "./page.module.css";

const FEATURE_ICONS = [
  <MessageCircle key="chat" size={20} strokeWidth={1.5} />,
  <BarChart2 key="chart" size={20} strokeWidth={1.5} />,
  <CreditCard key="card" size={20} strokeWidth={1.5} />,
  <FileText key="file" size={20} strokeWidth={1.5} />,
];

const HOW_ICONS = [
  <Send key="send" size={18} strokeWidth={1.5} />,
  <Sparkles key="sparkles" size={18} strokeWidth={1.5} />,
  <TrendingUp key="trend" size={18} strokeWidth={1.5} />,
  <BellRing key="bell" size={18} strokeWidth={1.5} />,
];

export default function LandingPage() {
  const t = useTranslations("Landing");
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

  const forWhoItems = t.raw("perChi.items") as { title: string; desc: string }[];
  const featureItems = t.raw("features.items") as { title: string; desc: string }[];
  const howSteps = t.raw("comeFunziona.steps") as { title: string; desc: string }[];
  const freeFeatures = t.raw("pricing.free.features") as string[];
  const premiumFeatures = t.raw("pricing.premium.features") as string[];

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
              {t("nav.comeFunziona")}
            </button>
            <button className={styles.navLink} onClick={() => scrollToSection("prezzi")}>
              {t("nav.prezzi")}
            </button>
          </div>
          <div className={styles.navActions}>
            {/* /login e /register sono route Flask (proxate via next.config.ts rewrites),
                non pagine Next.js localizzate: <a> semplice, niente Link con prefisso locale. */}
            <a href="/login" className={styles.btnGhost}>
              {t("nav.accedi")}
            </a>
            <a href="/register" className={styles.btnPrimary}>
              {t("nav.registrati")}
            </a>
            <LanguageSwitcher />
            {/* Hamburger — solo mobile */}
            <button
              className={styles.hamburger}
              onClick={() => setMobileMenuOpen((o) => !o)}
              aria-label={t("nav.menu")}
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
              {t("nav.comeFunziona")}
            </button>
            <button className={styles.mobileMenuLink} onClick={() => scrollToSection("prezzi")}>
              {t("nav.prezzi")}
            </button>
          </div>
        )}
      </nav>

      <main>
        {/* ── Hero ── */}
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroLeft}>
              <div className={styles.heroPillGroup} aria-label="Stato del servizio">
                <p className={styles.heroPill}>{t("hero.pill")}</p>
                <p className={`${styles.heroPill} ${styles.heroPillBeta}`}>
                  Beta privata ad accesso esclusivo
                </p>
              </div>
              <h1 className={styles.heroHeadline}>
                {t("hero.headlineLine1")}<br />{t("hero.headlineLine2")}
              </h1>
              <p className={styles.heroSub}>
                {t("hero.subLine1")}<br />
                {t("hero.subLine2")}
              </p>
              <div className={styles.heroActions}>
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
                <Image
                  src="/moneo/Moneo-base.png"
                  alt={t("hero.mascotAlt")}
                  className={styles.heroMascotImg}
                  width={800}
                  height={800}
                  priority
                  sizes="(max-width: 768px) 100vw, 50vw"
                  style={{ width: "100%", height: "auto" }}
                />
              </div>
            </div>
          </div>

          <button
            className={styles.heroScroll}
            onClick={() => scrollToSection("per-chi")}
            aria-label={t("hero.scrollDown")}
          >
            <ChevronDown size={20} strokeWidth={1.5} />
          </button>
        </section>

        {/* ── Per chi è pensato ── */}
        <section id="per-chi" className={styles.section}>
          <div className={styles.sectionInner}>
            <div className={styles.sectionHeadLeft}>
              <h2 className={styles.sectionH2} data-reveal>
                {t("perChi.titleLine1")}<br />{t("perChi.titleLine2")}
              </h2>
            </div>
            <div className={styles.forWhoList}>
              {forWhoItems.map((item, i) => (
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
              {t("features.titlePart1")}{" "}
              <span className={styles.h2Muted}>{t("features.titlePart2")}</span>
              <br />
              <span className={styles.h2Muted}>{t("features.titlePart3")}</span>
            </h2>
            <div className={styles.featureIllustration} data-reveal-scale="">
              <Image
                src="/moneo/Moneo-AI-powered.png"
                alt={t("features.illustrationAlt")}
                className={styles.featureIllustrationImg}
                width={1200}
                height={800}
                sizes="(max-width: 768px) 100vw, 80vw"
                style={{ width: "100%", height: "auto" }}
              />
            </div>
            <div className={styles.featureGrid} data-reveal>
              {featureItems.map((f, i) => (
                <div key={i} className={styles.featureCard}>
                  <div className={styles.featureIcon}>{FEATURE_ICONS[i]}</div>
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
              {t("comeFunziona.titleLine1")}<br />{t("comeFunziona.titleLine2")}
            </h2>

            <div className={styles.useCaseVisual} data-reveal-scale="">
              <Image
                src="/moneo/Expensum-use-case.png"
                alt={t("comeFunziona.useCaseAlt")}
                className={styles.useCaseImg}
                width={460}
                height={600}
                sizes="(max-width: 768px) 100vw, 460px"
                style={{ width: "100%", height: "auto" }}
              />
            </div>

            <div className={styles.timeline}>
              <div className={styles.timelineLine} />
              {howSteps.map((step, i) => (
                <div
                  key={i}
                  className={`${styles.timelineRow} ${i % 2 === 1 ? styles.timelineRowRight : ""}`}
                  {...(i % 2 === 0 ? { "data-reveal-left": "" } : { "data-reveal-right": "" })}
                  data-delay={i * 100}
                >
                  <div className={styles.timelineCard}>
                    <div className={styles.timelineStep}>{i + 1}</div>
                    <div className={styles.timelineIcon}>{HOW_ICONS[i]}</div>
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
                  <Image
                    src="/moneo/Moneo-money-helper.png"
                    alt={t("trust.dashboardAlt")}
                    className={styles.trustCardImg}
                    width={600}
                    height={500}
                    sizes="(max-width: 768px) 100vw, 50vw"
                    style={{ width: "100%", height: "auto" }}
                  />
                </div>
                <div className={styles.trustCardText}>
                  <strong>{t("trust.dashboardTitle")}</strong>
                  <span>{t("trust.dashboardDesc")}</span>
                </div>
              </div>
              <div className={styles.trustCard} data-reveal-right="">
                <div className={styles.trustCardImgWrap}>
                  <Image
                    src="/moneo/Moneo-secure.png"
                    alt={t("trust.secureAlt")}
                    className={styles.trustCardImg}
                    width={600}
                    height={500}
                    sizes="(max-width: 768px) 100vw, 50vw"
                    style={{ width: "100%", height: "auto" }}
                  />
                </div>
                <div className={styles.trustCardText}>
                  <strong>{t("trust.secureTitle")}</strong>
                  <span>{t("trust.secureDesc")}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── Pricing ── */}
        <section id="prezzi" className={styles.sectionAlt}>
          <div className={styles.sectionInner}>
            <h2 className={styles.sectionH2Full} data-reveal>
              {t("pricing.title")}
            </h2>

            <div className={styles.pricingGrid}>
              {/* Free */}
              <div className={styles.pricingCard} data-reveal>
                <p className={styles.pricingLabel}>{t("pricing.free.label")}</p>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>€0</span>
                  <span className={styles.pricingPeriod}>{t("pricing.perMonth")}</span>
                </div>
                <ul className={styles.featureList}>
                  {freeFeatures.map((feat) => (
                    <li key={feat} className={styles.featureListItem}>
                      <Check size={14} className={styles.checkIcon} />
                      {feat}
                    </li>
                  ))}
                </ul>
                <p className={styles.pricingNote}>
                  {t("pricing.free.note")}
                </p>
              </div>

              {/* Premium */}
              <div className={styles.pricingCard} data-reveal>
                <p className={styles.pricingLabel}>{t("pricing.premium.label")}</p>
                <div className={styles.pricingPrice}>
                  <span className={`${styles.pricingAmount} ${styles.pricingAmountBlurred}`} aria-hidden="true">€4.99</span>
                  <span className={`${styles.pricingPeriod} ${styles.pricingAmountBlurred}`} aria-hidden="true">{t("pricing.perMonth")}</span>
                  <span className={styles.pricingComingSoon}>{t("pricing.premium.comingSoon")}</span>
                </div>
                <ul className={styles.featureList}>
                  {premiumFeatures.map((feat) => (
                    <li key={feat} className={styles.featureListItem}>
                      <Check size={14} className={styles.checkIcon} />
                      {feat}
                    </li>
                  ))}
                </ul>
                <p className={styles.pricingNote}>
                  {t("pricing.premium.note")}
                </p>
              </div>

              {/* Lifetime Founder */}
              <div className={`${styles.pricingCard} ${styles.pricingCardPremium}`} data-reveal>
                <div className={styles.pricingBadge}>{t("pricing.lifetime.badge")}</div>
                <p className={styles.pricingLabel}>{t("pricing.lifetime.label")}</p>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>€89</span>
                  <span className={styles.pricingPeriod}>{t("pricing.oneTime")}</span>
                </div>
                <button
                  onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                  className={styles.btnPrimary}
                >
                  {t("pricing.lifetime.cta")}
                </button>
                <ul className={styles.featureList}>
                  {premiumFeatures.map((feat) => (
                    <li key={feat} className={styles.featureListItem}>
                      <Check size={14} className={styles.checkIcon} />
                      {feat}
                    </li>
                  ))}
                  <li className={styles.featureListItem}>
                    <Check size={14} className={styles.checkIcon} />
                    <strong>{t("pricing.lifetime.lifetimeAccess")}</strong>
                  </li>
                </ul>
                <p className={styles.pricingNote}>
                  {t("pricing.lifetime.note")}
                </p>
              </div>
            </div>

            <div className={styles.pricingCta} data-reveal>
              <p>{t("pricing.ctaQuestion")}</p>
              <a href="mailto:expensum.finance@gmail.com" className={styles.ctaLink}>
                {t("pricing.ctaContact")}
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
            <a href="https://acesse.one/ite4lxk" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="Facebook">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z" /></svg>
            </a>
            <a href="https://www.linkedin.com/company/expensum/" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="LinkedIn">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
                <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
                <rect x="2" y="9" width="4" height="12" />
                <circle cx="4" cy="4" r="2" />
              </svg>
            </a>
            <a href="https://www.tiktok.com/@expensum" target="_blank" rel="noopener noreferrer" className={styles.footerSocialIcon} aria-label="TikTok">
              <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 4v10.5a3.5 3.5 0 1 1-3.5-3.5c.35 0 .69.05 1 .14" />
                <path d="M14 4a4.5 4.5 0 0 0 4.5 4.5" />
              </svg>
            </a>
          </div>
        </div>

        {/* Link grid */}
        <div className={styles.footerGrid}>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>{t("footer.prodotto")}</p>
            <a href="#come-funziona" className={styles.footerGridLink}>{t("footer.comeFunziona")}</a>
            <a href="#features" className={styles.footerGridLink}>{t("footer.analytics")}</a>
            <a href="#features" className={styles.footerGridLink}>{t("footer.abbonamenti")}</a>
            <a href="#features" className={styles.footerGridLink}>{t("footer.reportMensili")}</a>
            <a href="#prezzi" className={styles.footerGridLink}>{t("footer.prezzi")}</a>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>{t("footer.perIniziare")}</p>
            <a href="#prezzi" className={styles.footerGridLink}>{t("footer.pianoFree")}</a>
            <a href="#prezzi" className={styles.footerGridLink}>{t("footer.pianoPremium")}</a>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>{t("footer.azienda")}</p>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerGridLink}>{t("footer.chiSiamo")}</a>
            <Link href="/contatti" className={styles.footerGridLink}>{t("footer.contatti")}</Link>
            <Link href="/come-funziona-moneo" className={styles.footerGridLink}>{t("footer.comeFunzionaAI")}</Link>
            <Link href="/privacy" className={styles.footerGridLink}>{t("footer.privacyPolicy")}</Link>
            <Link href="/cookies" className={styles.footerGridLink}>{t("footer.cookiePolicy")}</Link>
            <Link href="/terms" className={styles.footerGridLink}>{t("footer.terminiServizio")}</Link>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>{t("footer.seguici")}</p>
            <a href="https://instagram.com/expensum.finance" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Instagram</a>
            <a href="https://acesse.one/ite4lxk" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>Facebook</a>
            <a href="https://www.linkedin.com/company/expensum/" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>LinkedIn</a>
            <a href="https://www.tiktok.com/@expensum" target="_blank" rel="noopener noreferrer" className={styles.footerGridLink}>TikTok</a>
            <a href="mailto:expensum.finance@gmail.com" className={styles.footerGridLink}>Email</a>
          </div>
        </div>
        
        <div className={styles.footerBottom}>
          <p className={styles.footerCopy}>{t("footer.copy", { year: new Date().getFullYear() })}</p>
        </div>
      </footer>
    </>
  );
}
