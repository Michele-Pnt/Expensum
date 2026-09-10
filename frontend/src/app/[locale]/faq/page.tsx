import type { Metadata } from "next";
import { getMarketingContent } from "@/components/marketing/marketingContent";
import FaqAccordion from "@/components/marketing/FaqAccordion";
import MarketingHero from "@/components/marketing/MarketingHero";
import MarketingShell from "@/components/marketing/MarketingShell";
import styles from "../marketing-page.module.css";

export const metadata: Metadata = { title: "FAQ | Expensum", description: "Le risposte alle domande più comuni su Expensum." };

export default async function FaqPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params; const content = getMarketingContent(locale).faq;
  return <MarketingShell><div className={styles.page}><MarketingHero eyebrow={content.eyebrow} title={content.title} intro={content.intro} /><section className={styles.section}><FaqAccordion items={content.items} /></section></div></MarketingShell>;
}
