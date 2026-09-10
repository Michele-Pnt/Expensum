import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import LegalChrome from "@/components/legal/LegalChrome";
import PrivacyContentIt from "@/components/legal/PrivacyContentIt";
import PrivacyContentEn from "@/components/legal/PrivacyContentEn";
import { routing } from "@/i18n/routing";
import { localeAlternates } from "@/i18n/seo";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const isEn = locale === "en";
  return {
    title: isEn ? "Privacy Policy | Expensum" : "Privacy Policy | Expensum",
    description: isEn
      ? "Expensum's notice on the processing of personal data under the GDPR."
      : "Informativa sul trattamento dei dati personali di Expensum ai sensi del GDPR.",
    alternates: localeAlternates("/privacy"),
  };
}

export default async function PrivacyPolicyPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const isEn = locale === "en";

  return (
    <LegalChrome
      title="Privacy Policy"
      subtitle={
        isEn
          ? "Notice on the processing of personal data under EU Regulation 2016/679 (GDPR) and Italian Legislative Decree 196/2003 as amended by Legislative Decree 101/2018. Last updated: September 2, 2026."
          : "Informativa sul trattamento dei dati personali ai sensi del Regolamento UE 2016/679 (GDPR) e del D.Lgs. 196/2003 come modificato dal D.Lgs. 101/2018. Ultimo aggiornamento: 2 settembre 2026."
      }
    >
      {isEn ? <PrivacyContentEn /> : <PrivacyContentIt />}
    </LegalChrome>
  );
}
