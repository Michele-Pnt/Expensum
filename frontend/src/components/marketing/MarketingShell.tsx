import Image from "next/image";
import { Menu } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import MarketingCta from "./MarketingCta";
import { MARKETING_FOOTER_NAVIGATION, MARKETING_NAVIGATION } from "./marketingNavigation";
import styles from "./MarketingShell.module.css";

type MarketingShellProps = {
  children: React.ReactNode;
};

export default function MarketingShell({ children }: MarketingShellProps) {
  const t = useTranslations("Marketing");

  return (
    <div className={styles.root}>
      <div className={styles.atmosphere} aria-hidden="true" />
      <header className={styles.header}>
        <Link className={styles.logo} href="/">
          <Image src="/logo-expensum-icon.png" alt="" width={30} height={30} />
          <span>Expensum</span>
        </Link>
        <nav className={styles.nav} aria-label={t("nav.label")}>
          {MARKETING_NAVIGATION.map(({ href, labelKey }) => <Link key={href} href={href}>{t(labelKey)}</Link>)}
        </nav>
        <div className={styles.actions}>
          <LanguageSwitcher />
          <div className={styles.headerCta}><MarketingCta label={t("nav.cta")} waitlist /></div>
          <details className={styles.mobileMenu}>
            <summary aria-label={t("nav.menu")}><Menu size={20} /></summary>
            <nav aria-label={t("nav.label")}>
              {MARKETING_NAVIGATION.map(({ href, labelKey }) => <Link key={href} href={href}>{t(labelKey)}</Link>)}
              <Link className={styles.mobileCta} href="/#hero-waitlist-form">{t("nav.cta")}</Link>
            </nav>
          </details>
        </div>
      </header>
      <main>{children}</main>
      <footer className={styles.footer}>
        <div className={styles.footerTop}>
          <div>
            <Link className={styles.logo} href="/">
              <Image src="/logo-expensum-icon.png" alt="" width={26} height={26} />
              <span>Expensum</span>
            </Link>
            <p>{t("footer.mission")}</p>
          </div>
          <MarketingCta label={t("footer.cta")} waitlist />
        </div>
        <div className={styles.footerBottom}>
          <span>© {new Date().getFullYear()} Expensum</span>
          <nav aria-label={t("footer.label")}>
            {MARKETING_FOOTER_NAVIGATION.map(({ href, labelKey }) => <Link key={href} href={href}>{t(labelKey)}</Link>)}
          </nav>
        </div>
      </footer>
    </div>
  );
}
