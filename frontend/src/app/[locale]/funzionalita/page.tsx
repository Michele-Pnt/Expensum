import type { Metadata } from "next";
import { getMarketingContent } from "@/components/marketing/marketingContent";
import MarketingHero from "@/components/marketing/MarketingHero";
import MarketingShell from "@/components/marketing/MarketingShell";
import ProductScreenFrame from "@/components/marketing/ProductScreenFrame";
import styles from "../marketing-page.module.css";

export const metadata: Metadata = { title: "Funzionalità | Expensum", description: "Un ecosistema finanziario semplice per capire, organizzare e controllare le tue finanze." };

export default async function FeaturesPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params; const content = getMarketingContent(locale).features;
  return <MarketingShell><div className={styles.page}><MarketingHero eyebrow={content.eyebrow} title={content.title} intro={content.intro} ctaLabel={locale === "en" ? "Get access" : "Ottieni l’accesso"} waitlist />
    <section className={styles.featureShowcases} aria-label={content.eyebrow}>{content.items.map((item, index) => <article className={styles.featureShowcase} key={item.title}><div className={styles.featureCopy}><span>0{index + 1}</span><h2>{item.title}</h2><p>{item.text}</p></div><div className={styles.featureScreen}><ProductScreenFrame kind={item.screen} /></div></article>)}</section>
  </div></MarketingShell>;
}
