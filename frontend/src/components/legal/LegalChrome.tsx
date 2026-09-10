import Image from "next/image";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import styles from "@/app/[locale]/legal.module.css";

export default async function LegalChrome({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  const t = await getTranslations("Legal");

  return (
    <div className={styles.page}>
      <nav className={styles.nav}>
        <Link href="/" className={styles.navLogo}>
          <Image
            src="/logo-expensum-icon.png"
            alt="Expensum"
            width={28}
            height={28}
            className={styles.navLogoIcon}
          />
          <span className={styles.navLogoText}>Expensum</span>
        </Link>
        <Link href="/" className={styles.backLink}>{t("backToSite")}</Link>
      </nav>

      <main className={styles.main}>
        <div className={styles.header}>
          <h1 className={styles.title}>{title}</h1>
          <p className={styles.subtitle}>{subtitle}</p>
        </div>

        <div className={styles.embedWrap}>
          <div className={styles.legalContent}>{children}</div>
        </div>
      </main>

      <footer className={styles.footer}>
        <p className={styles.footerCopy}>{t("footerCopy", { year: new Date().getFullYear() })}</p>
        <div className={styles.footerLinks}>
          <Link href="/privacy" className={styles.footerLink}>{t("privacyPolicy")}</Link>
          <Link href="/cookies" className={styles.footerLink}>{t("cookiePolicy")}</Link>
          <Link href="/terms" className={styles.footerLink}>{t("termsOfService")}</Link>
        </div>
      </footer>
    </div>
  );
}
