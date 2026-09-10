import MarketingCta from "./MarketingCta";
import styles from "./MarketingHero.module.css";

type MarketingHeroProps = {
  eyebrow: string;
  title: string;
  intro: string;
  ctaLabel?: string;
  ctaHref?: string;
  waitlist?: boolean;
};

export default function MarketingHero({
  eyebrow,
  title,
  intro,
  ctaLabel,
  ctaHref,
  waitlist,
}: MarketingHeroProps) {
  return (
    <header className={styles.hero}>
      <p className={styles.eyebrow}>{eyebrow}</p>
      <h1>{title}</h1>
      <p className={styles.intro}>{intro}</p>
      {ctaLabel && <MarketingCta label={ctaLabel} href={ctaHref} waitlist={waitlist} />}
    </header>
  );
}
