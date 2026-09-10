import type { Metadata } from "next";
import { getMarketingContent } from "@/components/marketing/marketingContent";
import MarketingHero from "@/components/marketing/MarketingHero";
import MarketingCta from "@/components/marketing/MarketingCta";
import MarketingShell from "@/components/marketing/MarketingShell";
import styles from "../marketing-page.module.css";

export const metadata: Metadata = { title: "Prezzi e beta privata | Expensum", description: "Scopri come partecipare alla beta privata di Expensum." };

export default async function PricingPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params; const content = getMarketingContent(locale).pricing;
  return <MarketingShell><div className={styles.page}><MarketingHero eyebrow={content.eyebrow} title={content.title} intro={content.intro} /><section className={styles.cards}>{content.cards.map(([title, text, cta], index) => <article className={styles.priceCard} key={title}><h2>{title}</h2><p>{text}</p>{index === 0 ? <MarketingCta label={cta} waitlist /> : <span className={styles.sectionIntro}>{cta}</span>}</article>)}</section></div></MarketingShell>;
}
