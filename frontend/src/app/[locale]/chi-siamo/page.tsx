import type { Metadata } from "next";
import { getMarketingContent } from "@/components/marketing/marketingContent";
import MarketingHero from "@/components/marketing/MarketingHero";
import MarketingShell from "@/components/marketing/MarketingShell";
import styles from "../marketing-page.module.css";

export const metadata: Metadata = { title: "Chi siamo | Expensum", description: "La storia e il punto di vista dietro Expensum." };

export default async function AboutPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params; const content = getMarketingContent(locale).about;
  return <MarketingShell><div className={styles.page}><MarketingHero eyebrow={content.eyebrow} title={content.title} intro={content.intro} ctaLabel={locale === "en" ? "Build it with us" : "Costruiscilo con noi"} waitlist /><section className={styles.sectionGrid}><div><h2 className={styles.sectionTitle}>{locale === "en" ? "A small team, a practical ambition." : "Un team piccolo, un’ambizione concreta."}</h2><p className={styles.sectionIntro}>{locale === "en" ? "We are starting from the everyday questions people ask themselves about money." : "Partiamo dalle domande concrete che le persone si fanno ogni giorno sui propri soldi."}</p></div><div className={styles.people}>{content.people.map((person) => <div className={styles.person} key={person}>{person}</div>)}</div></section></div></MarketingShell>;
}
