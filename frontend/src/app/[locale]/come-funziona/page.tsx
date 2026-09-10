import type { Metadata } from "next";
import { getMarketingContent } from "@/components/marketing/marketingContent";
import MarketingHero from "@/components/marketing/MarketingHero";
import MarketingShell from "@/components/marketing/MarketingShell";
import ProductScreenFrame from "@/components/marketing/ProductScreenFrame";
import styles from "../marketing-page.module.css";

export const metadata: Metadata = { title: "Come funziona | Expensum", description: "Scopri come Expensum trasforma ogni spesa in una decisione più consapevole." };

export default async function HowItWorksPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params; const content = getMarketingContent(locale).how;
  return <MarketingShell><div className={styles.page}><MarketingHero eyebrow={content.eyebrow} title={content.title} intro={content.intro} ctaLabel={content.cta} waitlist />
    <section className={styles.steps} aria-label={content.eyebrow}>{content.steps.map((step, index) => <article className={styles.step} key={step.title}><div className={styles.stepCopy}><span className={styles.stepNumber}>0{index + 1}</span><h2>{step.title}</h2><p>{step.text}</p></div><div className={styles.screen}><ProductScreenFrame kind={step.screen} /></div></article>)}</section>
  </div></MarketingShell>;
}
