"use client";

import React, { useEffect, useState } from "react";
import Image from "next/image";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import {
  Check,
  TrendingUp,
  ChevronDown,
  ShieldCheck,
  Server,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import AtomFeatureSection, { type AtomFeature } from "@/components/landing/AtomFeatureSection";
import HowItWorksSection, { type HowStep } from "@/components/landing/HowItWorksSection";
import ProductScreenFrame, { type ProductScreenKind } from "@/components/marketing/ProductScreenFrame";
import { openTallyWaitlist } from "@/lib/tallyWaitlist";
import { getReferralCode } from "@/lib/waitlist";
import styles from "./page.module.css";

const TALLY_FORM_ID = "44pAAr";

export default function LandingPage() {
  const t = useTranslations("Landing");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [expensesTracked, setExpensesTracked] = useState<number | null>(null);
  const [referralCode] = useState<string | null>(() => (
    typeof window === "undefined" ? null : getReferralCode(window.location.search)
  ));

  useEffect(() => {
    let cancelled = false;
    fetch("/api/public/stats")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data && typeof data.total_expenses_tracked === "number") {
          setExpensesTracked(data.total_expenses_tracked);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const openWaitlist = () => {
    void openTallyWaitlist(TALLY_FORM_ID, referralCode);
  };

  const scrollToWaitlist = () => {
    document.getElementById("hero-waitlist-form")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

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
  const atomItems = t.raw("features.orbitItems") as AtomFeature[];
  const howSteps = t.raw("comeFunziona.steps") as HowStep[];
  const freeFeatures = t.raw("pricing.free.features") as string[];
  const premiumFeatures = t.raw("pricing.premium.features") as string[];
  const journeyScreens: ProductScreenKind[] = ["overview", "goals", "report"];

  return (
    <div className={styles.landingRoot}>
      <div className={styles.persistentVideoBg} aria-hidden="true">
        <video
          className={styles.persistentVideo}
          src="/video/hero-logo.webm"
          poster="/video/hero-logo-poster.webp"
          autoPlay
          loop
          muted
          playsInline
          preload="metadata"
        />
        <div className={styles.persistentVideoScrim} />
      </div>

      {/* Strato decorativo fisso: luci soffuse che restano ferme in viewport
          mentre le sezioni scorrono sotto, effetto "faretti" sul nero. */}
      <div className={styles.spotlightLayer} aria-hidden="true">
        <span className={styles.spot1} />
        <span className={styles.spot2} />
        <span className={styles.spot3} />
      </div>

      {/* ── Navbar ── */}
      <nav className={styles.nav}>
        <div className={styles.navInner}>
          <div className={styles.navLogo}>
            <Image src="/logo-expensum-icon.png" alt="" className={styles.navLogoIcon} width={34} height={34} />
            <span className={styles.navLogoText}>Expensum</span>
          </div>
          <div className={styles.navLinks}>
            <button className={styles.navLink} onClick={() => scrollToSection("come-funziona")}>
              {t("nav.comeFunziona")}
            </button>
            <Link href="/funzionalita" className={styles.navLink}>Funzionalità</Link>
            <Link href="/sicurezza" className={styles.navLink}>Sicurezza</Link>
            <Link href="/faq" className={styles.navLink}>FAQ</Link>
          </div>
          <div className={styles.navActions}>
            {/* /login è una route Flask (proxata via next.config.ts rewrites),
                non una pagina Next.js localizzata: <a> semplice, niente Link con prefisso locale.
                "Registrati" è nascosto finché il prodotto è in beta privata a lista d'attesa:
                l'unico ingresso pubblico è il form waitlist nell'hero, per non contraddire
                il posizionamento "accesso esclusivo". */}
            <NextLink href="/login" className={styles.btnPrimary}>
              {t("nav.accedi")}
            </NextLink>
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
            <Link href="/funzionalita" className={styles.mobileMenuLink} onClick={() => setMobileMenuOpen(false)}>Funzionalità</Link>
            <Link href="/sicurezza" className={styles.mobileMenuLink} onClick={() => setMobileMenuOpen(false)}>Sicurezza</Link>
            <Link href="/faq" className={styles.mobileMenuLink} onClick={() => setMobileMenuOpen(false)}>FAQ</Link>
          </div>
        )}
      </nav>

      <main>
        {/* ── Hero ── */}
        <section className={styles.hero}>
          <div className={styles.heroInner}>
            <div className={styles.heroContent}>
              <div className={styles.heroPillGroup}>
                <p className={`${styles.heroPill} ${styles.heroPillBeta}`}>
                  {t("hero.betaBadge")}
                </p>
              </div>
              <h1 className={styles.heroHeadline}>
                {t("hero.headlineLine1")} {t("hero.headlineLine2")}
              </h1>
              <p className={styles.heroSub}>
                {t("hero.subLine1")} {t("hero.subLine2")}
              </p>
              {expensesTracked !== null && expensesTracked > 0 && (
                <div className={styles.heroStatBadge}>
                  <TrendingUp size={16} strokeWidth={2} />
                  <span>{t("hero.socialProof", { count: expensesTracked })}</span>
                </div>
              )}
              <div className={styles.heroActions}>
                <div id="hero-waitlist-form" className={styles.heroWaitlistForm}>
                  <div className={styles.waitlistPrompt}>
                    <div>
                      <span className={styles.waitlistEyebrow}>{t("hero.betaEyebrow")}</span>
                      <p>{t("hero.betaPrompt")}</p>
                    </div>
                    <button
                      type="button"
                      className={styles.waitlistButton}
                      onClick={openWaitlist}
                      data-tally-open={TALLY_FORM_ID}
                      data-tally-layout="modal"
                      data-tally-hide-title="1"
                    >
                      {t("hero.betaCta")} <span aria-hidden="true">→</span>
                    </button>
                  </div>
                </div>
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
                  <div className={styles.forWhoCopy}>
                    <strong className={styles.forWhoTitle}>{item.title}</strong>
                    <span className={styles.forWhoDesc}>{item.desc}</span>
                  </div>
                  <div className={styles.journeyPreview}>
                    <ProductScreenFrame kind={journeyScreens[i]} compact />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Cosa fa Expensum: sistema atomico scroll-driven ── */}
        <AtomFeatureSection
          eyebrow={t("features.atomEyebrow")}
          title={t("features.atomTitle")}
          intro={t("features.atomIntro")}
          scrollHint={t("features.atomScrollHint")}
          items={atomItems}
        />

        <div className={styles.dividerLine} />

        {/* ── Come funziona: sticky scroll, stesso comportamento dell'atomo ── */}
        <HowItWorksSection
          titleLine1={t("comeFunziona.titleLine1")}
          titleLine2={t("comeFunziona.titleLine2")}
          scrollHint={t("comeFunziona.scrollHint")}
          steps={howSteps}
        />

        {/* ── Trust strip ── */}
        <section className={styles.trustSection}>
          <div className={styles.sectionInner}>
            <div className={styles.trustHeader}>
              <div data-reveal>
                <span className={styles.trustEyebrow}>{t("trust.eyebrow")}</span>
                <h2>
                  {t("trust.titleLine1")}<br />
                  <span className={styles.trustTitleSecond}>{t("trust.titleLine2")}</span>
                </h2>
              </div>
              <p data-reveal-right="">{t("trust.intro")}</p>
            </div>
            <div className={styles.trustGrid}>
              <div className={styles.trustCard} data-reveal-left="">
                <span className={styles.trustCardLabel}>{t("trust.controlLabel")}</span>
                <ShieldCheck className={styles.trustCardIcon} size={25} strokeWidth={1.35} aria-hidden="true" />
                <h3>{t("trust.dashboardTitle")}</h3>
                <p>{t("trust.dashboardDesc")}</p>
              </div>
              <div className={styles.trustCard} data-reveal-right="">
                <span className={styles.trustCardLabel}>{t("trust.portabilityLabel")}</span>
                <Server className={styles.trustCardIcon} size={25} strokeWidth={1.35} aria-hidden="true" />
                <h3>{t("trust.secureTitle")}</h3>
                <p>{t("trust.secureDesc")}</p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Pricing ── */}
        {/* Nascosta temporaneamente (non eliminata): prodotto in beta privata,
            i piani a pagamento non vanno mostrati finché non si apre l'accesso pubblico. */}
        <section id="prezzi" className={styles.sectionAlt} style={{ display: "none" }}>
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
                  <span className={`${styles.pricingAmount} ${styles.pricingAmountBlurred}`}>€4.99</span>
                  <span className={`${styles.pricingPeriod} ${styles.pricingAmountBlurred}`}>{t("pricing.perMonth")}</span>
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
                <button onClick={scrollToWaitlist} className={styles.btnPrimary}>
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
              <Link href="/contatti" className={styles.ctaLink}>
                {t("pricing.ctaContact")}
              </Link>
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ── */}
      <footer className={styles.footer}>
        {/* Top bar: logo + social */}
        <div className={styles.footerTopBar}>
          <div className={styles.footerLogoCombo}>
            <Image src="/logo-expensum-icon.png" alt="" className={styles.footerLogoIcon} width={28} height={28} />
            <span className={styles.footerLogoText}>Expensum</span>
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
            <Link href="/funzionalita" className={styles.footerGridLink}>Funzionalità</Link>
            <Link href="/prezzi" className={styles.footerGridLink}>Prezzi</Link>
          </div>
          <div className={styles.footerCol}>
            <p className={styles.footerColTitle}>{t("footer.azienda")}</p>
            <Link href="/chi-siamo" className={styles.footerGridLink}>Chi siamo</Link>
            <Link href="/sicurezza" className={styles.footerGridLink}>Sicurezza</Link>
            <Link href="/faq" className={styles.footerGridLink}>FAQ</Link>
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
    </div>
  );
}
