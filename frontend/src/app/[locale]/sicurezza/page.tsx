import type { Metadata } from "next";
import { getMarketingContent } from "@/components/marketing/marketingContent";
import MarketingHero from "@/components/marketing/MarketingHero";
import MarketingShell from "@/components/marketing/MarketingShell";
import styles from "../marketing-page.module.css";

export const metadata: Metadata = { title: "Sicurezza e privacy | Expensum", description: "Come Expensum protegge e tratta i tuoi dati finanziari." };

export default async function SecurityPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params; const content = getMarketingContent(locale).security;
  return <MarketingShell><div className={styles.page}><MarketingHero eyebrow={content.eyebrow} title={content.title} intro={content.intro} ctaLabel={locale === "en" ? "Read the privacy policy" : "Leggi la Privacy Policy"} ctaHref="/privacy" /><section className={styles.sectionGrid}><div><h2 className={styles.sectionTitle}>{locale === "en" ? "Your data. Your boundaries." : "I tuoi dati. I tuoi confini."}</h2><p className={styles.sectionIntro}>{locale === "en" ? "We explain what Expensum needs and why, without hiding behind technical language." : "Ti spieghiamo cosa serve a Expensum e perché, senza nasconderci dietro il linguaggio tecnico."}</p></div><ul className={styles.securityList}>{content.points.map((point) => <li key={point}>{point}</li>)}</ul></section></div></MarketingShell>;
}
