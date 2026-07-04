import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import LegalChrome from "@/components/legal/LegalChrome";
import TermsContentIt from "@/components/legal/TermsContentIt";
import TermsContentEn from "@/components/legal/TermsContentEn";
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
    title: isEn ? "Terms of Service — Expensum" : "Termini di Servizio — Expensum",
    description: isEn
      ? "General terms of use of the Expensum service."
      : "Condizioni generali d'uso del servizio Expensum.",
    alternates: localeAlternates("/terms"),
  };
}

export default async function TermsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const isEn = locale === "en";

  return (
    <LegalChrome
      title={isEn ? "Terms of Service" : "Termini di Servizio"}
      subtitle={
        isEn
          ? "General terms of use of the Expensum service. Last updated: July 1, 2026."
          : "Condizioni generali d'uso del servizio Expensum. Ultimo aggiornamento: 1 luglio 2026."
      }
    >
      {isEn ? <TermsContentEn /> : <TermsContentIt />}
    </LegalChrome>
  );
}
