import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import LegalChrome from "@/components/legal/LegalChrome";
import CookiesContentIt from "@/components/legal/CookiesContentIt";
import CookiesContentEn from "@/components/legal/CookiesContentEn";
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
    title: isEn ? "Cookie Policy | Expensum" : "Cookie Policy | Expensum",
    description: isEn
      ? "Expensum's notice on the use of cookies."
      : "Informativa sull'uso dei cookie su Expensum.",
    alternates: localeAlternates("/cookies"),
  };
}

export default async function CookiePolicyPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const isEn = locale === "en";

  return (
    <LegalChrome
      title="Cookie Policy"
      subtitle={
        isEn
          ? "Notice on the use of cookies under Art. 122 of Italian Legislative Decree 196/2003 and the Italian Data Protection Authority's measures of May 8, 2014 and June 10, 2021. Last updated: July 1, 2026."
          : "Informativa sull'uso dei cookie ai sensi dell'Art. 122 del D.Lgs. 196/2003 e del Provvedimento del Garante dell'8 maggio 2014 e del 10 giugno 2021. Ultimo aggiornamento: 1 luglio 2026."
      }
    >
      {isEn ? <CookiesContentEn /> : <CookiesContentIt />}
    </LegalChrome>
  );
}
